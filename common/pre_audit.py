"""前置审核 AI 接口（可插拔，硬性规则 4）。

业务硬性要求："输入前置审核 AI 校验，主模型输出后二次复核"。
即用户输入先过 PreAuditAI（轻量模型，只判定是否拦截/放行），
放行后才进入主模型；主模型输出再过 Reviewer（业务版各自实现）。

为避免绑定具体厂商，本模块定义抽象基类 PreAuditAI：
- 业务版本可注入任意实现（OpenAI 兼容、本地小模型、纯规则替身等）；
- 提供一个 RuleBasedPreAudit 作为默认兜底实现，把业务规则当作"前置审核 AI"使用，
  保证开发期 / 离线场景下整套链路依然可运行。

任何 PreAuditAI 实现都必须返回 PreAuditResult，统一字段：
- action: ALLOW / BLOCK
- category: BLOCK 时的违规类别（用于落库）
- reason: 人类可读原因
"""
from __future__ import annotations

import abc
import re
from dataclasses import dataclass, field
from typing import List, Tuple


# -------------------------------------------------------------------- #
#  返回结果
# -------------------------------------------------------------------- #
ACTION_ALLOW = "ALLOW"
ACTION_BLOCK = "BLOCK"


@dataclass
class PreAuditResult:
    action: str
    category: str = ""
    reason: str = ""
    # 命中的规则片段（调试 / 取证用，不会回显给用户）
    matched_snippets: List[str] = field(default_factory=list)


# -------------------------------------------------------------------- #
#  抽象基类
# -------------------------------------------------------------------- #
class PreAuditAI(abc.ABC):
    """前置审核 AI 抽象接口。所有实现必须实现 audit()。"""

    name: str = "abstract"

    @abc.abstractmethod
    def audit(self, user_input: str) -> PreAuditResult:
        """对用户输入做前置审核。"""
        raise NotImplementedError


# -------------------------------------------------------------------- #
#  规则驱动的默认前置审核实现
# -------------------------------------------------------------------- #
class RuleBasedPreAudit(PreAuditAI):
    """把业务规则当作"前置审核 AI"使用的兜底实现。

    实际生产中可替换为对接 OpenAI 兼容接口的 LlmPreAudit，
    但本类保证离线 / 测试环境也能跑通双层审核链路。
    """

    name = "rule_based_pre_audit"

    def __init__(self, ruleset) -> None:
        """
        ruleset: 业务版本提供的规则集合对象，需暴露方法：
            scan(text) -> List[(category, reason, snippet)]
        """
        self.ruleset = ruleset

    def audit(self, user_input: str) -> PreAuditResult:
        if not user_input:
            return PreAuditResult(action=ACTION_ALLOW)
        hits = self.ruleset.scan(user_input)
        if not hits:
            return PreAuditResult(action=ACTION_ALLOW)
        # 取第一条命中即可（多条命中也只记一条违规）
        cat, reason, snippet = hits[0]
        return PreAuditResult(
            action=ACTION_BLOCK,
            category=cat,
            reason=reason,
            matched_snippets=[snippet],
        )


# -------------------------------------------------------------------- #
#  扩展接口说明
# -------------------------------------------------------------------- #
# 真实 LLM 前置审核实现在 common/llm_adapter.py 中的 LlmPreAudit 类。
# 本模块仅定义抽象基类和规则兜底实现，避免循环依赖。
