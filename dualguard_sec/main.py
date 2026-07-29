"""DualGuard-Sec 安全业务版主入口。

启动顺序（严格遵守硬性规则 3、4）：
1. 构造 AppPaths / RiskConfig；
2. 构造 RiskEngine 并注入：
     - 审核策略重新生成器（regenerate_audit_policy）
     - 前置审核 AI（RuleBasedPreAudit + SecRuleset）
     - 二次复核器（SecReviewer）
3. 启动健康检查：哈希校验 + 时间回拨检测 + 锁定状态；
4. 若被冻结/锁定：拒绝服务，仅打印状态；
5. 否则进入对话循环：输入 → 前置审核 → 主模型 → 二次复核 → 输出。

主模型采用本地的 EchoModel 兜底（不调用真实 LLM API），
生产中可替换为真实的合规 LLM 客户端，但 RiskEngine 的双层审核链路不变。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _fix_sys_path() -> None:
    """修复 sys.path，确保打包态与开发态都能正确导入。

    开发态：__file__ 指向源码目录的 main.py，往上两级是仓库根。
    打包态（PyInstaller onedir）：__file__ 指向 _internal/dualguard_sec/main.pyc，
    此时 sys.path 已由 PyInstaller 自动设置，无需额外调整。
    但需避免把打包后的目录错误加入 sys.path（防止导入偏移）。
    """
    if getattr(sys, 'frozen', False):
        return
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_fix_sys_path()


def _load_dotenv(edition: str) -> None:
    """从 ~/.dualguard-<edition>.env 加载 LLM 配置（部署工具生成）。

    已存在的环境变量优先（不覆盖），便于 CI / systemd Environment 覆盖。
    """
    env_file = Path.home() / f".dualguard-{edition}.env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv("sec")

from common.audit_storage import (
    LOCK_STATE_OK,
    LOCK_STATE_LOCKED_72H,
    LOCK_STATE_FROZEN_BY_ROLLBACK,
    LOCK_STATE_FROZEN_BY_TAMPER,
)
from common.config import DEFAULT_CONFIG
from common.gui import run_gui
from common.llm_adapter import (
    llm_enabled,
    LlmMainModel,
    SEC_MAIN_MODEL_PROMPT,
)
from common.paths import AppPaths
from common.pre_audit import RuleBasedPreAudit, PreAuditAI, ACTION_BLOCK, ACTION_ALLOW
from common.risk_engine import RiskEngine, popup_warn
from common.service import DualGuardService, query_once

from dualguard_sec.reviewer import SecReviewer
from dualguard_sec.rules import SecRuleset, regenerate_audit_policy


EDITION = "sec"


# -------------------------------------------------------------------- #
#  主模型（兜底实现）
# -------------------------------------------------------------------- #
class EchoModel:
    """主模型兜底：把用户输入包装成"理论讲解"回复。

    生产中替换为真实 LLM 客户端即可。注意：即使主模型"想"输出攻击代码，
    二次复核器也会拦截，引擎会落违规记录。
    """

    def generate(self, user_input: str) -> str:
        if not user_input.strip():
            return "请输入您的安全理论学习问题。"
        return (
            f"【DualGuard-Sec 理论回复】\n"
            f"已收到您关于「{user_input[:60]}」的提问。\n"
            f"下面从理论层面作答（不包含可执行攻击代码）：\n"
            f"1. 概念定义：识别该问题涉及的安全域与威胁模型；\n"
            f"2. 成因分析：从 CIA 三要素拆解风险来源；\n"
            f"3. 防御建议：最小权限、输入校验、补丁、监控；\n"
            f"4. 合规验证：建议在授权靶场（DVWA / HackTheBox）下验证。\n"
        )


# -------------------------------------------------------------------- #
#  对话循环
# -------------------------------------------------------------------- #
def run_repl(engine: RiskEngine) -> int:
    """交互式对话循环。返回退出码。"""
    print("=" * 60)
    print(" DualGuard-Sec 安全业务版  (输入 quit / exit 退出)")
    print("=" * 60)

    model = EchoModel()

    while True:
        try:
            line = input("\n[user] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return 0
        if not line:
            continue
        if line.lower() in ("quit", "exit", ":q"):
            print("再见。")
            return 0

        # ① 前置审核
        pre = engine.audit_input(line)
        if pre.action == ACTION_BLOCK:
            print(f"[DualGuard] 拦截：{pre.reason}")
            continue

        # ② 主模型生成
        raw = model.generate(line)

        # ③ 二次复核
        review = engine.audit_output(line, raw)
        if review.action == ACTION_BLOCK:
            print(f"[DualGuard] 二次复核拦截：{review.reason}")
            print(review.safe_output)
            continue

        print(review.safe_output or raw)


# -------------------------------------------------------------------- #
#  主入口
# -------------------------------------------------------------------- #
def _build_engine():
    """构造引擎并完成依赖注入。返回 (engine, model)。

    分层策略（兼顾速度与质量）：
    - 前置审核：始终走规则（RuleBasedPreAudit），毫秒级响应
    - 主模型：若启用 LLM 则走 LLM（慢但质量高），否则走 EchoModel 兜底
    - 二次复核：始终走 SecReviewer（规则），不可绕过

    这样只有主模型调用 LLM（~17s），避免前置审核再调 LLM 导致翻倍等待。
    """
    paths = AppPaths(EDITION)
    engine = RiskEngine(paths, DEFAULT_CONFIG)
    engine.set_audit_policy_regen(regenerate_audit_policy)
    engine.set_reviewer(SecReviewer())

    # 前置审核始终走规则（快速），避免每次对话都调两次 LLM
    pre_audit = RuleBasedPreAudit(SecRuleset())

    if llm_enabled():
        # 主模型走 LLM
        model = LlmMainModel(SEC_MAIN_MODEL_PROMPT)
        print("[DualGuard-Sec] 已启用 LLM 主模型："
              f"{__import__('os').environ.get('DUALGUARD_LLM_BASE_URL')} / "
              f"model={__import__('os').environ.get('DUALGUARD_LLM_MODEL', 'gpt-4o-mini')}")
    else:
        model = EchoModel()
        print("[DualGuard-Sec] 未启用 LLM，使用规则兜底。"
              "如需接入 AI：set DUALGUARD_LLM_BASE_URL / DUALGUARD_LLM_API_KEY")

    engine.set_pre_audit(pre_audit)
    engine._main_model = model
    return engine, model


def main() -> int:
    engine, model = _build_engine()

    # 启动健康检查（哈希 + 时间回拨 + 锁定）
    state = engine.startup_health_check()

    if state in (LOCK_STATE_FROZEN_BY_TAMPER, LOCK_STATE_FROZEN_BY_ROLLBACK):
        print("[DualGuard] 服务已冻结，拒绝处理任何请求。")
        print(engine.status_report())
        return 2

    if state == LOCK_STATE_LOCKED_72H:
        print("[DualGuard] 对话处于 72 小时锁定中，请稍后再试。")
        print(engine.status_report())
        return 3

    # --status：仅打印状态后退出（运维 / 打包自检用）
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        print(engine.status_report())
        return 0

    # --query TEXT：向本地常驻服务发起一次查询
    if len(sys.argv) > 2 and sys.argv[1] == "--query":
        resp = query_once(engine.paths, sys.argv[2])
        print(resp.get("text", resp))
        return 0 if resp.get("action") != "BLOCK" else 1

    # --service：以常驻服务模式运行（systemd 使用）
    if len(sys.argv) > 1 and sys.argv[1] == "--service":
        svc = DualGuardService(engine, engine.paths)
        try:
            return svc.serve_forever()
        except KeyboardInterrupt:
            svc.stop()
            return 0

    # --repl：强制命令行模式（默认走 GUI）
    if len(sys.argv) > 1 and sys.argv[1] == "--repl":
        return run_repl(engine)

    # 默认：图形界面（双击 exe / 启动脚本时弹出窗口）
    return run_gui(
        engine, model,
        title="DualGuard-Sec 安全业务版",
        version_label="Sec",
        hint_text="请输入安全理论学习问题（漏洞原理、防御方法、靶场思路等）",
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        # console=False 模式下异常不可见，写到崩溃日志便于排查
        import traceback
        log_path = Path.home() / f".dualguard-{EDITION}-crash.log"
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise SystemExit(1)
