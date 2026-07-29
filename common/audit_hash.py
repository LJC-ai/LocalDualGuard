"""审核文件哈希校验与自动恢复（硬性规则 3 收尾要求）。

程序开机优先校验审核文件哈希：
1. 启动时读取 audit_policy.json 的实际 SHA256；
2. 与 audit_policy.sha256 中保存的预期哈希比对（恒定时间比较）；
3. 若不一致：
   - 尝试用 backup/audit_policy.json.bak 自动恢复；
   - 若恢复后哈希仍不一致，触发冻结；
   - 若无备份可恢复，直接冻结；
4. 若哈希文件本身被删，但审核文件存在 → 视为篡改 → 触发冻结；
5. 若二者都不存在 → 视为首次启动，从业务规则重新生成审核策略文件并写入哈希。

哈希文件本身也通过 audit_storage._compute_records_hmac 的 KEK 保护：
我们写入哈希文件时把 (sha256, hmac) 一起写，启动校验时先验 HMAC 再比对 SHA256。
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Optional, Tuple

from .paths import AppPaths


TAMPER_DETECTED = "TAMPER_DETECTED"
RESTORED_FROM_BACKUP = "RESTORED_FROM_BACKUP"
FRESH_GENERATED = "FRESH_GENERATED"
OK = "OK"


def sha256_of_file(path: Path) -> str:
    """计算文件的 SHA256（按 64KB 分块）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class AuditHashGuard:
    """审核文件哈希守卫：启动时校验 + 自动恢复。"""

    def __init__(self, paths: AppPaths, kek_provider) -> None:
        """
        kek_provider: 一个无参可调用，返回 32 字节 KEK。
        由 audit_storage.AuditStorage 提供，避免本模块重复读 KEK。
        """
        self.paths = paths
        self._kek_provider = kek_provider

    # ----------------------- 哈希文件读写 ----------------------- #
    def _hmac_of(self, message: str) -> str:
        import base64
        key = base64.urlsafe_b64encode(self._kek_provider())
        return hmac.new(key, message.encode("utf-8"),
                        digestmod=hashlib.sha256).hexdigest()

    def _write_hash_file(self, sha: str) -> None:
        payload = json.dumps({
            "sha256": sha,
            "hmac": self._hmac_of(sha),
        })
        tmp = self.paths.audit_hash_file.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.paths.audit_hash_file)

    def _read_hash_file(self) -> Optional[Tuple[str, str]]:
        """返回 (sha256, hmac)。文件不存在或损坏返回 None。"""
        path = self.paths.audit_hash_file
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sha = str(data.get("sha256", ""))
            sig = str(data.get("hmac", ""))
            if not sha or not sig:
                return None
            return sha, sig
        except (json.JSONDecodeError, OSError):
            return None

    def _verify_hash_file_integrity(self, sha: str, sig: str) -> bool:
        """验哈希文件自身 HMAC，防止攻击者只改 sha256 字段。"""
        expected = self._hmac_of(sha)
        return hmac.compare_digest(expected, sig)

    # ----------------------- 启动主流程 ----------------------- #
    def verify_on_startup(self, regenerator) -> str:
        """启动校验主入口。

        regenerator: 无参可调用，返回新生成的审核策略 JSON 字符串。
                     （由各业务版本的 rules 模块提供）

        返回状态码：
          OK                  - 校验通过
          RESTORED_FROM_BACKUP - 审核文件被篡改，已从备份恢复
          FRESH_GENERATED     - 首次启动，重新生成
          TAMPER_DETECTED     - 检测到篡改且无法恢复
        """
        audit_path = self.paths.audit_file
        backup_path = self.paths.audit_backup

        # 路径 A: 审核文件 + 哈希文件 均不存在 → 首次启动
        if not audit_path.exists() and not self.paths.audit_hash_file.exists():
            content = regenerator()
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(content, encoding="utf-8")
            self._write_hash_file(sha256_of_file(audit_path))
            return FRESH_GENERATED

        # 路径 B: 哈希文件被删但审核文件存在 → 篡改
        if audit_path.exists() and not self.paths.audit_hash_file.exists():
            return TAMPER_DETECTED

        # 路径 C: 哈希文件存在但自身被篡改 → 篡改
        record = self._read_hash_file()
        if record is None:
            return TAMPER_DETECTED
        expected_sha, sig = record
        if not self._verify_hash_file_integrity(expected_sha, sig):
            return TAMPER_DETECTED

        # 路径 D: 审核文件不存在但哈希文件存在 → 异常
        if not audit_path.exists():
            return TAMPER_DETECTED

        # 路径 E: 正常比对
        actual_sha = sha256_of_file(audit_path)
        if hmac.compare_digest(actual_sha, expected_sha):
            return OK

        # 不一致 → 尝试恢复
        if backup_path.exists():
            backup_sha = sha256_of_file(backup_path)
            # 备份本身也要匹配预期哈希
            if hmac.compare_digest(backup_sha, expected_sha):
                audit_path.write_bytes(backup_path.read_bytes())
                # 恢复后再次确认
                if hmac.compare_digest(sha256_of_file(audit_path), expected_sha):
                    return RESTORED_FROM_BACKUP
        return TAMPER_DETECTED

    def write_current(self) -> None:
        """重新写入当前审核文件的哈希（用于审计策略合法更新后）。"""
        if self.paths.audit_file.exists():
            self._write_hash_file(sha256_of_file(self.paths.audit_file))
