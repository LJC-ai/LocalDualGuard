#!/bin/bash
# ==========================================================================
#  DualGuard 一键部署工具启动脚本（Linux / macOS）
#  执行：./deploy.sh
# ==========================================================================
set -e
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

echo "[INFO] 启动 DualGuard 一键部署工具 ..."
$PYTHON -m deploy_tool || {
    echo ""
    echo "[ERR] 启动失败。若提示缺少 tkinter："
    echo "      Ubuntu/Debian: sudo apt install python3-tk"
    echo "      CentOS/RHEL:   sudo yum install python3-tkinter"
    exit 1
}
