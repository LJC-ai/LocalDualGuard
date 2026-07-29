#!/bin/bash
# ==========================================================================
#  DualGuard-Sec Linux deb 包构建脚本
#
#  产物：dist/dualguard-sec_1.0.0_all.deb
#  安装：sudo dpkg -i dist/dualguard-sec_1.0.0_all.deb
#  卸载：sudo dpkg -r dualguard-sec
#
#  依赖（构建机）：dpkg-deb、fakeroot（可选，用于非 root 构建属主）
#  依赖（运行机，声明在 control 中）：python3、python3-cryptography
# ==========================================================================
set -euo pipefail

# --- 变量 ---
PKG_NAME="dualguard-sec"
VERSION="1.0.0"
EDITION="sec"
MODULE="dualguard_sec"

# 仓库根（脚本位于 packaging/linux/）
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

DIST_DIR="$REPO_ROOT/dist"
STAGE="$DIST_DIR/${PKG_NAME}_stage"

LINUX_DIR="$REPO_ROOT/packaging/linux"
WRAPPERS_DIR="$LINUX_DIR/wrappers"
DEBIAN_DIR="$LINUX_DIR/debian/$EDITION"

echo "[1/6] 清理旧产物..."
rm -rf "$STAGE" "$DIST_DIR/${PKG_NAME}_${VERSION}_all.deb"
mkdir -p "$DIST_DIR"

echo "[2/6] 组装目录树..."
# 应用代码
mkdir -p "$STAGE/opt/$PKG_NAME"
cp -r common "$STAGE/opt/$PKG_NAME/"
cp -r "$MODULE" "$STAGE/opt/$PKG_NAME/"
cp requirements.txt "$STAGE/opt/$PKG_NAME/"

# 命令行 wrapper
mkdir -p "$STAGE/usr/bin"
cp "$WRAPPERS_DIR/$PKG_NAME" "$STAGE/usr/bin/$PKG_NAME"

# systemd 服务单元
mkdir -p "$STAGE/lib/systemd/system"
cp "$LINUX_DIR/${PKG_NAME}.service" "$STAGE/lib/systemd/system/"

# DEBIAN 控制脚本
mkdir -p "$STAGE/DEBIAN"
cp "$DEBIAN_DIR/control" "$STAGE/DEBIAN/control"
cp "$DEBIAN_DIR/postinst" "$STAGE/DEBIAN/postinst"
cp "$DEBIAN_DIR/prerm"   "$STAGE/DEBIAN/prerm"
cp "$DEBIAN_DIR/postrm"  "$STAGE/DEBIAN/postrm"

echo "[3/6] 设置权限..."
# DEBIAN 脚本必须可执行
chmod 0755 "$STAGE/DEBIAN/postinst" \
           "$STAGE/DEBIAN/prerm" \
           "$STAGE/DEBIAN/postrm"
chmod 0644 "$STAGE/DEBIAN/control"

# wrapper 可执行
chmod 0755 "$STAGE/usr/bin/$PKG_NAME"

# 服务单元只读
chmod 0644 "$STAGE/lib/systemd/system/${PKG_NAME}.service"

# 应用代码：目录可读可进入，文件只读
find "$STAGE/opt/$PKG_NAME" -type d -exec chmod 0755 {} \;
find "$STAGE/opt/$PKG_NAME" -type f -exec chmod 0644 {} \;

# 整体属主设为 root:root（fakeroot 包装时生效；非 fakeroot 时由 dpkg 修正）
if command -v fakeroot >/dev/null 2>&1; then
    FAKEROOT="fakeroot"
else
    FAKEROOT=""
fi
chown -R root:root "$STAGE" 2>/dev/null || true

echo "[4/6] 构建数据目录占位（运行期由 postinst 创建，此处仅占位以保留权限约定）..."
mkdir -p "$STAGE/var/lib/dualguard/$EDITION/backup" \
         "$STAGE/var/lib/dualguard/$EDITION/logs"
# 占位目录运行期会被 postinst 覆盖属主
chmod 0750 "$STAGE/var/lib/dualguard/$EDITION"

echo "[5/6] dpkg-deb 构建..."
if [ -n "$FAKEROOT" ]; then
    $FAKEROOT dpkg-deb --build --root-owner-group "$STAGE" \
        "$DIST_DIR/${PKG_NAME}_${VERSION}_all.deb"
else
    dpkg-deb --build "$STAGE" "$DIST_DIR/${PKG_NAME}_${VERSION}_all.deb"
fi

echo "[6/6] 清理 staging..."
rm -rf "$STAGE"

echo ""
echo "[OK] 构建完成："
echo "    $DIST_DIR/${PKG_NAME}_${VERSION}_all.deb"
echo "    安装：sudo dpkg -i $DIST_DIR/${PKG_NAME}_${VERSION}_all.deb"
echo "    查询：dualguard-$EDITION --status"
