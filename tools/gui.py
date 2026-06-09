"""简易 GUI — TDL 下载 + COS 上传"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import threading
import json
import os
import sys
import platform
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

process: subprocess.Popen | None = None
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
        btn_frame = ttk.Frame(self.root, padding=12)
        btn_frame.pack(fill=tk.X)

        self.dl_btn = ttk.Button(btn_frame, text="⬇ 开始下载", command=self.start_download, width=16)
        self.dl_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.ul_btn = ttk.Button(btn_frame, text="⬆ 开始上传", command=self.start_upload, width=16)
        self.ul_btn.pack(side=tk.LEFT, padx=(0, 20))

        # 清理缓存复选框
        self.clean_cache_var = tk.BooleanVar(value=False)
        self.clean_cache_cb = ttk.Checkbutton(
            btn_frame, text="下载前清理缓存", variable=self.clean_cache_var
        )
        self.clean_cache_cb.pack(side=tk.LEFT)

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

    # ── 计数刷新 ──

    def refresh_counts(self):
        self.dl_count_label.config(text=str(get_download_count()))
        self.ul_count_label.config(text=str(get_upload_count()))
        self.root.after(5000, self.refresh_counts)

    # ── 按钮状态 ──

    def set_buttons_enabled(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.dl_btn.config(state=state)
        self.ul_btn.config(state=state)

    # ── 运行子进程 ──

    def run_subprocess(self, cmd: list[str], desc: str):
        global process
        self.log_write(f"{'=' * 50}\n")
        self.log_write(f"{desc}\n")
        self.log_write(f"{' '.join(cmd)}\n")
        self.log_write(f"{'=' * 50}\n")

        self.set_buttons_enabled(False)

        def worker():
            global process
            try:
                with process_lock:
                    p = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                        creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
                    )
                    process = p

                for line in p.stdout:
                    self.log_write(line)

                p.wait()

                with process_lock:
                    process = None

                if p.returncode == 0:
                    self.log_write(f"\n✓ {desc}完成\n")
                else:
                    self.log_write(f"\n✗ {desc}失败 (返回码 {p.returncode})\n")
            except Exception as e:
                self.log_write(f"\n✗ 错误: {e}\n")
            finally:
                self.root.after(0, self.set_buttons_enabled, True)
                self.root.after(0, self.refresh_counts)

        threading.Thread(target=worker, daemon=True).start()

    # ── 下载 ──

    def start_download(self):
        # 勾选了清理缓存
        if self.clean_cache_var.get():
            for f in [DOWNLOADER_CACHE, DOWNLOADER_PROGRESS]:
                if f.exists():
                    f.unlink()
                    self.log_write(f"已清理: {f.name}\n")
        cmd = [str(VENV_PYTHON), str(DOWNLOADER_SCRIPT), "--auto"]
        self.run_subprocess(cmd, "下载图片")

    # ── 上传 ──

    def start_upload(self):
        cmd = [str(VENV_PYTHON), str(UPLOADER_SCRIPT)]
        self.run_subprocess(cmd, "上传图片")

    # ── 关闭 ──

    def on_close(self):
        global process
        with process_lock:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()