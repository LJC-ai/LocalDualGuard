#!/bin/bash
# ==========================================================================
#  DualGuard-Student 开发期启动脚本（Linux / macOS）
#  与 start_sec.sh 对称，启动学生业务版。
# ==========================================================================
set -euo pipefail

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

if ! "$PYTHON" -c "import cryptography" 2>/dev/null; then
    echo "[INFO] 安装运行依赖 cryptography ..."
    "$PYTHON" -m pip install -r requirements.txt
fi

echo "[INFO] 启动 DualGuard-Student ..."
exec "$PYTHON" -m dualguard_student.main "$@"
