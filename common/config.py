"""配置加载。

集中管理风控阈值、密钥派生参数等。所有可调参数集中在 Config dataclass，
业务版本只读不写，避免散落的魔法数字。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class RiskConfig:
    """统一风控配置。"""

    # 单次违规即弹窗警告（业务规则强制要求）
    warn_on_single_violation: bool = True
    # 累计 3 次锁定对话 72 小时
    lock_threshold: int = 3
    lock_hours: int = 72

    # AES 主密钥派生参数
    kdk_salt_len: int = 16      # 主密钥派生盐
    kdk_iterations: int = 200_000  # PBKDF2 迭代次数，按 2025 后安全基线

    # 防系统时间回拨的容忍窗口（秒）。若当前时间比上次记录早超过该值，
    # 视为时间被回拨，触发冻结。
    clock_rollback_tolerance_sec: int = 60

    # 前置审核 AI 与主模型之间的最大等待（秒）
    pre_audit_timeout_sec: int = 8
    main_review_timeout_sec: int = 15

    # 各业务版本通过 injection 注入的关键词类别
    # （此处仅占位，实际由业务版 rules.py 提供）
    blocked_categories: tuple = ()

    # 允许输出理论思路 / 知识点时的最大提示深度（防止变相泄露）
    safe_hint_max_lines: int = 12


@dataclass(frozen=True)
class Paths:
    """供依赖注入使用的路径占位。"""

    edition: str = "common"


# 默认配置实例，业务版本可直接复用或在其上派生
DEFAULT_CONFIG = RiskConfig()
