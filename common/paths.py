"""统一的路径管理。

所有业务版本共用同一套目录约定：
- data_dir: 运行期数据目录（违规记录、备份、哈希文件）
- backup_dir: 审核文件备份（被篡改时用于自动恢复）
- log_dir: 运行日志

Windows 默认: %PROGRAMDATA%\\DualGuard\\<edition>
Linux 默认: /var/lib/dualguard-<edition>

允许通过环境变量 DUALGUARD_DATA_ROOT 覆盖根目录，便于测试与打包。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_data_root() -> Path:
    """返回平台相关的默认数据根目录。"""
    env_override = os.environ.get("DUALGUARD_DATA_ROOT")
    if env_override:
        return Path(env_override)

    if sys.platform.startswith("win"):
        # %PROGRAMDATA% 一般为 C:\ProgramData
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "DualGuard"
    # Linux / macOS
    return Path("/var/lib/dualguard")


class AppPaths:
    """单实例路径对象，由各业务版本在启动时构造。

    edition: "sec" 或 "student"，用于隔离两套版本的数据目录，
    避免互相干扰、互相污染违规计数。
    """

    def __init__(self, edition: str) -> None:
        assert edition in ("sec", "student"), f"非法版本号: {edition}"
        self.edition = edition
        root = _default_data_root() / edition
        self.data_dir = root
        self.backup_dir = root / "backup"
        self.log_dir = root / "logs"

        # 违规记录数据库（AES 加密的 JSON Lines）
        self.violations_db = self.data_dir / "violations.enc"
        # 审核文件本体（用于哈希校验的关键审核策略文件）
        self.audit_file = self.data_dir / "audit_policy.json"
        self.audit_backup = self.backup_dir / "audit_policy.json.bak"
        # 哈希清单文件（保存审核文件本身的预期 SHA256）
        self.audit_hash_file = self.data_dir / "audit_policy.sha256"
        # 主密钥文件（仅存 KEK，实际数据密钥派生自此）
        self.kek_file = self.data_dir / "kek.bin"
        # 单调计数器文件（防系统时间回拨绕过的关键证据）
        self.monotonic_file = self.data_dir / "monotonic.state"
        # 锁定状态文件
        self.lock_file = self.data_dir / "lock.state"

    def ensure_dirs(self) -> None:
        """启动时调用，确保所有目录存在。"""
        for d in (self.data_dir, self.backup_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)
