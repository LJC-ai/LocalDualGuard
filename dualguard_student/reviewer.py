"""DualGuard-Student 输出二次复核器（硬性规则 4 第二层审核）。

主模型生成输出后必须经过本复核器：
- 复用 StudentRuleset 扫描；
- 命中即 BLOCK 并替换为"知识点 / 局部逻辑"安全提示；
- 未命中才放行原输出。

与 SecReviewer 同样的接口契约，注入到同一份 RiskEngine，
但规则集不同、安全提示文案不同。
"""
from __future__ import annotations

from common.risk_engine import ReviewResult

from .rules import StudentRuleset, make_safe_hint


class StudentReviewer:
    """学生版二次复核器。"""

    name = "student_reviewer"

    def __init__(self) -> None:
        self.ruleset = StudentRuleset()

    def review(self, user_input: str, raw_output: str) -> ReviewResult:
        if not raw_output:
            return ReviewResult(action="ALLOW", safe_output=raw_output)

        hits = self.ruleset.scan(raw_output)
        if not hits and user_input:
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
