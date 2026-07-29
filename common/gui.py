"""DualGuard 通用图形界面（两套版本共用）。

设计目标：
- 替代原命令行 REPL，双击 exe 直接弹出图形窗口
- 完整复用 RiskEngine 双层审核链路，不可绕过
- 风控状态实时显示（违规次数 / 锁定状态）
- 拦截时弹窗警告 + 日志区红色显示
- 支持 LLM 接入状态显示

入口：
    业务版本 main.py 调用 run_gui(engine, model, title, version_label)
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from typing import Optional

from .audit_storage import (
    LOCK_STATE_OK,
    LOCK_STATE_LOCKED_72H,
    LOCK_STATE_FROZEN_BY_ROLLBACK,
    LOCK_STATE_FROZEN_BY_TAMPER,
)
from .pre_audit import ACTION_BLOCK, ACTION_ALLOW
from .risk_engine import popup_warn


def _has_tkinter() -> bool:
    """检测 tkinter 是否可用（部分精简 Linux 无此模块）。"""
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


def run_gui(engine, model, title: str, version_label: str,
            hint_text: str = "") -> int:
    """启动图形界面。

    参数：
        engine: RiskEngine 实例（已完成启动健康检查）
        model: 主模型实例（EchoModel / KnowledgePointModel / LlmMainModel）
        title: 窗口标题
        version_label: 版本标识（如 "安全业务版" / "学生业务版"）
        hint_text: 输入框上方的提示文案

    返回退出码。
    """
    if not _has_tkinter():
        print("[ERR] 系统未安装 tkinter，无法启动 GUI。")
        if sys.platform.startswith("linux"):
            print("      Ubuntu/Debian: sudo apt install python3-tk")
            print("      CentOS/RHEL:   sudo yum install python3-tkinter")
        print("      可改用命令行模式：python -m dualguard_sec.main --repl")
        return 1

    # 延迟导入 tkinter 并注入到模块全局（避免无 tkinter 环境 import 报错）
    global tk, ttk, messagebox
    import tkinter as tk
    from tkinter import messagebox, ttk

    app = DualGuardApp(engine, model, title, version_label, hint_text)
    app.root.mainloop()
    return 0


# -------------------------------------------------------------------- #
#  主窗口
# -------------------------------------------------------------------- #
class DualGuardApp:
    """DualGuard 主窗口（对话式 GUI）。"""

    def __init__(self, engine, model, title: str,
                 version_label: str, hint_text: str = "") -> None:
        self.engine = engine
        self.model = model
        self.version_label = version_label
        self.hint_text = hint_text

        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("900x680")
        self.root.minsize(800, 600)

        # 高 DPI 适配（Windows）
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # 隐藏控制台窗口（双击 exe 时不显示黑框）
        # 仅在 Windows 且非冻结调试态生效
        if sys.platform.startswith("win"):
            try:
                import ctypes
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
            except Exception:
                pass

        # 关闭窗口时清理
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 审核状态
        self._is_processing = False

        self._build_ui()
        self._refresh_status()
        self._append_log(f"[系统] DualGuard-{version_label} 已就绪", "system")

        # 启动期锁定检查
        state = engine.check_lock_status()
        if state in (LOCK_STATE_FROZEN_BY_TAMPER, LOCK_STATE_FROZEN_BY_ROLLBACK):
            self._append_log(
                "[安全告警] 检测到审核文件被篡改或系统时间回拨，服务已冻结。",
                "block")
            messagebox.showerror("DualGuard 安全告警",
                "检测到审核文件被篡改或系统时间回拨。\n对话已被冻结，请联系管理员。")
            self._lock_ui()
        elif state == LOCK_STATE_LOCKED_72H:
            self._append_log("[锁定] 对话处于 72 小时锁定中。", "block")
            messagebox.showwarning("DualGuard 锁定",
                "累计违规已达阈值，对话已锁定 72 小时。")
            self._lock_ui()

    # ============================ UI ============================ #
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # --- 顶部状态栏 ---
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        self.lbl_title = ttk.Label(
            top,
            text=f"DualGuard-{self.version_label}",
            font=("Microsoft YaHei", 14, "bold"))
        self.lbl_title.pack(side="left")

        self.lbl_status = ttk.Label(
            top, text="状态：就绪", foreground="#0a7",
            font=("Microsoft YaHei", 9))
        self.lbl_status.pack(side="right")

        # --- 状态信息条 ---
        info = ttk.Frame(self.root)
        info.pack(fill="x", **pad)
        self.lbl_violations = ttk.Label(
            info, text="违规次数：0 / 3", font=("Microsoft YaHei", 9))
        self.lbl_violations.pack(side="left")
        self.lbl_llm = ttk.Label(
            info, text="LLM：未启用（规则兜底）",
            foreground="#666", font=("Microsoft YaHei", 9))
        self.lbl_llm.pack(side="right")

        # --- 对话显示区 ---
        conv_frame = ttk.LabelFrame(self.root, text="对话")
        conv_frame.pack(fill="both", expand=True, **pad)

        # 使用 Text + 不同 tag 实现彩色输出
        self.txt_conv = tk.Text(
            conv_frame, wrap="word", state="disabled",
            background="#fafafa", font=("Microsoft YaHei", 10),
            padx=8, pady=6)
        scroll_y = ttk.Scrollbar(conv_frame, command=self.txt_conv.yview)
        self.txt_conv.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        scroll_y.pack(side="right", fill="y", pady=4)
        self.txt_conv.config(yscrollcommand=scroll_y.set)

        # 配置颜色 tag
        self.txt_conv.tag_config("user", foreground="#0066cc")
        self.txt_conv.tag_config("ai", foreground="#222222")
        self.txt_conv.tag_config("block", foreground="#cc0000",
                                  background="#ffe6e6")
        self.txt_conv.tag_config("system", foreground="#666666")
        self.txt_conv.tag_config("warn", foreground="#cc6600",
                                  background="#fff4e6")

        # --- 输入区 ---
        input_frame = ttk.LabelFrame(self.root, text="输入")
        input_frame.pack(fill="x", **pad)

        if self.hint_text:
            ttk.Label(input_frame, text=self.hint_text,
                      foreground="#666", font=("Microsoft YaHei", 8)).pack(
                          anchor="w", padx=8, pady=(4, 0))

        input_row = ttk.Frame(input_frame)
        input_row.pack(fill="x", padx=8, pady=4)

        self.ent_input = ttk.Entry(input_row, font=("Microsoft YaHei", 10))
        self.ent_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.ent_input.bind("<Return>", lambda e: self._on_send())
        self.ent_input.focus_set()

        self.btn_send = ttk.Button(input_row, text="发送", command=self._on_send)
        self.btn_send.pack(side="left")

        self.btn_clear = ttk.Button(input_row, text="清空",
                                     command=self._on_clear)
        self.btn_clear.pack(side="left", padx=(4, 0))

        # --- 底部状态栏 ---
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", side="bottom", **pad)
        ttk.Label(bottom, text="Enter 发送 · Shift+Enter 换行",
                  foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left")
        ttk.Button(bottom, text="状态详情",
                   command=self._on_status_detail).pack(side="right")

    # ============================ 行为 ============================ #
    def _on_send(self) -> None:
        """发送消息。双层审核在后台线程执行，避免界面卡死。"""
        if self._is_processing:
            return
        text = self.ent_input.get().strip()
        if not text:
            return

        # 锁定状态检查
        if not self.engine.is_service_available():
            state = self.engine.check_lock_status()
            self._append_log(f"[系统] 服务不可用：{state}", "block")
            messagebox.showwarning("DualGuard", f"服务不可用：{state}")
            return

        # 显示用户消息
        self._append_log(f"[你] {text}", "user")
        self.ent_input.delete(0, tk.END)
        self._is_processing = True
        self.btn_send.config(state="disabled", text="处理中...")
        self.lbl_status.config(text="状态：处理中...", foreground="#cc6600")

        # 后台线程执行双层审核（LLM 调用可能耗时）
        threading.Thread(
            target=self._process_async, args=(text,),
            daemon=True).start()

    def _process_async(self, text: str) -> None:
        """后台执行双层审核链路。"""
        try:
            # ① 前置审核
            pre = self.engine.audit_input(text)
            if pre.action == ACTION_BLOCK:
                self.root.after(0, self._on_pre_blocked, pre.reason, pre.category)
                return

            # ② 主模型生成
            raw = self.model.generate(text)

            # ③ 二次复核
            review = self.engine.audit_output(text, raw)
            if review.action == ACTION_BLOCK:
                self.root.after(0, self._on_review_blocked,
                                review.reason, review.category,
                                review.safe_output)
                return

            # 放行
            self.root.after(0, self._on_allowed, review.safe_output or raw)

        except Exception as e:
            self.root.after(0, self._on_error, str(e))
        finally:
            self.root.after(0, self._on_done)

    def _on_pre_blocked(self, reason: str, category: str) -> None:
        """前置审核拦截。"""
        self._append_log(f"[DualGuard] 拦截：{reason}", "block")
        self._append_log(f"  类别：{category}", "block")
        # 单次违规弹窗（硬性规则 3）
        popup_warn(f"输入被拦截：{reason}\n违规类别：{category}",
                   title="DualGuard 风控警告")
        self._refresh_status()

    def _on_review_blocked(self, reason: str, category: str,
                            safe_output: str) -> None:
        """二次复核拦截。"""
        self._append_log(f"[DualGuard] 二次复核拦截：{reason}", "block")
        if safe_output:
            self._append_log(f"[安全回复] {safe_output}", "warn")
        popup_warn(f"输出被二次复核拦截：{reason}\n已替换为安全提示。",
                   title="DualGuard 风控警告")
        self._refresh_status()

    def _on_allowed(self, output: str) -> None:
        """放行输出。"""
        self._append_log(f"[AI] {output}", "ai")

    def _on_error(self, err: str) -> None:
        """处理异常。"""
        self._append_log(f"[错误] {err}", "block")

    def _on_done(self) -> None:
        """处理完成。"""
        self._is_processing = False
        self.btn_send.config(state="normal", text="发送")
        self.lbl_status.config(text="状态：就绪", foreground="#0a7")
        self.ent_input.focus_set()

    def _on_clear(self) -> None:
        """清空对话区。"""
        self.txt_conv.config(state="normal")
        self.txt_conv.delete("1.0", "end")
        self.txt_conv.config(state="disabled")

    def _on_status_detail(self) -> None:
        """显示详细状态。"""
        report = self.engine.status_report()
        messagebox.showinfo("DualGuard 状态", report)

    def _on_close(self) -> None:
        """关闭窗口。"""
        self.root.destroy()

    # ============================ 辅助 ============================ #
    def _append_log(self, text: str, tag: str = "ai") -> None:
        """向对话区追加一条消息（线程安全）。"""
        def _do():
            ts = datetime.now().strftime("%H:%M:%S")
            self.txt_conv.config(state="normal")
            self.txt_conv.insert("end", f"{ts} ", "system")
            self.txt_conv.insert("end", text + "\n\n", tag)
            self.txt_conv.see("end")
            self.txt_conv.config(state="disabled")
        # 在主线程执行
        if threading.current_thread() is threading.main_thread():
            _do()
        else:
            self.root.after(0, _do)

    def _refresh_status(self) -> None:
        """刷新状态栏。"""
        try:
            count = len(self.engine.storage.list_violations())
            threshold = self.engine.config.lock_threshold
            self.lbl_violations.config(
                text=f"违规次数：{count} / {threshold}")
            if count >= threshold:
                self.lbl_violations.config(foreground="#cc0000")
            elif count > 0:
                self.lbl_violations.config(foreground="#cc6600")
            else:
                self.lbl_violations.config(foreground="#0a7")
        except Exception:
            pass

        # LLM 状态
        from .llm_adapter import llm_enabled
        if llm_enabled():
            url = os.environ.get("DUALGUARD_LLM_BASE_URL", "")
            mdl = os.environ.get("DUALGUARD_LLM_MODEL", "gpt-4o-mini")
            self.lbl_llm.config(text=f"LLM：已启用 ({mdl})", foreground="#0a7")
        else:
            self.lbl_llm.config(text="LLM：未启用（规则兜底）",
                                foreground="#666")

    def _lock_ui(self) -> None:
        """锁定 UI（被冻结/锁定时调用）。"""
        self.ent_input.config(state="disabled")
        self.btn_send.config(state="disabled", text="已锁定")
        self.lbl_status.config(text="状态：已锁定", foreground="#cc0000")
