"""DualGuard-Sec 输出二次复核器（硬性规则 4 第二层审核）。

主模型生成输出后，必须经过本复核器：
- 复用 SecRuleset 扫描输出文本；
- 命中即返回 BLOCK + 安全提示（理论思路）；
- 未命中才放行原输出。

业务硬性要求："双层审核逻辑不可跳过" ——
common.risk_engine.RiskEngine.audit_output() 永远会调用本复核器，
不存在"绕过 reviewer 直出"的代码路径。
"""
from __future__ import annotations

from common.risk_engine import ReviewResult

from .rules import SecRuleset, make_safe_hint


class SecReviewer:
    """安全版二次复核器。"""

    name = "sec_reviewer"

    def __init__(self) -> None:
        self.ruleset = SecRuleset()

    def review(self, user_input: str, raw_output: str) -> ReviewResult:
        """对主模型输出做二次审核。

        扫描对象既包含输出，也包含"输入+输出"的拼接（防止输出靠引用输入绕过）。
        """
        if not raw_output:
            return ReviewResult(action="ALLOW", safe_output=raw_output)

        # 先扫输出本身
        hits = self.ruleset.scan(raw_output)
        if not hits and user_input:
            # 再扫"输入->输出"组合（检测把攻击载荷塞进引用块的情况）
            hits = self.ruleset.scan(f"{user_input}\n---\n{raw_output}")

        if not hits:
            return ReviewResult(action="ALLOW", safe_output=raw_output)

        category, reason, snippet = hits[0]
        return ReviewResult(
            action="BLOCK",
            category=category,
            reason=reason,
            safe_output=make_safe_hint(category),
            matched_snippets=[snippet],
        )
