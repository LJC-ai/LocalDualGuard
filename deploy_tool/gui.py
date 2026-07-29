"""DualGuard 一键部署图形化工具（零依赖，跨平台）。

启动流程：
1. 先弹出「审核 AI 模型选择」对话框
2. 用户选择 DeepSeek 系列模型（2b / 3b / 7b）
3. 自动调用 `ollama pull` 下载安装（如未安装）
4. 安装完成后进入主部署界面

入口：
    python -m deploy_tool
    python deploy_tool/gui.py
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Tuple


# -------------------------------------------------------------------- #
#  路径与常量
# -------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CONFIG_FILE = Path.home() / ".dualguard_deploy.json"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

# 预定义的 DeepSeek 模型列表（按参数规模排序）
DEEPSEEK_MODELS = [
    ("DeepSeek-R1:2B", "deepseek-r1:2b",
     "轻量级，约 4GB 显存，速度快，适合开发测试"),
    ("DeepSeek-R1:3B", "deepseek-r1:3b",
     "中等规模，约 6GB 显存，平衡速度与质量"),
    ("DeepSeek-R1:6.7B", "deepseek-r1:6.7b",
     "旗舰版，约 13GB 显存，最佳质量，适合生产环境"),
]


# -------------------------------------------------------------------- #
#  工具函数：Ollama 操作
# -------------------------------------------------------------------- #
def find_ollama() -> Optional[str]:
    cmd = "where" if sys.platform.startswith("win") else "which"
    try:
        r = subprocess.run([cmd, "ollama"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def ollama_is_running() -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(f"{OLLAMA_BASE_URL.rstrip('/v1')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False


def list_ollama_models() -> List[str]:
    try:
        import urllib.request
        import json
        req = urllib.request.Request(f"{OLLAMA_BASE_URL.rstrip('/v1')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _ollama_pull(ollama_path: str, model_name: str,
                 progress_callback=None) -> bool:
    """调用 ollama pull 下载模型。返回是否成功。"""
    try:
        proc = subprocess.Popen(
            [ollama_path, "pull", model_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:  # type: ignore
            line = line.rstrip()
            if progress_callback:
                progress_callback(line)
        return proc.wait(timeout=3600) == 0
    except (subprocess.TimeoutExpired, Exception) as e:
        if progress_callback:
            progress_callback(f"下载失败: {e}")
        return False


# -------------------------------------------------------------------- #
#  步骤 0：启动时模型选择弹窗（DeepSeek 2b/3b/7b）
# -------------------------------------------------------------------- #
class ModelSelectDialog:
    """启动时弹出的模型选择对话框。"""

    def __init__(self, parent: tk.Tk) -> None:
        self.parent = parent
        self.parent.withdraw()

        self.result: Optional[str] = None
        self.ollama_path = find_ollama()

        self._build_dialog()

    def _build_dialog(self) -> None:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("选择审核 AI 模型")
        self.dialog.geometry("560x420")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

        pad = {"padx": 12, "pady": 8}

        # 标题
        ttk.Label(self.dialog, text="📦 选择前置审核 AI 模型",
                  font=("Microsoft YaHei", 12, "bold")).pack(**pad)

        # 提示
        ttk.Label(self.dialog,
                  text="选择后将自动下载安装（需联网，首次下载约数分钟）",
                  foreground="#666").pack(padx=12, pady=(0, 8))

        # 模型列表
        self.selected_model = tk.StringVar()
        self.selected_model.set(DEEPSEEK_MODELS[1][1])

        for display_name, model_name, desc in DEEPSEEK_MODELS:
            row = ttk.Frame(self.dialog)
            row.pack(fill="x", padx=12, pady=4)
            ttk.Radiobutton(row, text=display_name,
                            variable=self.selected_model,
                            value=model_name).pack(anchor="w")
            ttk.Label(row, text=f"  {desc}",
                      foreground="#666", font=("Tahoma", 8)).pack(anchor="w")

        # 进度区
        progress_frame = ttk.LabelFrame(self.dialog, text="下载进度")
        progress_frame.pack(fill="x", **pad)

        self.txt_progress = tk.Text(progress_frame, height=5, wrap="word",
                                     background="#1e1e1e", foreground="#d4d4d4",
                                     font=("Consolas", 9), state="disabled")
        self.txt_progress.pack(fill="x", padx=4, pady=4)

        # 按钮
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(fill="x", **pad)

        self.btn_select = ttk.Button(btn_frame, text="选择并安装",
                                      command=self._on_select)
        self.btn_select.pack(side="left", padx=4)

        ttk.Button(btn_frame, text="跳过（使用规则兜底）",
                   command=self._on_skip).pack(side="left", padx=4)

        # 检查已安装模型并自动选中
        self._check_installed_models()

    def _check_installed_models(self) -> None:
        """检查哪些模型已安装，自动选中已安装的最大模型。"""
        def worker():
            if not ollama_is_running():
                return
            installed = list_ollama_models()
            # 从大到小检查
            for _, model_name, _ in reversed(DEEPSEEK_MODELS):
                if any(model_name in m for m in installed):
                    self.selected_model.set(model_name)
                    self.txt_progress.config(state="normal")
                    self.txt_progress.insert("end",
                                             f"✓ 检测到已安装：{model_name}\n")
                    self.txt_progress.config(state="disabled")
                    break
        threading.Thread(target=worker, daemon=True).start()

    def _on_select(self) -> None:
        model_name = self.selected_model.get()
        if not self.ollama_path:
            if not messagebox.askyesno(
                "Ollama 未安装",
                "未检测到 Ollama。请先安装：\nhttps://ollama.com/download\n\n"
                "是否继续？（继续将只保存配置，需自行安装 Ollama 后生效）"
            ):
                return
            self.result = model_name
            self.dialog.destroy()
            self.parent.deiconify()
            return

        # 检查是否已安装
        installed = list_ollama_models()
        if any(model_name in m for m in installed):
            self.result = model_name
            self.dialog.destroy()
            self.parent.deiconify()
            return

        # 开始下载
        self.btn_select.config(state="disabled")
        self.txt_progress.config(state="normal")
        self.txt_progress.insert("end", f"开始下载模型：{model_name}\n")
        self.txt_progress.see("end")
        self.txt_progress.config(state="disabled")

        def progress(line: str) -> None:
            self.txt_progress.config(state="normal")
            self.txt_progress.insert("end", line + "\n")
            self.txt_progress.see("end")
            self.txt_progress.config(state="disabled")

        def worker():
            success = _ollama_pull(self.ollama_path, model_name, progress)
            self.dialog.after(0, self._on_download_done, success, model_name)

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_done(self, success: bool, model_name: str) -> None:
        if success:
            self.result = model_name
            self.txt_progress.config(state="normal")
            self.txt_progress.insert("end", "✓ 下载完成！\n")
            self.txt_progress.config(state="disabled")
            messagebox.showinfo("下载完成", f"模型 {model_name} 安装成功！")
            self.dialog.destroy()
            self.parent.deiconify()
        else:
            self.btn_select.config(state="normal")
            messagebox.showerror("下载失败",
                                 "模型下载失败，请检查网络连接后重试。")

    def _on_skip(self) -> None:
        self.result = None
        self.dialog.destroy()
        self.parent.deiconify()


# -------------------------------------------------------------------- #
#  主 GUI
# -------------------------------------------------------------------- #
class DeployGUI:
    """一键部署主窗口。"""

    def __init__(self, root: tk.Tk, selected_model: Optional[str]) -> None:
        self.root = root
        self.root.title("DualGuard 一键部署工具")
        self.root.geometry("720x620")
        self.root.minsize(640, 560)

        self.ollama_path: Optional[str] = find_ollama()
        self.dualguard_process: Optional[subprocess.Popen] = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.config_path = CONFIG_FILE
        self.selected_model = selected_model

        self.root.after(100, self._drain_log_queue)
        self._build_ui()
        self._async_health_check()

        if selected_model:
            self._log(f"已选择模型：{selected_model}")

    # ============================ UI ============================ #
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # --- 顶部状态条 ---
        top = ttk.LabelFrame(self.root, text="环境检测")
        top.pack(fill="x", **pad)

        self.lbl_ollama = ttk.Label(top, text="检测 Ollama 中...", foreground="#666")
        self.lbl_ollama.pack(anchor="w", padx=10, pady=4)

        self.lbl_running = ttk.Label(top, text="Ollama 服务状态：未知", foreground="#666")
        self.lbl_running.pack(anchor="w", padx=10, pady=2)

        # --- 步骤 1: 选择版本 ---
        s1 = ttk.LabelFrame(self.root, text="步骤 1：选择 DualGuard 版本")
        s1.pack(fill="x", **pad)

        self.edition_var = tk.StringVar(value="sec")
        ttk.Radiobutton(s1, text="DualGuard-Sec 安全业务版",
                        variable=self.edition_var, value="sec").pack(anchor="w", padx=10)
        ttk.Radiobutton(s1, text="DualGuard-Student 学生业务版",
                        variable=self.edition_var, value="student").pack(anchor="w", padx=10)

        # --- 步骤 2: 选择模型 ---
        s2 = ttk.LabelFrame(self.root, text="步骤 2：选择 LLM 模型")
        s2.pack(fill="x", **pad)

        self.model_source = tk.StringVar(value="existing")
        ttk.Radiobutton(s2, text="A. 使用已下载的 Ollama 模型",
                        variable=self.model_source, value="existing",
                        command=self._toggle_model_source).pack(anchor="w", padx=10, pady=(4, 0))

        existing_row = ttk.Frame(s2)
        existing_row.pack(fill="x", padx=24, pady=2)
        self.cb_models = ttk.Combobox(existing_row, state="readonly", width=40)
        self.cb_models.pack(side="left", padx=(0, 6))
        ttk.Button(existing_row, text="刷新", width=6,
                    command=self._refresh_models).pack(side="left")

        ttk.Radiobutton(s2, text="B. 从本地 GGUF 文件导入",
                        variable=self.model_source, value="gguf",
                        command=self._toggle_model_source).pack(anchor="w", padx=10, pady=(8, 0))

        gguf_row = ttk.Frame(s2)
        gguf_row.pack(fill="x", padx=24, pady=2)
        self.ent_gguf = ttk.Entry(gguf_row, width=40)
        self.ent_gguf.pack(side="left", padx=(0, 6))
        self.ent_gguf.config(state="disabled")
        ttk.Button(gguf_row, text="浏览...", width=8,
                   command=self._pick_gguf).pack(side="left")
        self.btn_gguf_browse = gguf_row.winfo_children()[-1]

        name_row = ttk.Frame(s2)
        name_row.pack(fill="x", padx=24, pady=2)
        ttk.Label(name_row, text="导入后模型名：").pack(side="left")
        self.ent_model_name = ttk.Entry(name_row, width=30)
        self.ent_model_name.pack(side="left", padx=6)
        self.ent_model_name.insert(0, "dualguard-custom")
        self.ent_model_name.config(state="disabled")

        # --- 步骤 3: 启动模式 ---
        s3 = ttk.LabelFrame(self.root, text="步骤 3：启动模式")
        s3.pack(fill="x", **pad)

        self.run_mode = tk.StringVar(value="repl")
        ttk.Radiobutton(s3, text="前台交互式（REPL，开发/测试用）",
                        variable=self.run_mode, value="repl").pack(anchor="w", padx=10)
        ttk.Radiobutton(s3, text="后台常驻服务（systemd / 后台进程，生产用）",
                        variable=self.run_mode, value="service").pack(anchor="w", padx=10)

        # --- 操作按钮 ---
        btns = ttk.Frame(self.root)
        btns.pack(fill="x", **pad)
        self.btn_deploy = ttk.Button(btns, text="🚀 一键部署并启动",
                                     command=self._on_deploy)
        self.btn_deploy.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(btns, text="⏹ 停止 DualGuard",
                                    command=self._on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        ttk.Button(btns, text="🔄 重新检测环境",
                   command=self._async_health_check).pack(side="left", padx=4)

        # --- 日志输出 ---
        log_frame = ttk.LabelFrame(self.root, text="部署日志")
        log_frame.pack(fill="both", expand=True, **pad)
        self.txt_log = tk.Text(log_frame, height=10, wrap="word",
                              background="#1e1e1e", foreground="#d4d4d4",
                              font=("Consolas", 9), state="disabled")
        self.txt_log.pack(fill="both", expand=True, side="left", padx=4, pady=4)
        scroll = ttk.Scrollbar(log_frame, command=self.txt_log.yview)
        scroll.pack(side="right", fill="y")
        self.txt_log.config(yscrollcommand=scroll.set)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken",
                  anchor="w").pack(fill="x", side="bottom")

        self._load_saved_config()

    # ============================ 行为 ============================ #
    def _toggle_model_source(self) -> None:
        if self.model_source.get() == "existing":
            self.cb_models.config(state="readonly")
            self.ent_gguf.config(state="disabled")
            self.ent_model_name.config(state="disabled")
            self.btn_gguf_browse.config(state="disabled")
        else:
            self.cb_models.config(state="disabled")
            self.ent_gguf.config(state="normal")
            self.ent_model_name.config(state="normal")
            self.btn_gguf_browse.config(state="normal")

    def _pick_gguf(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 GGUF 模型文件",
            filetypes=[("GGUF 模型", "*.gguf"), ("所有文件", "*.*")]
        )
        if path:
            self.ent_gguf.delete(0, tk.END)
            self.ent_gguf.insert(0, path)

    def _log(self, msg: str) -> None:
        self.log_queue.put(msg)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.txt_log.config(state="normal")
                self.txt_log.insert("end", msg + "\n")
                self.txt_log.see("end")
                self.txt_log.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log_queue)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _async_health_check(self) -> None:
        self.lbl_ollama.config(text="检测 Ollama 中...", foreground="#666")
        self.lbl_running.config(text="Ollama 服务状态：检测中...", foreground="#666")
        threading.Thread(target=self._health_check_worker, daemon=True).start()

    def _health_check_worker(self) -> None:
        if self.ollama_path:
            self.lbl_ollama.config(
                text=f"✓ Ollama 已安装：{self.ollama_path}", foreground="#0a7")
        else:
            self.lbl_ollama.config(
                text="✗ 未检测到 ollama，请先安装：https://ollama.com/download",
                foreground="#a00")
        if ollama_is_running():
            self.lbl_running.config(text="✓ Ollama 服务运行中", foreground="#0a7")
            self._refresh_models()
        else:
            self.lbl_running.config(text="○ Ollama 服务未运行（部署时会自动启动）",
                                    foreground="#a60")

    def _refresh_models(self) -> None:
        def worker():
            models = list_ollama_models()
            self.cb_models["values"] = models
            if self.selected_model and self.selected_model in models:
                self.cb_models.set(self.selected_model)
            elif models and not self.cb_models.get():
                self.cb_models.set(models[0])
            if not models:
                self.cb_models.set("")
        threading.Thread(target=worker, daemon=True).start()

    def _on_deploy(self) -> None:
        edition = self.edition_var.get()
        model_name = self._resolve_model_name()
        if not model_name:
            messagebox.showerror("错误", "请选择或输入模型名")
            return

        if not self.ollama_path:
            if not messagebox.askyesno(
                "Ollama 未安装",
                "未检测到 ollama。是否继续？"
            ):
                return

        self._save_config(edition, model_name)
        self.btn_deploy.config(state="disabled")
        self._set_status("部署中...")

        threading.Thread(target=self._deploy_worker,
                         args=(edition, model_name), daemon=True).start()

    def _resolve_model_name(self) -> str:
        if self.model_source.get() == "existing":
            return self.cb_models.get().strip()
        gguf_path = self.ent_gguf.get().strip()
        if not gguf_path or not Path(gguf_path).exists():
            return ""
        return self.ent_model_name.get().strip() or "dualguard-custom"

    def _deploy_worker(self, edition: str, model_name: str) -> None:
        try:
            if self.ollama_path and not ollama_is_running():
                self._log("→ 启动 ollama serve（后台）...")
                self._start_ollama_serve()
                for _ in range(15):
                    time.sleep(1)
                    if ollama_is_running():
                        self._log("✓ Ollama 服务已就绪")
                        break
                else:
                    self._log("✗ Ollama 启动超时")
            elif ollama_is_running():
                self._log("✓ Ollama 已在运行")

            if self.model_source.get() == "gguf":
                gguf_path = self.ent_gguf.get().strip()
                self._log(f"→ 从 GGUF 创建模型 {model_name} ...")
                self._ollama_create(gguf_path, model_name)
                self._log(f"✓ 模型 {model_name} 创建完成")

            self._log("→ 写入 DualGuard LLM 配置...")
            self._write_llm_config(edition, model_name)
            self._log(f"✓ 配置写入：model={model_name}, base_url={OLLAMA_BASE_URL}")

            mode = self.run_mode.get()
            self._log(f"→ 启动 DualGuard-{edition} （模式：{mode}）...")
            self._start_dualguard(edition, mode)

            self._set_status("部署完成 ✓")
            self._log("=" * 50)
            self._log(f"✅ 部署完成！DualGuard-{edition} 已接入模型 {model_name}")
            self.btn_stop.config(state="normal")

        except Exception as e:
            self._log(f"✗ 部署失败：{e}")
            self._set_status("部署失败")
        finally:
            self.root.after(0, lambda: self.btn_deploy.config(state="normal"))

    def _start_ollama_serve(self) -> None:
        if not self.ollama_path:
            return
        flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        subprocess.Popen(
            [self.ollama_path, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )

    def _ollama_create(self, gguf_path: str, model_name: str) -> None:
        modelfile = f"FROM {gguf_path}\n"
        proc = subprocess.run(
            [self.ollama_path, "create", model_name, "-f", "-"],
            input=modelfile.encode("utf-8"),
            capture_output=True,
            timeout=600,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace")[:300]
            raise RuntimeError(f"ollama create 失败：{err}")

    def _write_llm_config(self, edition: str, model_name: str) -> None:
        env_file = Path.home() / f".dualguard-{edition}.env"
        content = (
            f"# DualGuard-{edition} LLM 配置\n"
            f"DUALGUARD_LLM_BASE_URL={OLLAMA_BASE_URL}\n"
            f"DUALGUARD_LLM_API_KEY=ollama\n"
            f"DUALGUARD_LLM_MODEL={model_name}\n"
        )
        env_file.write_text(content, encoding="utf-8")
        try:
            os.chmod(env_file, 0o600)
        except OSError:
            pass

    def _start_dualguard(self, edition: str, mode: str) -> None:
        module = f"dualguard_{edition}.main"
        env = os.environ.copy()
        env_file = Path.home() / f".dualguard-{edition}.env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()

        if mode == "service":
            if sys.platform.startswith("win"):
                flags = subprocess.CREATE_NO_WINDOW
                self.dualguard_process = subprocess.Popen(
                    [sys.executable, "-m", module, "--service"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
                self._log(f"✓ 后台服务已启动（PID={self.dualguard_process.pid}）")
            else:
                svc = f"dualguard-{edition}.service"
                subprocess.run(["systemctl", "start", svc], check=False)
                self._log(f"✓ 已启动 systemd 服务 {svc}")
        else:
            self.dualguard_process = subprocess.Popen(
                [sys.executable, "-m", module],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            threading.Thread(target=self._pump_output,
                             args=(self.dualguard_process,), daemon=True).start()

    def _pump_output(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stdout:  # type: ignore
                self._log(line.rstrip())
        except Exception:
            pass

    def _on_stop(self) -> None:
        edition = self.edition_var.get()
        if self.run_mode.get() == "service" and not sys.platform.startswith("win"):
            subprocess.run(["systemctl", "stop", f"dualguard-{edition}.service"],
                           check=False)
            self._log(f"已停止 systemd 服务 dualguard-{edition}")
        elif self.dualguard_process and self.dualguard_process.poll() is None:
            self.dualguard_process.terminate()
            try:
                self.dualguard_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.dualguard_process.kill()
            self._log("已停止 DualGuard 进程")
        self.btn_stop.config(state="disabled")
        self._set_status("已停止")

    def _save_config(self, edition: str, model_name: str) -> None:
        import json
        data = {
            "edition": edition,
            "model_name": model_name,
            "model_source": self.model_source.get(),
            "run_mode": self.run_mode.get(),
        }
        try:
            self.config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        except OSError:
            pass

    def _load_saved_config(self) -> None:
        import json
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            self.edition_var.set(data.get("edition", "sec"))
            self.model_source.set(data.get("model_source", "existing"))
            self.run_mode.set(data.get("run_mode", "repl"))
            self._toggle_model_source()
            if data.get("model_name"):
                self.cb_models.set(data["model_name"])
        except (json.JSONDecodeError, OSError):
            pass


# -------------------------------------------------------------------- #
#  入口
# -------------------------------------------------------------------- #
def main() -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("[ERR] 系统未安装 tkinter。")
        if sys.platform.startswith("linux"):
            print("      Ubuntu/Debian: sudo apt install python3-tk")
            print("      CentOS/RHEL:   sudo yum install python3-tkinter")
        return 1

    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # 步骤 1：弹出模型选择对话框（用户选 DeepSeek 模型，自动下载）
    model_dialog = ModelSelectDialog(root)
    root.wait_window(model_dialog.dialog)
    selected_model = model_dialog.result

    # 步骤 2：进入主部署界面
    app = DeployGUI(root, selected_model)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
