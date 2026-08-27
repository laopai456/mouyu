"""简易 GUI — TDL 下载 + COS 上传"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import threading
import json
import os
import sys
import platform
import signal
import webbrowser
from pathlib import Path

# ── 路径配置（兼容 .py 和 .exe 运行）──
if getattr(sys, 'frozen', False):
    EXE_DIR = Path(sys.executable).parent     # exe 所在目录
else:
    EXE_DIR = Path(__file__).parent.parent    # 项目根目录

VENV_PYTHON = EXE_DIR / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)

DOWNLOAD_DIR = r"C:\Users\w\Downloads\tdl"
DOWNLOADER_SCRIPT = EXE_DIR / "tools" / "tdl_downloader" / "tdl_downloader_v2.py"
UPLOADER_SCRIPT = EXE_DIR / "tools" / "uploader" / "uploader.py"
UPLOADER_CACHE = EXE_DIR / "tools" / "uploader" / "cache" / "md5_cache.json"
DOWNLOADER_CACHE = EXE_DIR / "tools" / "tdl_downloader" / "cache" / "md5_cache.json"
DOWNLOADER_PROGRESS = EXE_DIR / "tools" / "tdl_downloader" / "cache" / "progress_cache.json"

INCLUDE_TYPES = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
# 托管版后台（本地 admin.html 缺失时的回退）
ADMIN_URL = "https://MOYU_ENV_ID_PLACEHOLDER-1414730090.tcloudbaseapp.com/admin.html"
ADMIN_DIR = EXE_DIR / "admin"
LOCAL_ADMIN_PORT = 9000
admin_server = None

running_process: subprocess.Popen | None = None
process_lock = threading.Lock()


# ── 计数 ──

def get_download_count() -> int:
    if not os.path.exists(DOWNLOAD_DIR):
        return 0
    return sum(
        1 for f in os.scandir(DOWNLOAD_DIR)
        if f.is_file() and f.name.split(".")[-1].lower() in INCLUDE_TYPES
    )


def get_upload_count() -> int:
    if UPLOADER_CACHE.exists():
        try:
            with open(UPLOADER_CACHE, "r", encoding="utf-8") as f:
                return len(json.load(f))
        except Exception:
            pass
    return 0


# ── 主窗口 ──

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("木偶鱼 - 下载/上传工具")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)

        # 当前运行状态: None | "download" | "upload"
        self.current_action: str | None = None

        # 样式
        style = ttk.Style()
        style.theme_use("vista")

        # ─ 顶部信息栏 ─
        info_frame = ttk.Frame(self.root, padding=12)
        info_frame.pack(fill=tk.X)

        ttk.Label(info_frame, text="📥 已下载:", font=("", 12)).pack(side=tk.LEFT, padx=(0, 4))
        self.dl_count_label = ttk.Label(info_frame, text="0", font=("", 16, "bold"), foreground="#667eea")
        self.dl_count_label.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(info_frame, text="📤 已上传:", font=("", 12)).pack(side=tk.LEFT, padx=(0, 4))
        self.ul_count_label = ttk.Label(info_frame, text="0", font=("", 16, "bold"), foreground="#52c41a")
        self.ul_count_label.pack(side=tk.LEFT)

        # ─ 按钮区 ─
        btn_frame = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        btn_frame.pack(fill=tk.X)

        self.dl_btn = ttk.Button(btn_frame, text="⬇ 开始下载", command=lambda: self.toggle_action("download"), width=16)
        self.dl_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.ul_btn = ttk.Button(btn_frame, text="⬆ 开始上传", command=lambda: self.toggle_action("upload"), width=16)
        self.ul_btn.pack(side=tk.LEFT, padx=(0, 20))

        # 清理缓存复选框
        self.clean_cache_var = tk.BooleanVar(value=False)
        self.clean_cache_cb = ttk.Checkbutton(
            btn_frame, text="下载前清理缓存", variable=self.clean_cache_var
        )
        self.clean_cache_cb.pack(side=tk.LEFT)

        # 第二行按钮区
        btn_row2 = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        btn_row2.pack(fill=tk.X)

        self.copy_log_btn = ttk.Button(btn_row2, text="📋 复制日志", command=self.copy_log, width=16)
        self.copy_log_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.admin_btn = ttk.Button(btn_row2, text="🔍 打开审核", command=self.open_admin, width=16)
        self.admin_btn.pack(side=tk.LEFT)

        # ─ 日志区 ─
        log_frame = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log = scrolledtext.ScrolledText(
            log_frame, font=("Consolas", 10), wrap=tk.WORD,
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
            state=tk.DISABLED,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        # 刷新计数
        self.refresh_counts()

        # 窗口关闭时清理子进程
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ── 日志写入 ──

    def log_write(self, text: str):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)
        self.root.update_idletasks()

    # ── 复制日志 ──

    def copy_log(self):
        content = self.log.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.copy_log_btn.config(text="✅ 已复制")
        self.root.after(2000, lambda: self.copy_log_btn.config(text="📋 复制日志"))

    # ── 打开审核页面 ──

    def _ensure_local_admin(self) -> str:
        """本地起静态服务托管 admin/ 目录；admin.html 缺失时回退托管版 URL"""
        global admin_server
        if not (ADMIN_DIR / "admin.html").exists():
            self.log_write("WARN 本地admin.html不存在，回退打开托管版\n")
            return ADMIN_URL
        if admin_server is None:
            try:
                from functools import partial
                from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
                handler = partial(SimpleHTTPRequestHandler, directory=str(ADMIN_DIR))
                admin_server = ThreadingHTTPServer(("localhost", LOCAL_ADMIN_PORT), handler)
                admin_server.daemon_threads = True
                threading.Thread(target=admin_server.serve_forever, daemon=True).start()
                self.log_write(f"INFO 本地审核服务已启动 http://localhost:{LOCAL_ADMIN_PORT}/admin.html\n")
            except OSError:
                # 端口已被占用：大概率已有本地服务在跑，直接复用
                self.log_write(f"INFO 端口{LOCAL_ADMIN_PORT}已被占用，复用现有服务\n")
        return f"http://localhost:{LOCAL_ADMIN_PORT}/admin.html"

    def open_admin(self):
        url = self._ensure_local_admin()
        webbrowser.open(url)
        self.admin_btn.config(text="✅ 已打开")
        self.root.after(2000, lambda: self.admin_btn.config(text="🔍 打开审核"))

    # ── 计数刷新 ──

    def refresh_counts(self):
        self.dl_count_label.config(text=str(get_download_count()))
        self.ul_count_label.config(text=str(get_upload_count()))
        self.root.after(5000, self.refresh_counts)

    # ── 按钮切换 ──

    def toggle_action(self, action: str):
        if self.current_action == action:
            # 正在运行 → 停止
            self.stop_process()
        else:
            # 空闲 → 启动
            if action == "download":
                self.start_download()
            else:
                self.start_upload()

    def _kill_tree(self):
        """强制终止进程树（包括 tdl 等孙进程）"""
        global running_process
        with process_lock:
            if running_process and running_process.poll() is None:
                pid = running_process.pid
                # Windows: taskkill /T 杀整个进程树
                if platform.system() == "Windows":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        capture_output=True,
                    )
                else:
                    running_process.kill()
                try:
                    running_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                running_process = None

    def stop_process(self):
        self._kill_tree()
        self.log_write("\n⏹ 已手动停止\n")
        self.current_action = None
        self.dl_btn.config(text="⬇ 开始下载", state=tk.NORMAL)
        self.ul_btn.config(text="⬆ 开始上传", state=tk.NORMAL)

    # ── 运行子进程 ──

    def run_subprocess(self, cmd: list[str], desc: str, action: str):
        global running_process
        self.log_write(f"{'=' * 50}\n")
        self.log_write(f"{desc}\n")
        self.log_write(f"{' '.join(cmd)}\n")
        self.log_write(f"{'=' * 50}\n")

        # 切换按钮状态
        self.current_action = action
        btn = self.dl_btn if action == "download" else self.ul_btn
        other_btn = self.ul_btn if action == "download" else self.dl_btn
        btn.config(text="⏹ 停止", state=tk.NORMAL)
        other_btn.config(state=tk.DISABLED)

        def worker():
            global running_process
            try:
                with process_lock:
                    env = os.environ.copy()
                    env["PYTHONIOENCODING"] = "utf-8"
                    p = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                        env=env,
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                        ) if platform.system() == "Windows" else 0,
                    )
                    running_process = p

                for line in p.stdout:
                    self.log_write(line)

                p.wait()

                with process_lock:
                    if running_process == p:
                        running_process = None

                if p.returncode == 0:
                    self.log_write(f"\n✓ {desc}完成\n")
                else:
                    self.log_write(f"\n✗ {desc}失败 (返回码 {p.returncode})\n")
            except Exception as e:
                self.log_write(f"\n✗ 错误: {e}\n")
            finally:
                self.root.after(0, self.set_buttons_idle)

        threading.Thread(target=worker, daemon=True).start()

    def set_buttons_idle(self):
        self.current_action = None
        self.dl_btn.config(text="⬇ 开始下载", state=tk.NORMAL)
        self.ul_btn.config(text="⬆ 开始上传", state=tk.NORMAL)
        self.root.after(0, self.refresh_counts)

    # ── 下载 ──

    def start_download(self):
        if self.clean_cache_var.get():
            for f in [DOWNLOADER_CACHE, DOWNLOADER_PROGRESS]:
                if f.exists():
                    f.unlink()
                    self.log_write(f"已清理: {f.name}\n")
        cmd = [str(VENV_PYTHON), str(DOWNLOADER_SCRIPT), "--auto"]
        self.run_subprocess(cmd, "下载图片", "download")

    # ── 上传 ──

    def start_upload(self):
        cmd = [str(VENV_PYTHON), str(UPLOADER_SCRIPT)]
        self.run_subprocess(cmd, "上传图片", "upload")

    # ── 关闭 ──

    def on_close(self):
        self._kill_tree()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()