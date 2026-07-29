"""统一风控引擎（硬性规则 3、4 的枢纽）。

职责：
1. 接收用户输入 → 调用前置审核 AI（pre_audit）→ 若 BLOCK 记录违规、弹窗、（达阈值）锁定；
2. 接收主模型输出 → 调用业务版 reviewer 二次复核 → 若 BLOCK 同样记录违规；
3. 维护当前锁定状态：被锁定 / 被冻结时拒绝处理任何输入；
4. 单次违规弹窗（warn_on_single_violation）；
5. 累计 3 次锁定 72 小时；
6. 启动时联动 audit_hash 守卫（篡改 → 自动恢复 / 冻结）。

引擎本身不知道任何业务规则，规则通过依赖注入传入：
- pre_audit: PreAuditAI（前置审核）
- reviewer: 业务版本提供的 Reviewer 实例（输出二次复核）
- audit_policy_regen: 重新生成审核策略文件的回调（用于首次启动 / 恢复）

业务层调用顺序（不可跳过的双层审核）：
    engine.startup_health_check()                  # 启动哈希校验
    state = engine.check_lock_status()             # 锁定 / 冻结检查
    if state != OK: 拒绝服务
    pre = engine.audit_input(user_input)           # ① 前置审核
    if pre.action == BLOCK: 弹窗 + 落库 + 返回
    raw_output = main_model.generate(user_input)   # 主模型（业务自调）
    review = engine.audit_output(user_input, raw_output)  # ② 二次复核
    if review.action == BLOCK: 弹窗 + 落库 + 返回安全提示
    return review.safe_output
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from .audit_hash import AuditHashGuard, OK, RESTORED_FROM_BACKUP, \
    FRESH_GENERATED, TAMPER_DETECTED
from .audit_storage import (
    AuditStorage,
    LOCK_STATE_OK,
    LOCK_STATE_LOCKED_72H,
    LOCK_STATE_FROZEN_BY_ROLLBACK,
    LOCK_STATE_FROZEN_BY_TAMPER,
)
from .config import RiskConfig, DEFAULT_CONFIG
from .paths import AppPaths
from .pre_audit import PreAuditAI, PreAuditResult, ACTION_BLOCK, ACTION_ALLOW


# -------------------------------------------------------------------- #
#  弹窗实现（跨平台）
# -------------------------------------------------------------------- #
def popup_warn(message: str, title: str = "DualGuard 风控警告") -> None:
    """跨平台弹窗。Windows 用 ctypes 调 MessageBox；Linux 用 zenity 或 tkinter。"""
    try:
        if _is_windows():
            _win_popup(message, title)
        else:
            _posix_popup(message, title)
    except Exception:
        # 弹窗失败不影响主流程，仅打印到 stderr
        import sys
        print(f"[DualGuard Popup] {title}: {message}", file=sys.stderr)


def _is_windows() -> bool:
    import sys
    return sys.platform.startswith("win")


def _win_popup(message: str, title: str) -> None:
    import ctypes
    # MB_OK | MB_ICONWARNING = 0x0 | 0x30
    ctypes.windll.user32.MessageBoxW(0, message, title, 0x30)


def _posix_popup(message: str, title: str) -> None:
    import shutil
    import subprocess
    if shutil.which("zenity"):
        subprocess.run([
            "zenity", "--warning", f"--title={title}", f"--text={message}"
        ], check=False)
        return
    # 兜底用 tkinter
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(title, message)
        root.destroy()
    except Exception:
        import sys
        print(f"[DualGuard Popup] {title}: {message}", file=sys.stderr)


# -------------------------------------------------------------------- #
#  复核结果（业务 reviewer 返回）
# -------------------------------------------------------------------- #
@dataclass
class ReviewResult:
    action: str                    # ALLOW / BLOCK
    category: str = ""
    reason: str = ""
    safe_output: str = ""          # BLOCK 时给出安全替代输出
    matched_snippets: list = None


# -------------------------------------------------------------------- #
#  引擎主类
# -------------------------------------------------------------------- #
class RiskEngine:
    """统一风控引擎。"""

    def __init__(
        self,
        paths: AppPaths,
        config: RiskConfig = DEFAULT_CONFIG,
    ) -> None:
        self.paths = paths
        self.config = config
        self.storage = AuditStorage(paths, config)
        # 审核策略文件首次启动时的重新生成器（由业务版本注入）
        self._audit_policy_regen: Optional[Callable[[], str]] = None
        # 前置审核 AI（启动后由业务版本注入，未注入则任何输入都视为 ALLOW）
        self._pre_audit: Optional[PreAuditAI] = None
        # 业务版 reviewer（输出二次复核，由业务版本注入）
        self._reviewer = None

    # ----------------------- 依赖注入 ----------------------- #
    def set_audit_policy_regen(self, fn: Callable[[], str]) -> None:
        self._audit_policy_regen = fn

    def set_pre_audit(self, pre: PreAuditAI) -> None:
        self._pre_audit = pre

    def set_reviewer(self, reviewer) -> None:
        """注入业务版的二次复核器。reviewer 需实现 review(input, output) -> ReviewResult。"""
        self._reviewer = reviewer

    # ----------------------- 启动校验 ----------------------- #
    def startup_health_check(self) -> str:
        """启动时哈希校验 + 时间回拨检测。

        返回最终锁定状态。业务层据此决定是否放行。
        """
        self.paths.ensure_dirs()
        # 先做审核文件哈希校验（规则要求：开机优先校验）
        regen = self._audit_policy_regen or (lambda: "{}")
        guard = AuditHashGuard(self.paths, kek_provider=self.storage._load_or_create_kek)
        hash_state = guard.verify_on_startup(regen)

        if hash_state == TAMPER_DETECTED:
            # 触发冻结
            self.storage._mark_frozen(LOCK_STATE_FROZEN_BY_TAMPER)
            popup_warn(
                "检测到审核文件被篡改，且无法从备份恢复。\n"
                "对话已被冻结，请联系管理员。",
                title="DualGuard 安全告警"
            )
            return LOCK_STATE_FROZEN_BY_TAMPER

        if hash_state == RESTORED_FROM_BACKUP:
            popup_warn(
                "检测到审核文件被篡改，已自动从备份恢复。",
                title="DualGuard 安全告警"
            )
            # 恢复后仍可继续服务
        elif hash_state == FRESH_GENERATED:
            # 首次启动，备份新生成的审核策略
            self.storage.backup_audit_file()

        # 哈希校验通过 → 检查时间回拨 + 已有锁定状态
        lock_state = self.storage.initialize()

        if lock_state == LOCK_STATE_FROZEN_BY_ROLLBACK:
            popup_warn(
                "检测到系统时间回拨（疑似绕过锁定），对话已被冻结。",
                title="DualGuard 安全告警"
            )
        elif lock_state == LOCK_STATE_FROZEN_BY_TAMPER:
            popup_warn(
                "审核状态文件被篡改，对话已被冻结。",
                title="DualGuard 安全告警"
            )

        return lock_state

    # ----------------------- 锁定状态查询 ----------------------- #
    def check_lock_status(self) -> str:
        """业务层每次对话前调用：返回当前锁定状态。"""
        # 锁定到期清理
        self.storage.refresh_lock_if_expired()
        return self.storage.read_lock_state()

    def is_service_available(self) -> bool:
        """便捷方法：是否仍可对话。"""
        return self.check_lock_status() == LOCK_STATE_OK

    # ----------------------- 前置审核 ----------------------- #
    def audit_input(self, user_input: str) -> PreAuditResult:
        """① 前置审核：拦截违规输入。"""
        # 被锁定/冻结时直接 BLOCK（业务层应已拦截，这里兜底）
        state = self.check_lock_status()
        if state != LOCK_STATE_OK:
            return PreAuditResult(
                action=ACTION_BLOCK,
                category="LOCKED",
                reason=f"当前对话处于锁定/冻结状态（{state}）",
            )

        if self._pre_audit is None:
            return PreAuditResult(action=ACTION_ALLOW)

        try:
            result = self._pre_audit.audit(user_input)
        except Exception as e:
            # 前置审核 AI 报错 → 安全失败，拒绝放行
            return PreAuditResult(
                action=ACTION_BLOCK,
                category="PRE_AUDIT_ERROR",
                reason=f"前置审核异常：{e}",
            )

        if result.action == ACTION_BLOCK:
            self._handle_violation(
                category=result.category or "PRE_AUDIT_BLOCK",
                reason=result.reason or "前置审核拦截",
                preview=user_input,
            )
        return result

    # ----------------------- 二次复核 ----------------------- #
    def audit_output(self, user_input: str, raw_output: str) -> ReviewResult:
        """② 主模型输出后二次复核。"""
        if self._reviewer is None:
            return ReviewResult(action=ACTION_ALLOW, safe_output=raw_output)

        try:
            result = self._reviewer.review(user_input, raw_output)
        except Exception as e:
            return ReviewResult(
                action=ACTION_BLOCK,
                category="REVIEW_ERROR",
                reason=f"二次复核异常：{e}",
                safe_output="（输出已因复核异常被拦截）",
            )

        if result.action == ACTION_BLOCK:
            self._handle_violation(
                category=result.category or "OUTPUT_BLOCK",
                reason=result.reason or "二次复核拦截",
                preview=raw_output,
            )
        return result

    # ----------------------- 违规处理 ----------------------- #
    def _handle_violation(self, category: str, reason: str, preview: str) -> None:
        """统一违规处理：记录 + 弹窗。锁定由 storage 内部按阈值触发。"""
        ok, state = self.storage.append_violation(category, reason, preview)

        if self.config.warn_on_single_violation:
            msg = f"检测到违规内容（{category}）。\n原因：{reason}"
            if state == LOCK_STATE_LOCKED_72H:
                msg += f"\n累计达到 {self.config.lock_threshold} 次，对话已锁定 {self.config.lock_hours} 小时。"
            popup_warn(msg)

    # ----------------------- 状态查看（供 CLI / 调试） ----------------------- #
    def status_report(self) -> str:
        state = self.check_lock_status()
        violations = self.storage.list_violations()
        lines = [
            f"Edition        : {self.paths.edition}",
            f"Lock state     : {state}",
            f"Violations     : {len(violations)}",
            f"Lock threshold : {self.config.lock_threshold} -> {self.config.lock_hours}h",
            f"Last wall time : {self.storage._last_wall_time}",
            f"Monotonic cnt  : {self.storage._monotonic_counter}",
        ]
        return "\n".join(lines)
