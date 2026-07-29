"""本地常驻服务（硬性规则 5② Linux 后台常驻服务的运行期实现）。

提供：
- 一个极简的本地 IPC 服务端：
  * Linux: Unix domain socket (/run/dualguard-<edition>/sock 或 /tmp 下)
  * Windows: 命名管道 (\\\\.\\pipe\\dualguard_<edition>)
- 协议：客户端发一行 UTF-8 文本（查询），服务端返回一行 JSON：
    {"action": "ALLOW|BLOCK|LOCKED", "text": "..."}
  特殊指令：
    "PING"       -> {"action":"PONG"}
    "STATUS"     -> {"action":"STATUS","text":"<status_report>"}
    "SHUTDOWN"   -> 关闭服务（仅用于调试）
- RiskEngine 的双层审核链路完整复用，不存在绕过路径。

systemd 服务调用 `python -m dualguard_sec.main --service` 启动本服务，
用户/前端通过 `python -m dualguard_sec.main --query "..."` 发起查询。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Optional

from .paths import AppPaths


# -------------------------------------------------------------------- #
#  IPC 端点路径解析
# -------------------------------------------------------------------- #
def _socket_path(paths: AppPaths) -> Path:
    """返回 Unix socket 路径。优先 /run，回退 /tmp。"""
    if os.name == "posix":
        # /run/dualguard-<edition>（需由 systemd / 打包脚本创建并 chown）
        run_dir = Path("/run") / f"dualguard-{paths.edition}"
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            run_dir = Path("/tmp") / f"dualguard-{paths.edition}"
            run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir / "sock"
    # Windows 命名管道名（不含路径分隔）
    return Path(f"\\\\.\\pipe\\dualguard_{paths.edition}")


# -------------------------------------------------------------------- #
#  服务端
# -------------------------------------------------------------------- #
class DualGuardService:
    """本地常驻服务。监听 IPC 端点，对每个查询执行双层审核。"""

    def __init__(self, engine, paths: AppPaths) -> None:
        self.engine = engine
        self.paths = paths
        self._stop = threading.Event()
        self._server_sock: Optional[socket.socket] = None

    # ----------------------- 启动 ----------------------- #
    def serve_forever(self) -> int:
        if os.name == "posix":
            return self._serve_unix()
        return self._serve_win_pipe()

    # ----------------------- Unix socket ----------------------- #
    def _serve_unix(self) -> int:
        sock_path = _socket_path(self.paths)
        if sock_path.exists():
            sock_path.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        try:
            os.chmod(sock_path, 0o660)
        except OSError:
            pass
        srv.listen(8)
        srv.settimeout(1.0)
        self._server_sock = srv
        print(f"[DualGuardService] listening on {sock_path}", flush=True)

        while not self._stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle_conn(conn)
            finally:
                conn.close()
        srv.close()
        if sock_path.exists():
            sock_path.unlink()
        return 0

    # ----------------------- Windows named pipe ----------------------- #
    def _serve_win_pipe(self) -> int:
        # 简化实现：Windows 桌面版主要走交互式 REPL，
        # 这里提供一个最小可用的 TCP 本地回环作为后备（避免依赖 win32pipe）。
        port = 47000 + (1 if self.paths.edition == "student" else 0)
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(8)
        srv.settimeout(1.0)
        self._server_sock = srv
        print(f"[DualGuardService] listening on 127.0.0.1:{port}", flush=True)

        while not self._stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle_conn(conn)
            finally:
                conn.close()
        srv.close()
        return 0

    # ----------------------- 单连接处理 ----------------------- #
    def _handle_conn(self, conn: socket.socket) -> None:
        conn.settimeout(self.engine.config.pre_audit_timeout_sec
                        + self.engine.config.main_review_timeout_sec + 2)
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
            if len(buf) > 65536:
                self._send(conn, {"action": "BLOCK",
                                   "text": "查询过长，已拒绝。"})
                return
        line = buf.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
        resp = self._dispatch(line)
        self._send(conn, resp)

    def _dispatch(self, line: str) -> dict:
        if line == "PING":
            return {"action": "PONG"}
        if line == "STATUS":
            return {"action": "STATUS", "text": self.engine.status_report()}
        if line == "SHUTDOWN":
            self._stop.set()
            return {"action": "OK", "text": "shutting down"}

        # 锁定/冻结时直接拒绝
        if not self.engine.is_service_available():
            return {"action": "LOCKED",
                    "text": f"服务不可用：{self.engine.check_lock_status()}"}

        # 双层审核：① 前置审核
        pre = self.engine.audit_input(line)
        if pre.action == "BLOCK":
            return {"action": "BLOCK", "text": pre.reason,
                    "category": pre.category}

        # ② 主模型（引擎未注入主模型时使用占位回复）
        main_model = getattr(self.engine, "_main_model", None)
        raw = main_model.generate(line) if main_model else f"(echo) {line}"

        # ③ 二次复核
        review = self.engine.audit_output(line, raw)
        if review.action == "BLOCK":
            return {"action": "BLOCK", "text": review.safe_output,
                    "category": review.category}
        return {"action": "ALLOW", "text": review.safe_output or raw}

    @staticmethod
    def _send(conn: socket.socket, obj: dict) -> None:
        conn.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    def stop(self) -> None:
        self._stop.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass


# -------------------------------------------------------------------- #
#  客户端：单次查询
# -------------------------------------------------------------------- #
def query_once(paths: AppPaths, text: str, timeout: float = 20.0) -> dict:
    """向本地常驻服务发一次查询，返回解析后的 JSON。"""
    if os.name == "posix":
        sock_path = _socket_path(paths)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(str(sock_path))
    else:
        port = 47000 + (1 if paths.edition == "student" else 0)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", port))
    try:
        s.sendall((text + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n", 1)[0].decode("utf-8", errors="replace")
        return json.loads(line)
    finally:
        s.close()
