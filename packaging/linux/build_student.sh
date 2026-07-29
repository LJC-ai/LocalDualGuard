#!/bin/bash
# ==========================================================================
#  DualGuard-Student Linux deb 包构建脚本
#  与 build_sec.sh 结构对称，仅包名 / 模块 / service 不同。
#
#  产物：dist/dualguard-student_1.0.0_all.deb
#  安装：sudo dpkg -i dist/dualguard-student_1.0.0_all.deb
# ==========================================================================
set -euo pipefail

PKG_NAME="dualguard-student"
VERSION="1.0.0"
EDITION="student"
MODULE="dualguard_student"

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
mkdir -p "$STAGE/opt/$PKG_NAME"
cp -r common "$STAGE/opt/$PKG_NAME/"
cp -r "$MODULE" "$STAGE/opt/$PKG_NAME/"
cp requirements.txt "$STAGE/opt/$PKG_NAME/"

mkdir -p "$STAGE/usr/bin"
cp "$WRAPPERS_DIR/$PKG_NAME" "$STAGE/usr/bin/$PKG_NAME"

mkdir -p "$STAGE/lib/systemd/system"
cp "$LINUX_DIR/${PKG_NAME}.service" "$STAGE/lib/systemd/system/"

mkdir -p "$STAGE/DEBIAN"
cp "$DEBIAN_DIR/control" "$STAGE/DEBIAN/control"
cp "$DEBIAN_DIR/postinst" "$STAGE/DEBIAN/postinst"
cp "$DEBIAN_DIR/prerm"   "$STAGE/DEBIAN/prerm"
cp "$DEBIAN_DIR/postrm"  "$STAGE/DEBIAN/postrm"

echo "[3/6] 设置权限..."
chmod 0755 "$STAGE/DEBIAN/postinst" \
           "$STAGE/DEBIAN/prerm" \
           "$STAGE/DEBIAN/postrm"
chmod 0644 "$STAGE/DEBIAN/control"

chmod 0755 "$STAGE/usr/bin/$PKG_NAME"
chmod 0644 "$STAGE/lib/systemd/system/${PKG_NAME}.service"

find "$STAGE/opt/$PKG_NAME" -type d -exec chmod 0755 {} \;
find "$STAGE/opt/$PKG_NAME" -type f -exec chmod 0644 {} \;

if command -v fakeroot >/dev/null 2>&1; then
    FAKEROOT="fakeroot"
else
    FAKEROOT=""
fi
chown -R root:root "$STAGE" 2>/dev/null || true

echo "[4/6] 构建数据目录占位..."
mkdir -p "$STAGE/var/lib/dualguard/$EDITION/backup" \
         "$STAGE/var/lib/dualguard/$EDITION/logs"
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
