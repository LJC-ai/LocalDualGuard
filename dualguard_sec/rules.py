"""DualGuard-Sec 安全业务版的拦截规则。

规则只用于检测与拦截（防御性用途），不包含任何真实攻击载荷；
模式基于公开的、约定俗成的关键词与目录命名约定（如 msfconsole、
exploit/windows/*、reverse shell one-liner 等），
仅用于在用户请求生成此类内容时阻断并改为输出理论思路。

规则分类（category）：
    EXPLOIT_SCRIPT   - 漏洞攻击脚本（payload/shellcode/MSF 模块路径）
    WINLINK_EXPLOIT  - Winlink 利用代码（针对 Winlink / Winlink Express 软件）
    PENETRATION_LIVE - 公共网络渗透实操（针对真实目标的渗透步骤）
    WEAPONIZED_CODE  - 直接武器化的代码（如 ready-to-run reverse shell）

scan(text) 返回 [(category, reason, snippet)] 列表，
供 RuleBasedPreAudit 与 Reviewer 共用。
"""
from __future__ import annotations

import re
from typing import List, Tuple

# 单条命中返回类型
Hit = Tuple[str, str, str]


# -------------------------------------------------------------------- #
#  规则定义：每条规则 = (category, reason, compiled_pattern)
#  正则使用 IGNORECASE，且尽量精确避免误伤教学讨论。
# -------------------------------------------------------------------- #
SEC_RULES: List[Tuple[str, str, "re.Pattern"]] = [
    # --- 漏洞攻击脚本 / 武器化 payload ----------------------------- #
    (
        "EXPLOIT_SCRIPT",
        "请求生成漏洞攻击脚本或武器化 payload",
        re.compile(
            r"(?i)("
            r"metasploit|msfconsole|msfvenom|"
            r"exploit/(?:windows|linux|multi|unix)/[a-z0-9_/]+|"
            r"shellcode\s*(?:generator|payload)|"
            r"reverse\s*shell\s*(?:one[-\s]?liner|script)|"
            r"bind\s*shell\s*script|"
            r"cobalt\s*strike\s*(?:beacon|script)|"
            r"empire\s*(?:stager|agent)|"
            r"mimikatz\s*(?:dump|execute)|"
            r"\bpowershell\s+(?:-enc|-e\s)|"        # powershell -enc base64 是典型武器化标志
            r"\bbash\s+-i\s>&\s*/dev/tcp|"         # 反弹 shell 经典 one-liner
            r"nc\s+-e\s+/bin/(?:sh|bash)"
            r")"
        ),
    ),
    (
        "EXPLOIT_SCRIPT",
        "请求生成漏洞 PoC 武器化代码",
        re.compile(
            r"(?i)("
            r"给我一个\s*(?:完整的\s*)?(?:exploit|漏洞\s*利用|攻击\s*脚本|payload)|"
            r"生成\s*(?:一段|一个)\s*(?:可运行|可执行)的\s*(?:exploit|payload|攻击代码)|"
            r"写一个\s*(?:完整的\s*)?(?:rce|远程命令执行|漏洞\s*利用)\s*(?:exp|脚本|代码)"
            r")"
        ),
    ),

    # --- Winlink 利用代码 ----------------------------------------- #
    # Winlink 是业余无线电邮件软件；规则检测针对其已知缺陷的利用请求。
    (
        "WINLINK_EXPLOIT",
        "请求生成针对 Winlink 软件的利用代码",
        re.compile(
            r"(?i)("
            r"winlink\s*express\s*(?:exploit|漏洞\s*利用|攻击|exp)|"
            r"winlink\s+(?:rce|lfi|sqli|溢出|提权|unauth)|"
            r"针对\s*winlink\s*(?:的\s*)?(?:漏洞|exp|攻击脚本|利用代码)|"
            r"winlink.*?(?:payload|shellcode|reverse\s*shell)"
            r")"
        ),
    ),

    # --- 公共网络渗透实操 ----------------------------------------- #
    # 检测"针对真实/公共目标"的逐步实操请求，区分于"靶场/教学"。
    (
        "PENETRATION_LIVE",
        "请求针对真实公共目标的渗透实操步骤",
        re.compile(
            r"(?i)("
            r"渗透\s*(?:一下|攻击|入侵)\s*(?:www\.|https?://|[0-9]{1,3}(?:\.[0-9]{1,3}){3})|"
            r"(?:入侵|攻破|拿下)\s*(?:某公司|某站点|真实\s*目标|线上\s*系统)|"
            r"如何\s*(?:渗透|攻击)\s*(?:github\.com|google\.com|baidu\.com|taobao\.com|政府|银行)|"
            r"扫描\s*(?:互联网|公网)\s*(?:上\s*)?(?:所有|批量)\s*(?:开放\s*端口|漏洞)"
            r")"
        ),
    ),
    (
        "PENETRATION_LIVE",
        "请求生成针对真实目标的有效扫描/爆破载荷",
        re.compile(
            r"(?i)("
            r"针对\s*(?:真实|生产)\s*环境\s*(?:的\s*)?(?:hydra|medusa|nmap\s*-sS|masscan)|"
            r"对\s*(?:真实|线上)\s*服务器\s*进行\s*(?:nmap\s*-sS|端口扫描|漏洞扫描|爆破)"
            r")"
        ),
    ),
]


class SecRuleset:
    """安全版规则集合。供 RuleBasedPreAudit 与 SecReviewer 共用。"""

    name = "sec_ruleset"

    def scan(self, text: str) -> List[Hit]:
        if not text:
            return []
        hits: List[Hit] = []
        for category, reason, pattern in SEC_RULES:
            m = pattern.search(text)
            if m:
                # 截取命中上下文，便于落库 preview
                start = max(0, m.start() - 10)
                end = min(len(text), m.end() + 30)
                snippet = text[start:end].replace("\n", " ")
                hits.append((category, reason, snippet))
        return hits


# -------------------------------------------------------------------- #
#  审核策略文件生成器（启动哈希校验使用）
#  内容是规则摘要的 JSON 快照，仅用于完整性比对。
# -------------------------------------------------------------------- #
def regenerate_audit_policy() -> str:
    import json
    snapshot = {
        "edition": "sec",
        "rule_count": len(SEC_RULES),
        "categories": sorted({c for c, _, _ in SEC_RULES}),
        # 把规则正则源文本摘要纳入哈希范围（不暴露攻击载荷，仅 pattern 文本）
        "patterns": [
            {"category": c, "reason": r, "pattern": p.pattern}
            for c, r, p in SEC_RULES
        ],
    }
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2)


# -------------------------------------------------------------------- #
#  安全替代输出（理论思路模板，硬性规则 2 安全版"仅输出理论思路"）
# -------------------------------------------------------------------- #
SAFE_HINT_TEMPLATE = (
    "【DualGuard-Sec 拦截】请求的内容属于安全版风控拦截范围（{category}），"
    "无法提供可直接执行的攻击代码 / 渗透实操步骤。\n\n"
    "可讨论的理论思路：\n"
    "1. 该类漏洞的成因与影响面（CIA 三要素分析）；\n"
    "2. 通用的防御与缓解措施（最小权限、输入校验、补丁管理）；\n"
    "3. 在授权靶场环境下的合规验证方法（DVWA / HackTheBox 等）；\n"
    "4. 相关公开标准与参考（OWASP Top 10、MITRE ATT&CK）。\n\n"
    "如需在授权范围内进行安全测试，请联系持牌安全团队并在合规环境下进行。"
)


def make_safe_hint(category: str) -> str:
    return SAFE_HINT_TEMPLATE.format(category=category)
