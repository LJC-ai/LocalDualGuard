"""LLM 适配器（OpenAI 兼容接口）。

设计目标：用最简方式把真实 AI 接入 DualGuard 的两个环节，
不增加任何依赖（仅用标准库 urllib），不强制配置。

============================================================
使用方法（"不要太麻烦"版）
============================================================

设置两个环境变量即可启用：

    # Linux / macOS
    export DUALGUARD_LLM_BASE_URL="https://api.deepseek.com/v1"
    export DUALGUARD_LLM_API_KEY="sk-xxxxxxxx"
    # 可选：模型名（默认 gpt-4o-mini）
    export DUALGUARD_LLM_MODEL="deepseek-chat"

    # Windows PowerShell
    $env:DUALGUARD_LLM_BASE_URL="https://api.deepseek.com/v1"
    $env:DUALGUARD_LLM_API_KEY="sk-xxxxxxxx"
    $env:DUALGUARD_LLM_MODEL="deepseek-chat"

不设置 → main.py 自动回退到 RuleBasedPreAudit / EchoModel（兜底），
不影响现有功能，零成本。

============================================================
兼容的 AI 服务（任选其一，填对应 BASE_URL）
============================================================
- OpenAI:        https://api.openai.com/v1
- DeepSeek:      https://api.deepseek.com/v1
- 通义千问:       https://dashscope.aliyuncs.com/compatible-mode/v1
- Moonshot:      https://api.moonshot.cn/v1
- 智谱 GLM:      https://open.bigmodel.cn/api/paas/v4
- 本地 Ollama:    http://localhost:11434/v1   （key 任意）
- 本地 vLLM:     http://localhost:8000/v1     （key 任意）

============================================================
接入的两个环节（main.py 自动调用）
============================================================
1. 前置审核 AI  → LlmPreAudit
   让 LLM 判断"用户输入是否属于本版本拦截范围"，
   返回 JSON {"block": true/false, "category": "...", "reason": "..."}
   LLM 判定结果仍走 RiskEngine 落库 + 计数 + 弹窗，无法绕过。

2. 主模型生成   → LlmMainModel
   让 LLM 生成回复（带版本专属 system prompt，
   安全版/学生版分别约束为"理论思路"/"知识点讲解"）。
   主模型输出仍然必须经过 SecReviewer/StudentReviewer 二次复核，
   不存在绕过路径。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from .pre_audit import PreAuditAI, PreAuditResult, ACTION_ALLOW, ACTION_BLOCK
from .risk_engine import ReviewResult


# -------------------------------------------------------------------- #
#  配置读取
# -------------------------------------------------------------------- #
def llm_enabled() -> bool:
    """是否启用了 LLM 接入。"""
    return bool(os.environ.get("DUALGUARD_LLM_BASE_URL"))


def _base_url() -> str:
    return os.environ.get("DUALGUARD_LLM_BASE_URL", "").rstrip("/")


def _api_key() -> str:
    return os.environ.get("DUALGUARD_LLM_API_KEY", "")


def _model(default: str = "gpt-4o-mini") -> str:
    return os.environ.get("DUALGUARD_LLM_MODEL", default)


# -------------------------------------------------------------------- #
#  最小 OpenAI 兼容客户端
# -------------------------------------------------------------------- #
class OpenAICompatibleClient:
    """OpenAI 兼容客户端，支持 chat/completions 和 completions 两种模式。"""

    def __init__(self, timeout: float = 120.0) -> None:
        self.timeout = timeout

    def chat(self, messages: list, model: Optional[str] = None,
             temperature: float = 0.2, max_tokens: int = 1024) -> str:
        """调用 LLM，优先 chat/completions，失败则降级到 completions。"""
        model_name = model or _model()
        headers = {"Content-Type": "application/json"}
        api_key = _api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            return self._chat_completions(messages, model_name, temperature, max_tokens, headers)
        except Exception as e:
            try:
                return self._completions(messages, model_name, temperature, max_tokens, headers)
            except Exception as e2:
                raise RuntimeError(f"LLM 调用失败: {e}")

    def _chat_completions(self, messages: list, model: str, temperature: float,
                          max_tokens: int, headers: dict) -> str:
        """调用 /chat/completions（标准 OpenAI 格式）。"""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        url = f"{_base_url()}/chat/completions"
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
        msg = data["choices"][0]["message"]
        content = msg.get("content", "").strip()
        if not content:
            content = msg.get("reasoning_content", "").strip()
        return content

    def _completions(self, messages: list, model: str, temperature: float,
                     max_tokens: int, headers: dict) -> str:
        """调用 /completions（LM Studio 等仅支持补全的服务）。"""
        prompt = "\n\n".join(f"{m['role']}: {m['content']}" for m in messages) + "\n\nassistant:"
        payload = {
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stop": ["\n\nuser:", "\n\nassistant:"],
        }
        url = f"{_base_url()}/completions"
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
        return data["choices"][0]["text"].strip()


# ==================================================================== #
#  ① 前置审核 AI 的 LLM 实现
# ==================================================================== #
class LlmPreAudit(PreAuditAI):
    """用 LLM 做前置审核判定。

    要求 LLM 严格返回 JSON：
        {"block": true,  "category": "...", "reason": "..."}
        {"block": false}

    输入拦截范围由 system_prompt 描述（业务版本注入）。
    若 LLM 解析失败或超时，安全失败 → BLOCK（防误放行）。
    """

    name = "llm_pre_audit"

    def __init__(self, system_prompt: str, client: Optional[OpenAICompatibleClient] = None) -> None:
        self.system_prompt = system_prompt
        self.client = client or OpenAICompatibleClient(timeout=60.0)

    def audit(self, user_input: str) -> PreAuditResult:
        if not user_input.strip():
            return PreAuditResult(action=ACTION_ALLOW)
        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_input},
                ],
                temperature=0.0,
                max_tokens=256,
            )
        except Exception as e:
            # 安全失败：审核异常时拒绝放行（与 common.pre_audit 约定一致）
            return PreAuditResult(
                action=ACTION_BLOCK,
                category="PRE_AUDIT_ERROR",
                reason=f"前置审核 LLM 异常: {e}",
            )
        return self._parse(raw, user_input)

    def _parse(self, raw: str, user_input: str) -> PreAuditResult:
        """容错解析 LLM 返回的 JSON。"""
        # 兼容模型把 JSON 包在 ```json ... ``` 中的情况
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 解析失败 → 安全失败
            return PreAuditResult(
                action=ACTION_BLOCK,
                category="PRE_AUDIT_PARSE_FAIL",
                reason=f"前置审核 LLM 返回非 JSON: {raw[:80]}",
            )
        if not data.get("block"):
            return PreAuditResult(action=ACTION_ALLOW)
        return PreAuditResult(
            action=ACTION_BLOCK,
            category=str(data.get("category", "LLM_BLOCK")),
            reason=str(data.get("reason", "前置审核 LLM 拦截")),
            matched_snippets=[user_input[:100]],
        )


# ==================================================================== #
#  ② 主模型生成的 LLM 实现
# ==================================================================== #
class LlmMainModel:
    """用 LLM 生成主模型回复。

    system_prompt 由业务版本注入（sec 版约束为"仅输出理论思路"，
    student 版约束为"仅提供知识点、局部逻辑讲解"）。
    生成的输出仍然必须经过 Reviewer 二次复核，不可绕过。
    """

    def __init__(self, system_prompt: str, client: Optional[OpenAICompatibleClient] = None) -> None:
        self.system_prompt = system_prompt
        self.client = client or OpenAICompatibleClient(timeout=60.0)

    def generate(self, user_input: str) -> str:
        if not user_input.strip():
            return "请输入您的问题。"
        try:
            return self.client.chat(
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_input},
                ],
                temperature=0.3,
                max_tokens=1024,
            )
        except Exception as e:
            # 主模型失败时回退到兜底回复（不抛错，保持服务可用）
            return f"（主模型暂不可用，回退兜底）关于「{user_input[:40]}」：请稍后重试。原因: {e}"


# ==================================================================== #
#  业务版本注入用的 system prompts
#  （业务规则 2 的强约束：安全版仅输出理论思路，学生版仅提供知识点/局部逻辑）
# ==================================================================== #
SEC_PRE_AUDIT_PROMPT = """你是 DualGuard-Sec 安全业务版的前置审核 AI。
任务：判断用户输入是否属于安全版拦截范围。
拦截范围（block=true）：
1. 请求生成漏洞攻击脚本 / 武器化 payload（metasploit、shellcode、reverse shell 等）
2. 请求生成针对 Winlink 软件的利用代码
3. 请求针对真实公共目标（github.com、政府、银行等）的渗透实操步骤
不拦截（block=false）：理论问题、防御方法、靶场练习、CTF 思路。
严格只返回 JSON，不要多余文字：
  拦截: {"block": true, "category": "EXPLOIT_SCRIPT|WINLINK_EXPLOIT|PENETRATION_LIVE", "reason": "简短原因"}
  放行: {"block": false}"""

SEC_MAIN_MODEL_PROMPT = """你是 DualGuard-Sec 安全业务版的主模型。
硬性约束：只输出理论思路、成因分析、防御方法、合规验证方法；
绝不输出可直接执行的攻击代码 / 漏洞利用 EXP / 反弹 shell 载荷。
回复保持简洁，分点说明。若用户请求越界，直接拒绝并改为输出理论层面讲解。"""

STUDENT_PRE_AUDIT_PROMPT = """你是 DualGuard-Student 学生业务版的前置审核 AI。
任务：判断用户输入是否属于学生版拦截范围。
拦截范围（block=true）：
1. 请求生成可直接提交的完整作业答案
2. 请求整套 Scratch 图形化积木搭建流程（每块积木逐块给出 + 完整运行步骤）
不拦截（block=false）：知识点讲解、局部逻辑、解题思路、单块积木说明。
严格只返回 JSON，不要多余文字：
  拦截: {"block": true, "category": "FULL_ANSWER|SCRATCH_FULL_TUTORIAL", "reason": "简短原因"}
  放行: {"block": false}"""

STUDENT_MAIN_MODEL_PROMPT = """你是 DualGuard-Student 学生业务版的主模型。
硬性约束：仅提供知识点、解题思路、局部逻辑讲解；
绝不输出可直接照搬的完整答案 / 整套 Scratch 搭建流程。
引导学生自主完成，遇到具体卡点再细化讲解。回复温和、引导向、分点说明。"""
