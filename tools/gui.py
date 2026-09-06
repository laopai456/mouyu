"""简易 GUI — TDL 下载 + COS 上传"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import threading
import json
import os
import re
import sys
import platform
import signal
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
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

# ── QQ 机器人（qqbot 仓库）控制 ──
QQBOT_DIR = Path(r"C:\Users\w\Documents\GitHub\qqbot")
QQBOT_LOG_DIR = QQBOT_DIR / "logs"
QQBOT_BOT_LOG = QQBOT_LOG_DIR / "bot.log"
QQBOT_STOP_FLAG = QQBOT_LOG_DIR / "STOPPED"
QQBOT_SILENT_VBS = QQBOT_DIR / "silent_start_bot.vbs"
QQBOT_STATUS_BAT = QQBOT_DIR / "机器人状态.bat"
BOT_LOG_INIT_BYTES = 8000   # 打开窗口时回看 bot.log 的字节数
BOT_LOG_MAX_LINES = 3000    # 机器人日志面板保留的行数上限
BOT_PORT = 8080             # NoneBot 监听端口（bot 存活判定，与看门狗一致）
# loguru 写进 bot.log 的 ANSI 颜色码，tk 文本框不解释，显示前剥掉
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

INCLUDE_TYPES = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
# 托管版后台（本地 admin.html 缺失时的回退）
ADMIN_URL = os.environ.get("MOYU_ADMIN_URL", "https://MOYU_ENV_ID_PLACEHOLDER-1414730090.tcloudbaseapp.com/admin.html")
ADMIN_DIR = EXE_DIR / "admin"
LOCAL_ADMIN_PORT = 9000
admin_server = None


class _QuietAdminHandler(SimpleHTTPRequestHandler):
    """静默版静态服务 handler。

    windowed exe（console=False）下 sys.stderr 为 None，父类 log_message
    每请求写 stderr 会抛异常掐断连接（浏览器表现为 ERR_EMPTY_RESPONSE），
    故覆写为静默。directory 由构造参数传入。
    """
    def log_message(self, format, *args):
        pass

    def end_headers(self):
        # 本地开发服务，禁缓存：否则浏览器 heuristic 缓存旧 admin.html，
        # 改完页面再点「打开审核」看到的还是旧版
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class _QuietAdminServer(ThreadingHTTPServer):
    """同上：默认 handle_error 会 print 到 stderr，一并静默。"""
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass

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
        self.root.geometry("1000x620")
        self.root.minsize(800, 480)

        # 当前运行状态: None | "download" | "upload"
        self.current_action: str | None = None
        # 机器人按钮互斥（启/停/清理 同时只允许一个在跑）
        self._bot_busy = False

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
        btn_row2 = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        btn_row2.pack(fill=tk.X)

        self.copy_log_btn = ttk.Button(btn_row2, text="📋 复制日志", command=self.copy_log, width=16)
        self.copy_log_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.admin_btn = ttk.Button(btn_row2, text="🔍 打开审核", command=self.open_admin, width=16)
        self.admin_btn.pack(side=tk.LEFT)

        # 第三行按钮区：QQ 机器人控制（判定/清退逻辑与 qqbot 看门狗同一套）
        btn_row3 = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        btn_row3.pack(fill=tk.X)

        self.bot_start_btn = ttk.Button(btn_row3, text="🤖 启动机器人", command=self.bot_start, width=14)
        self.bot_start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.bot_stop_btn = ttk.Button(btn_row3, text="⏹ 停止机器人", command=self.bot_stop, width=14)
        self.bot_stop_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.bot_panel_btn = ttk.Button(btn_row3, text="📊 打开面板", command=self.bot_panel, width=14)
        self.bot_panel_btn.pack(side=tk.LEFT)

        # ─ 日志区（左右分屏：工具日志 | 机器人日志） ─
        log_frame = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        log_frame.pack(fill=tk.BOTH, expand=True)

        log_paned = ttk.PanedWindow(log_frame, orient=tk.HORIZONTAL)
        log_paned.pack(fill=tk.BOTH, expand=True)

        tool_pane = ttk.LabelFrame(log_paned, text="工具日志", padding=2)
        bot_pane = ttk.LabelFrame(log_paned, text="机器人日志（qqbot/logs/bot.log）", padding=2)
        log_paned.add(tool_pane, weight=1)
        log_paned.add(bot_pane, weight=1)

        self.log = scrolledtext.ScrolledText(
            tool_pane, font=("Consolas", 10), wrap=tk.WORD,
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
            state=tk.DISABLED,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        self.botlog = scrolledtext.ScrolledText(
            bot_pane, font=("Consolas", 10), wrap=tk.WORD,
            bg="#1e1e1e", fg="#9cdcfe", insertbackground="white",
            state=tk.DISABLED,
        )
        self.botlog.pack(fill=tk.BOTH, expand=True)

        # 刷新计数
        self.refresh_counts()

        # 机器人日志尾随线程（不管 bot 由谁启动，tail bot.log 都能看到）
        threading.Thread(target=self._tail_bot_log, daemon=True).start()

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
                handler = partial(_QuietAdminHandler, directory=str(ADMIN_DIR))
                admin_server = _QuietAdminServer(("localhost", LOCAL_ADMIN_PORT), handler)

                def _serve():
                    try:
                        admin_server.serve_forever()
                    except Exception as e:
                        self.log_write(f"ERROR 本地审核服务异常退出: {e}\n")

                threading.Thread(target=_serve, daemon=True).start()
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

    # ── 机器人日志面板 ──

    def bot_log_write(self, text: str):
        self.botlog.config(state=tk.NORMAL)
        self.botlog.insert(tk.END, text)
        # 行数封顶，超出删最旧的，避免长跑撑爆内存
        lines = int(self.botlog.index("end-1c").split(".")[0])
        if lines > BOT_LOG_MAX_LINES:
            self.botlog.delete("1.0", f"{lines - BOT_LOG_MAX_LINES}.0")
        self.botlog.see(tk.END)
        self.botlog.config(state=tk.DISABLED)

    def _tail_bot_log(self):
        """每秒尾随 qqbot/logs/bot.log（bot.py 写入为 UTF-8，与状态面板同源）。"""
        pos = 0
        inited = False
        skip_partial = False
        while True:
            try:
                if QQBOT_BOT_LOG.exists():
                    size = QQBOT_BOT_LOG.stat().st_size
                    if not inited:
                        inited = True
                        if size > BOT_LOG_INIT_BYTES:
                            pos = size - BOT_LOG_INIT_BYTES
                            skip_partial = True  # 从中间起读，首行多半是半截
                            self.bot_log_write("……（仅回看最近部分日志）\n")
                    if size < pos:  # 日志轮转（start_silent.bat 超 10MB 会删了重建）
                        pos = 0
                        self.bot_log_write("[bot.log 已重建，重新从头跟踪]\n")
                    if size > pos:
                        with open(QQBOT_BOT_LOG, "rb") as f:
                            f.seek(pos)
                            chunk = f.read()
                        pos += len(chunk)
                        if skip_partial:
                            nl = chunk.find(b"\n")
                            if nl != -1:
                                chunk = chunk[nl + 1:]
                                skip_partial = False
                            else:
                                chunk = b""
                        text = _ANSI_RE.sub("", chunk.decode("utf-8", errors="replace"))
                        if text:
                            self.bot_log_write(text)
            except Exception:
                pass  # 读日志失败下一秒重试
            time.sleep(1)

    # ── 机器人启停 ──

    def bot_start(self):
        self._bot_action(self._do_bot_start)

    def bot_stop(self):
        self._bot_action(self._do_bot_stop)

    def bot_panel(self):
        self._bot_action(self._do_bot_panel)

    def _bot_action(self, fn):
        """机器人按钮公共壳：后台线程执行，期间三个按钮禁用。"""
        if self._bot_busy:
            return
        self._bot_busy = True
        for btn in (self.bot_start_btn, self.bot_stop_btn, self.bot_panel_btn):
            btn.config(state=tk.DISABLED)

        def worker():
            try:
                fn()
            except Exception as e:
                self.bot_log_write(f"\n✗ 错误: {e}\n")
            finally:
                self.root.after(0, self._bot_buttons_idle)

        threading.Thread(target=worker, daemon=True).start()

    def _bot_buttons_idle(self):
        self._bot_busy = False
        for btn in (self.bot_start_btn, self.bot_stop_btn, self.bot_panel_btn):
            btn.config(state=tk.NORMAL)

    def _do_bot_start(self):
        self.bot_log_write("\n" + "─" * 46 + "\n🤖 启动机器人……\n")
        if QQBOT_STOP_FLAG.exists():
            QQBOT_STOP_FLAG.unlink()
            self.bot_log_write("已清除手动停止标志（logs\\STOPPED）\n")
        if self._napcat_running():
            self.bot_log_write("NapCat/QQ 已在运行，跳过（避免重启 QQ 触发风控）\n")
        else:
            self.bot_log_write("NapCat/QQ 未运行，经计划任务拉起（上线约需 30-60 秒）……\n")
            self._run_logged(["schtasks", "/Run", "/TN", "QQBotAutoStart"])
        if self._port_listening():
            self.bot_log_write("机器人进程已在运行（8080 监听中），跳过\n")
        else:
            self.bot_log_write("启动机器人进程（静默，输出进本面板）……\n")
            self._run_logged(["wscript.exe", str(QQBOT_SILENT_VBS)])
        self.bot_log_write("启动指令执行完毕，连接是否恢复看上方日志滚动。\n")

    def _do_bot_stop(self):
        """轻停：只停机器人 python，不动 NapCat/QQ（避免触发风控），看门狗写标志暂停。"""
        self.bot_log_write("\n" + "─" * 46 + "\n⏹ 停止机器人……\n")
        QQBOT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        QQBOT_STOP_FLAG.touch()
        self.bot_log_write("已写停止标志，看门狗不会再自动拉起\n")
        killed = self._kill_bot_pythons()
        self.bot_log_write(f"已结束 {killed} 个机器人进程；NapCat/QQ 未动。\n")

    def _do_bot_panel(self):
        """打开 qqbot 状态面板（独立控制台窗口，纯展示；关窗只收起展示，不影响机器人进程）。"""
        self.bot_log_write("\n" + "─" * 46 + "\n📊 打开机器人状态面板……\n")
        if not QQBOT_STATUS_BAT.exists():
            self.bot_log_write(f"WARN 未找到 {QQBOT_STATUS_BAT}\n")
            return
        # CREATE_NEW_CONSOLE：给 bat 开一个真正可见的新控制台
        # （hidden 父进程里用 start 弹窗不可见，必须直接给子进程新控制台）
        subprocess.Popen(
            ["cmd", "/c", str(QQBOT_STATUS_BAT)],
            cwd=str(QQBOT_DIR), creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        self.bot_log_write("已在独立窗口打开（每 5 秒刷新）。关窗只是收起展示，机器人照常运行。\n")

    # ── 进程探测/清理工具 ──

    def _run_logged(self, cmd: list[str]):
        _NO_WIN = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        try:
            r = subprocess.run(cmd, capture_output=True, creationflags=_NO_WIN)
            if r.returncode != 0:
                err = (r.stderr or b"").decode("gbk", "replace").strip()
                self.bot_log_write(f"WARN 命令返回码 {r.returncode}: {' '.join(cmd)}\n{err}\n")
        except Exception as e:
            self.bot_log_write(f"WARN 命令执行失败 {' '.join(cmd)}: {e}\n")

    def _port_listening(self, port: int = BOT_PORT) -> bool:
        """端口是否有人监听（与看门狗的 bot 存活判定一致）。"""
        _NO_WIN = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, timeout=10,
                encoding="gbk", errors="replace", creationflags=_NO_WIN,
            ).stdout
        except Exception:
            return False
        return any(f":{port}" in line and "LISTENING" in line for line in out.splitlines())

    def _napcat_running(self) -> bool:
        _NO_WIN = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq NapCatWinBootMain.exe"],
                capture_output=True, timeout=10,
                encoding="gbk", errors="replace", creationflags=_NO_WIN,
            ).stdout
        except Exception:
            return False
        return "NapCatWinBootMain" in out

    def _list_python_procs(self) -> list[tuple[str, str]]:
        """命令行含 bot.py 的 python.exe 进程：[(pid, cmdline)]，含历史残留实例。"""
        _NO_WIN = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        try:
            raw = subprocess.run(
                ["wmic", "process", "where", "name='python.exe'",
                 "get", "CommandLine,ProcessId", "/format:csv"],
                capture_output=True, timeout=15, creationflags=_NO_WIN,
            ).stdout.decode("gbk", "replace")
        except Exception:
            return []
        pairs = []
        for line in raw.splitlines():
            line = line.strip()
            cmd_part, _, pid_part = line.rpartition(",")  # csv 行尾是 PID
            if pid_part.isdigit() and "bot.py" in cmd_part:
                pairs.append((pid_part, cmd_part))
        return pairs

    def _kill_bot_pythons(self) -> int:
        """结束机器人 python：8080 监听者 + 命令行含 bot.py 的所有实例（含残留旧进程）。"""
        _NO_WIN = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        pids: set[str] = set()
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, timeout=10,
                encoding="gbk", errors="replace", creationflags=_NO_WIN,
            ).stdout
            for line in out.splitlines():
                if f":{BOT_PORT}" in line and "LISTENING" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pids.add(parts[4])
        except Exception:
            pass
        for pid, cmdline in self._list_python_procs():
            self.bot_log_write(f"命中 bot 进程 PID={pid}: {cmdline[:100]}\n")
            pids.add(pid)
        killed = 0
        for pid in pids:
            r = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", pid],
                capture_output=True, encoding="gbk", errors="replace", creationflags=_NO_WIN,
            )
            if r.returncode == 0:
                killed += 1
        return killed

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