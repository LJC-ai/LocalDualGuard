"""AES 加密的违规记录存储。

设计目标（严格对应硬性规则 3）：
1. AES 加密：每条违规记录以 Fernet（AES-128-CBC + HMAC-SHA256）加密落盘，
   防止直接读取明文。Fernet 自带 HMAC，本身具备记录级防篡改。
2. 防篡改：除 Fernet 内置 HMAC 外，整库再叠加一个 HMAC-SHA256 签名文件，
   任一字节被改动下次启动即被 audit_hash 模块识别。
3. 防系统时间绕过：
   - 维护单调计数器 monotonic_counter（永不回退，落盘）。
   - 维护 last_wall_time（上次记录的真实墙钟时间）。
   - 写入时若 now_wall < last_wall_time - tolerance，判定为时间回拨，
     直接触发冻结（lock_state = FROZEN_BY_ROLLBACK），不接受新写入。
   - 即便攻击者改时间，monotonic_counter 也只增不减，无法把已写入的违规"抹掉"。

文件格式（violations.enc）：
    每行一个 base64(Fernet token)，token 解密后为 JSON：
    {
      "ts": 1234567890.0,        # 墙钟时间戳
      "mc": 42,                  # 单调计数器
      "category": "EXPLOIT_CODE",
      "reason": "...",           # 拦截原因
      "preview": "..."           # 触发内容摘要（已截断）
    }

文件末尾最后一行恒为：
    {"__sig__": "<hex-hmac>", "count": N, "max_mc": M}
    该行不加密，但内容是被加密记录列表的 HMAC-SHA256 签名，
    任何对历史记录的删改都会让验签失败。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from .config import RiskConfig
from .paths import AppPaths


# -------------------------------------------------------------------- #
#  违规记录数据结构
# -------------------------------------------------------------------- #
@dataclass
class ViolationRecord:
    """单条违规记录。"""

    ts: float                  # 墙钟时间戳（time.time()）
    mc: int                    # 单调计数器（永不回退）
    category: str              # 违规类别（来自业务规则）
    reason: str                # 拦截原因
    preview: str               # 触发内容摘要（已截断）

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "ViolationRecord":
        return cls(**json.loads(raw))


# -------------------------------------------------------------------- #
#  锁定状态枚举
# -------------------------------------------------------------------- #
LOCK_STATE_OK = "OK"
LOCK_STATE_LOCKED_72H = "LOCKED_72H"            # 累计 3 次锁定 72h
LOCK_STATE_FROZEN_BY_ROLLBACK = "FROZEN_BY_ROLLBACK"  # 时间回拨/篡改冻结
LOCK_STATE_FROZEN_BY_TAMPER = "FROZEN_BY_TAMPER"      # 审核文件被篡改冻结


# -------------------------------------------------------------------- #
#  存储实现
# -------------------------------------------------------------------- #
class AuditStorage:
    """违规记录加密存储 + 时间防绕过。"""

    def __init__(self, paths: AppPaths, config: RiskConfig) -> None:
        self.paths = paths
        self.config = config
        self._fernet: Optional[Fernet] = None
        # 运行期单调计数器（从落盘值继续递增）
        self._monotonic_counter: int = 0
        self._last_wall_time: float = 0.0

    # ----------------------- 密钥管理 ----------------------- #
    def _load_or_create_kek(self) -> bytes:
        """加载或首次创建 KEK（32 字节随机）。

        KEK 文件权限由 paths.ensure_dirs 之后的安装脚本设置；
        本模块不负责权限位（跨平台差异由打包脚本处理）。
        """
        kek_path = self.paths.kek_file
        if kek_path.exists():
            return kek_path.read_bytes()
        kek = secrets.token_bytes(32)
        # 原子写：先写临时文件再 rename，避免半写
        tmp = kek_path.with_suffix(".tmp")
        tmp.write_bytes(kek)
        tmp.replace(kek_path)
        try:
            # 限制权限：仅当前用户可读写（Linux chmod 600；Windows 也能调用）
            os.chmod(kek_path, 0o600)
        except OSError:
            pass
        return kek

    @property
    def fernet(self) -> Fernet:
        if self._fernet is None:
            kek = self._load_or_create_kek()
            # Fernet 要求 32 字节 base64url 编码的密钥
            fernet_key = base64.urlsafe_b64encode(kek)
            self._fernet = Fernet(fernet_key)
        return self._fernet

    # ----------------------- 单调状态 ----------------------- #
    def _load_monotonic_state(self) -> None:
        """加载落盘的单调计数器与上次墙钟时间。"""
        path = self.paths.monotonic_file
        if not path.exists():
            self._monotonic_counter = 0
            self._last_wall_time = time.time()
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._monotonic_counter = int(data.get("mc", 0))
            self._last_wall_time = float(data.get("last_wall", 0.0))
        except (json.JSONDecodeError, ValueError):
            # 状态文件被破坏 → 视为篡改 → 触发冻结
            self._mark_frozen(LOCK_STATE_FROZEN_BY_TAMPER)
            self._monotonic_counter = -1  # 哨兵值
            self._last_wall_time = 0.0

    def _save_monotonic_state(self) -> None:
        path = self.paths.monotonic_file
        payload = json.dumps({
            "mc": self._monotonic_counter,
            "last_wall": self._last_wall_time,
        })
        tmp = path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    # ----------------------- 锁定状态 ----------------------- #
    def read_lock_state(self) -> str:
        path = self.paths.lock_file
        if not path.exists():
            return LOCK_STATE_OK
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return str(data.get("state", LOCK_STATE_OK))
        except (json.JSONDecodeError, OSError):
            return LOCK_STATE_FROZEN_BY_TAMPER

    def _mark_frozen(self, state: str) -> None:
        path = self.paths.lock_file
        payload = json.dumps({
            "state": state,
            "ts": time.time(),
            "mc": self._monotonic_counter,
        })
        path.write_text(payload, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    # ----------------------- 防时间回拨 ----------------------- #
    def _check_clock_rollback(self) -> bool:
        """返回 True 表示检测到时间回拨。"""
        now = time.time()
        if self._last_wall_time > 0 and \
                now < self._last_wall_time - self.config.clock_rollback_tolerance_sec:
            return True
        return False

    # ----------------------- 启动初始化 ----------------------- #
    def initialize(self) -> str:
        """启动时调用：加载状态、检测时间回拨。

        返回当前锁定状态。若检测到回拨，直接写入冻结状态。
        """
        self._load_monotonic_state()
        existing_state = self.read_lock_state()

        # 已被冻结就不再放行
        if existing_state in (LOCK_STATE_FROZEN_BY_ROLLBACK,
                              LOCK_STATE_FROZEN_BY_TAMPER):
            return existing_state

        if self._check_clock_rollback():
            self._mark_frozen(LOCK_STATE_FROZEN_BY_ROLLBACK)
            return LOCK_STATE_FROZEN_BY_ROLLBACK

        # 若之前处于 72h 锁定，需检查是否已到解锁时间
        if existing_state == LOCK_STATE_LOCKED_72H:
            self.refresh_lock_if_expired()

        return self.read_lock_state()

    # ----------------------- 写入违规 ----------------------- #
    def append_violation(self, category: str, reason: str,
                         preview: str) -> Tuple[bool, str]:
        """追加一条违规记录。

        返回 (success, current_lock_state)。
        若已被冻结 / 锁定，写入仍会被记录（用于取证），但业务层应据此拦截对话。
        """
        # 防时间回拨：每次写入前再校验一次
        if self._check_clock_rollback():
            self._mark_frozen(LOCK_STATE_FROZEN_BY_ROLLBACK)
            return False, LOCK_STATE_FROZEN_BY_ROLLBACK

        now = time.time()
        self._monotonic_counter += 1
        self._last_wall_time = now

        preview = (preview or "")[:200]
        record = ViolationRecord(
            ts=now,
            mc=self._monotonic_counter,
            category=category,
            reason=reason,
            preview=preview,
        )

        token = self.fernet.encrypt(record.to_json().encode("utf-8"))
        # 追加（按行）
        with open(self.paths.violations_db, "ab") as f:
            f.write(token + b"\n")

        # 更新整库 HMAC 签名
        self._rewrite_signature()

        # 同步单调状态（必须在签名之后，确保下次启动能正确读到最新计数器）
        self._save_monotonic_state()

        # 计数达阈值 → 72h 锁定
        violations = self.list_violations()
        if len(violations) >= self.config.lock_threshold:
            self._lock_for_hours(self.config.lock_hours)

        return True, self.read_lock_state()

    # ----------------------- 读出所有违规 ----------------------- #
    def list_violations(self) -> List[ViolationRecord]:
        """解密读取全部违规记录。文件不存在或解密失败时返回空列表。"""
        path = self.paths.violations_db
        if not path.exists():
            return []
        out: List[ViolationRecord] = []
        with open(path, "rb") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith(b"{"):
                    # 签名行，跳过
                    continue
                try:
                    plain = self.fernet.decrypt(line).decode("utf-8")
                    out.append(ViolationRecord.from_json(plain))
                except InvalidToken:
                    # 单条记录被篡改 → 整体视为被篡改，触发冻结
                    self._mark_frozen(LOCK_STATE_FROZEN_BY_TAMPER)
                    return out
        return out

    # ----------------------- 整库签名 ----------------------- #
    def _compute_records_hmac(self) -> bytes:
        """对 violations.db 中所有加密行计算 HMAC-SHA256。"""
        key = base64.urlsafe_b64encode(self._load_or_create_kek())
        h = hmac.new(key, digestmod=hashlib.sha256)
        path = self.paths.violations_db
        if path.exists():
            with open(path, "rb") as f:
                for line in f:
                    if line.strip() and not line.startswith(b"{"):
                        h.update(line.strip())
        return h.digest()

    def _rewrite_signature(self) -> None:
        """重写整库签名行。"""
        sig = self._compute_records_hmac().hex()
        violations = self.list_violations()
        payload = json.dumps({
            "__sig__": sig,
            "count": len(violations),
            "max_mc": self._monotonic_counter,
        })
        # 重写整个文件：所有 token 行 + 最后一行签名
        path = self.paths.violations_db
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as out:
            if path.exists():
                with open(path, "rb") as src:
                    for line in src:
                        if line.strip() and not line.startswith(b"{"):
                            out.write(line if line.endswith(b"\n") else line + b"\n")
            out.write(payload.encode("utf-8") + b"\n")
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def verify_signature(self) -> bool:
        """启动时验签：True 表示未被篡改。"""
        path = self.paths.violations_db
        if not path.exists():
            return True
        expected = self._compute_records_hmac().hex()
        with open(path, "rb") as f:
            lines = f.readlines()
        if not lines:
            return True
        last = lines[-1].strip()
        try:
            data = json.loads(last)
            return hmac.compare_digest(str(data.get("__sig__", "")), expected)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    # ----------------------- 锁定逻辑 ----------------------- #
    def _lock_for_hours(self, hours: int) -> None:
        unlock_at = time.time() + hours * 3600
        path = self.paths.lock_file
        payload = json.dumps({
            "state": LOCK_STATE_LOCKED_72H,
            "ts": time.time(),
            "unlock_at": unlock_at,
            "mc": self._monotonic_counter,
        })
        path.write_text(payload, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def refresh_lock_if_expired(self) -> None:
        """72h 锁定到期后清除锁定（保留违规记录历史）。"""
        state = self.read_lock_state()
        if state != LOCK_STATE_LOCKED_72H:
            return
        try:
            data = json.loads(self.paths.lock_file.read_text(encoding="utf-8"))
            unlock_at = float(data.get("unlock_at", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            return
        if time.time() >= unlock_at:
            # 解锁但保留 violations 记录（仍达 3 条）—— 业务上可继续对话，
            # 但若再违规则立即重新锁定。这里直接清除 lock 文件。
            self.paths.lock_file.unlink(missing_ok=True)

    # ----------------------- 备份 ----------------------- #
    def backup_audit_file(self) -> None:
        """把审核策略文件备份到 backup 目录（启动时调用）。"""
        src = self.paths.audit_file
        dst = self.paths.audit_backup
        if not src.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
