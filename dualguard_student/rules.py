"""DualGuard-Student 学生业务版的拦截规则。

风控目标（硬性规则 2 - 学生版）：
- 拦截完整作业答案（"直接交作业级别"的整段答案）
- 拦截全套 Scratch 图形化搭建流程（每积木逐块给出 + 完整运行步骤）
- 仅提供知识点、局部逻辑讲解

判定思路：抓"整段答案"与"全套搭建"两个特征词族，
对"知识点 / 思路 / 局部逻辑"类请求放行，避免误伤正常学习。
"""
from __future__ import annotations

import re
from typing import List, Tuple

Hit = Tuple[str, str, str]


# -------------------------------------------------------------------- #
#  规则定义
# -------------------------------------------------------------------- #
STUDENT_RULES: List[Tuple[str, str, "re.Pattern"]] = [
    # --- 完整作业答案 --------------------------------------------- #
    (
        "FULL_ANSWER",
        "请求生成可直接提交的完整作业答案",
        re.compile(
            r"(?i)("
            r"给我\s*(?:一份\s*)?(?:完整|全部|可以直接交|可直接提交)\s*(?:的\s*)?(?:作业\s*)?答案|"
            r"把(?:整道|这道|所有)\s*(?:题|作业)\s*(?:的\s*)?答案\s*(?:都\s*)?(?:写完整|给全|列出来)|"
            r"(?:完整\s*)?作业答案\s*(?:一份|直接发|发我)|"
            r"(?:帮我写|代写)\s*(?:一份\s*)?(?:完整\s*)?(?:作业|论文|实验报告)"
            r")"
        ),
    ),
    (
        "FULL_ANSWER",
        "请求把题目要求逐条照搬转化为成段答案",
        re.compile(
            r"(?i)("
            r"按(?:题目|要求)\s*(?:逐条|一条不落|全部)\s*(?:作答|写出来)|"
            r"把\s*(?:所有|全部)\s*(?:空|题)\s*(?:都\s*)?(?:填上|答出来|写完)"
            r")"
        ),
    ),

    # --- 全套 Scratch 图形化搭建流程 ------------------------------ #
    # 关键词组：scratch + (完整|所有|整套|每一步|从零) + (搭|拼|积木)
    # 允许中文与英文混排、词序灵活（用 .{0,15}? 连接关键词）。
    (
        "SCRATCH_FULL_TUTORIAL",
        "请求提供整套 Scratch 图形化积木搭建流程",
        re.compile(
            r"(?i)scratch.{0,15}?(?:完整|所有|整套|每一步|从零|一步一步)"
            r".{0,15}?(?:搭|拼|积木|代码|脚本|清单)"
        ),
    ),
    (
        "SCRATCH_FULL_TUTORIAL",
        "请求把整套 Scratch 程序/积木完整搭出来",
        re.compile(
            r"(?i)(?:完整|整个|全套|所有)\s*scratch.{0,15}?(?:搭出来|搭给我|拼出来|列出来|写出来)"
        ),
    ),
    (
        "SCRATCH_FULL_TUTORIAL",
        "请求逐块列出 Scratch 完整积木清单（可直接照搬）",
        re.compile(
            r"(?i)scratch.{0,15}?积木.{0,15}?(?:全部|完整|所有|每块).{0,10}?(?:列|写|给)"
        ),
    ),
]


class StudentRuleset:
    """学生版规则集合。"""

    name = "student_ruleset"

    def scan(self, text: str) -> List[Hit]:
        if not text:
            return []
        hits: List[Hit] = []
        for category, reason, pattern in STUDENT_RULES:
            m = pattern.search(text)
            if m:
                start = max(0, m.start() - 10)
                end = min(len(text), m.end() + 30)
                snippet = text[start:end].replace("\n", " ")
                hits.append((category, reason, snippet))
        return hits


# -------------------------------------------------------------------- #
#  审核策略快照（哈希校验使用）
# -------------------------------------------------------------------- #
def regenerate_audit_policy() -> str:
    import json
    snapshot = {
        "edition": "student",
        "rule_count": len(STUDENT_RULES),
        "categories": sorted({c for c, _, _ in STUDENT_RULES}),
        "patterns": [
            {"category": c, "reason": r, "pattern": p.pattern}
            for c, r, p in STUDENT_RULES
        ],
    }
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2)


# -------------------------------------------------------------------- #
#  安全替代输出（知识点 / 局部逻辑模板）
#  硬性规则 2 学生版："仅提供知识点、局部逻辑讲解"
# -------------------------------------------------------------------- #
SAFE_HINT_TEMPLATE = (
    "【DualGuard-Student 拦截】请求的内容属于学生版风控拦截范围（{category}），"
    "无法提供可直接提交的完整答案 / 整套 Scratch 搭建流程。\n\n"
    "可提供的辅导内容：\n"
    "1. 相关知识点（涉及的语法 / 概念 / 公式）；\n"
    "2. 解题思路与切入点（不直接给整段答案）；\n"
    "3. 局部代码或单块积木的逻辑讲解（非完整可照搬）；\n"
    "4. 自检方向（边界条件、常见错误）。\n\n"
    "建议你基于以上提示自己动手完成，遇到具体卡点再继续提问。"
)


def make_safe_hint(category: str) -> str:
    return SAFE_HINT_TEMPLATE.format(category=category)
