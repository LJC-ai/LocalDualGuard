"""DualGuard-Student 学生业务版主入口。

启动顺序与 DualGuard-Sec 完全对称：
1. 构造 AppPaths("student") / RiskConfig；
2. 注入审核策略重新生成器、前置审核 AI、二次复核器；
3. 启动健康检查（哈希 + 时间回拨 + 锁定）；
4. 进入对话循环：输入 → 前置审核 → 主模型 → 二次复核 → 输出。

主模型兜底为 KnowledgePointModel，输出"知识点 + 局部逻辑"风格的回复，
与硬性规则 2 学生版的"仅提供知识点、局部逻辑讲解"对齐。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _fix_sys_path() -> None:
    """修复 sys.path，确保打包态与开发态都能正确导入。"""
    if getattr(sys, 'frozen', False):
        return
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_fix_sys_path()


def _load_dotenv(edition: str) -> None:
    """从 ~/.dualguard-<edition>.env 加载 LLM 配置（部署工具生成）。"""
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


_load_dotenv("student")

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
    STUDENT_MAIN_MODEL_PROMPT,
)
from common.paths import AppPaths
from common.pre_audit import RuleBasedPreAudit, PreAuditAI, ACTION_BLOCK
from common.risk_engine import RiskEngine
from common.service import DualGuardService, query_once

from dualguard_student.reviewer import StudentReviewer
from dualguard_student.rules import StudentRuleset, regenerate_audit_policy


EDITION = "student"


# -------------------------------------------------------------------- #
#  主模型（兜底）
# -------------------------------------------------------------------- #
class KnowledgePointModel:
    """主模型兜底：默认以"知识点 / 局部逻辑"风格回复。"""

    def generate(self, user_input: str) -> str:
        if not user_input.strip():
            return "请输入你的学习问题（知识点或某道题的局部思路）。"
        return (
            f"【DualGuard-Student 知识点回复】\n"
            f"关于「{user_input[:60]}」：\n"
            f"1. 相关知识点：识别题目考查的概念与适用范围；\n"
            f"2. 解题切入点：从已知条件出发的局部逻辑；\n"
            f"3. 提示方向：自己补全剩下的步骤（不直接给整段答案）；\n"
            f"4. 自检：检查边界条件与常见错误。\n"
        )


# -------------------------------------------------------------------- #
#  对话循环
# -------------------------------------------------------------------- #
def run_repl(engine: RiskEngine) -> int:
    print("=" * 60)
    print(" DualGuard-Student 学生业务版  (输入 quit / exit 退出)")
    print("=" * 60)

    model = KnowledgePointModel()

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

        pre = engine.audit_input(line)
        if pre.action == "BLOCK":
            print(f"[DualGuard] 拦截：{pre.reason}")
            continue

        raw = model.generate(line)

        review = engine.audit_output(line, raw)
        if review.action == "BLOCK":
            print(f"[DualGuard] 二次复核拦截：{review.reason}")
            print(review.safe_output)
            continue

        print(review.safe_output or raw)


# -------------------------------------------------------------------- #
#  主入口
# -------------------------------------------------------------------- #
def _build_engine():
    """构造引擎并完成依赖注入。返回 (engine, model)。

    分层策略（与 sec 版对称，兼顾速度与质量）：
    - 前置审核：始终走规则（RuleBasedPreAudit），毫秒级响应
    - 主模型：若启用 LLM 则走 LLM（慢但质量高），否则走 KnowledgePointModel 兜底
    - 二次复核：始终走 StudentReviewer（规则），不可绕过

    这样只有主模型调用 LLM（~17s），避免前置审核再调 LLM 导致翻倍等待。
    """
    paths = AppPaths(EDITION)
    engine = RiskEngine(paths, DEFAULT_CONFIG)
    engine.set_audit_policy_regen(regenerate_audit_policy)
    engine.set_reviewer(StudentReviewer())

    # 前置审核始终走规则（快速），避免每次对话都调两次 LLM
    pre_audit = RuleBasedPreAudit(StudentRuleset())

    if llm_enabled():
        # 主模型走 LLM
        model = LlmMainModel(STUDENT_MAIN_MODEL_PROMPT)
        print("[DualGuard-Student] 已启用 LLM 主模型："
              f"{__import__('os').environ.get('DUALGUARD_LLM_BASE_URL')} / "
              f"model={__import__('os').environ.get('DUALGUARD_LLM_MODEL', 'gpt-4o-mini')}")
    else:
        model = KnowledgePointModel()
        print("[DualGuard-Student] 未启用 LLM，使用规则兜底。"
              "如需接入 AI：set DUALGUARD_LLM_BASE_URL / DUALGUARD_LLM_API_KEY")

    engine.set_pre_audit(pre_audit)
    engine._main_model = model
    return engine, model


def main() -> int:
    engine, model = _build_engine()

    state = engine.startup_health_check()

    if state in (LOCK_STATE_FROZEN_BY_TAMPER, LOCK_STATE_FROZEN_BY_ROLLBACK):
        print("[DualGuard] 服务已冻结，拒绝处理任何请求。")
        print(engine.status_report())
        return 2

    if state == LOCK_STATE_LOCKED_72H:
        print("[DualGuard] 对话处于 72 小时锁定中，请稍后再试。")
        print(engine.status_report())
        return 3

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

    # 默认：图形界面
    return run_gui(
        engine, model,
        title="DualGuard-Student 学生业务版",
        version_label="Student",
        hint_text="请输入学习问题（知识点、解题思路、局部逻辑等）",
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
