#!/bin/bash
# ==========================================================================
#  DualGuard-Sec 开发期启动脚本（Linux / macOS）
#  - 自动检查并安装 cryptography 依赖
#  - 启动安全业务版（默认交互式 REPL，可附加 --service / --status / --query）
#  打包后由 deb 包安装的 /usr/bin/dualguard-sec 直接调用，本脚本主要用于开发/免安装运行。
# ==========================================================================
set -euo pipefail

cd "$(dirname "$0")"

# 优先使用虚拟环境
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

# 依赖检查
if ! "$PYTHON" -c "import cryptography" 2>/dev/null; then
    echo "[INFO] 安装运行依赖 cryptography ..."
    "$PYTHON" -m pip install -r requirements.txt
fi

echo "[INFO] 启动 DualGuard-Sec ..."
exec "$PYTHON" -m dualguard_sec.main "$@"
