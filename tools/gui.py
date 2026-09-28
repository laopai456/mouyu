"""GUI — TDL/煎蛋下载 + COS 上传 + QQ 机器人控制台（计数/高亮/进度条版）"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
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

# exe 放在 repo 的 dist\ 里时，.venv 和 tools\ 都在上一级（repo 根）
if (EXE_DIR / "tools").exists():
    BASE_DIR = EXE_DIR
elif (EXE_DIR.parent / "tools").exists():
    BASE_DIR = EXE_DIR.parent
else:
    BASE_DIR = EXE_DIR

VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists() and getattr(sys, 'frozen', False):
    VENV_PYTHON = EXE_DIR / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)

# 窗口标题栏图标：源码态用 repo 内 tools/icon.ico；onefile exe 态用 PyInstaller 解包目录里那份
ICON_FILE = BASE_DIR / "tools" / "icon.ico"
if not ICON_FILE.exists() and getattr(sys, 'frozen', False):
    ICON_FILE = Path(getattr(sys, "_MEIPASS", "")) / "icon.ico"

DOWNLOAD_DIR = r"C:\Users\w\Downloads\tdl"
JANDAN_DOWNLOAD_DIR = r"C:\Users\w\Downloads\jandan"
DOWNLOADER_SCRIPT = BASE_DIR / "tools" / "tdl_downloader" / "tdl_downloader_v2.py"
UPLOADER_SCRIPT = BASE_DIR / "tools" / "uploader" / "uploader.py"
JANDAN_SCRIPT = BASE_DIR / "tools" / "jandan" / "jandan_scraper.py"
CLOUD_STATS_SCRIPT = BASE_DIR / "tools" / "cloud_stats.py"
# cloud_stats.py 的结果标记行，GUI 只解析该行（stderr 可能混有 SDK 噪音）
PENDING_JSON_MARK = "CLOUD_STATS_JSON "
UPLOADER_CACHE = BASE_DIR / "tools" / "uploader" / "cache" / "md5_cache.json"
DOWNLOADER_CACHE = BASE_DIR / "tools" / "tdl_downloader" / "cache" / "md5_cache.json"
DOWNLOADER_PROGRESS = BASE_DIR / "tools" / "tdl_downloader" / "cache" / "progress_cache.json"

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

# ── 日志关键词着色（顺序即优先级：一行命中多条取更严重的）──
LOG_TAG_PATTERNS = (
    ("tag_err", re.compile(r"ERROR|FATAL|FAIL(?:ED)?|失败|✗|卡死|熔断|ABORT|not authorized", re.I)),
    ("tag_warn", re.compile(r"WARN(?:ING)?|警告|删除|重试|停滞|超时|清理", re.I)),
    ("tag_ok", re.compile(r"SUCCESS|done|完成|成功|✓|已恢复", re.I)),
    ("tag_info", re.compile(r"\bINFO\b|\bdiag\b", re.I)),
)

# ── 子进程 stdout 进度行解析规则（对应 tdl/煎蛋/uploader 的既有输出格式）──
PROGRESS_RULES = (
    (re.compile(r"已下载 (\d+) 张（预期 (\d+) 张"), "total"),        # tdl：总数已知
    (re.compile(r"第(\d+)张 done"), "count"),                        # tdl：频道逐张
    (re.compile(r"JANDAN_PROGRESS 本轮已下载(\d+)张"), "count"),      # 煎蛋：每10张
    (re.compile(r"共 (\d+) 张: 新增 (\d+), 重复 (\d+), 跳过 (\d+), 失败 (\d+)"), "upload_summary"),
    (re.compile(r"✓ \S"), "upload"),                                  # uploader：逐张成功
)
RAW_LOG_MAX_LINES = 5000  # 命令行原始输出面板保留行数上限
# 托管版后台（本地 admin.html 缺失时的回退）
ADMIN_URL = os.environ.get("MOYU_ADMIN_URL", "https://MOYU_ENV_ID_PLACEHOLDER-1414730090.tcloudbaseapp.com/admin.html")
ADMIN_DIR = BASE_DIR / "admin"
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


class ToolTip:
    """轻量悬浮提示：悬停 500ms 后出现在控件下方，移开即消失。"""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self._tip: tk.Toplevel | None = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _e=None):
        self._after_id = self.widget.after(500, self._show)

    def _show(self):
        if self._tip is not None:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._tip, text=self.text, justify=tk.LEFT,
            bg="#333333", fg="#ffffff", relief=tk.SOLID, borderwidth=1,
            font=("", 9), padx=6, pady=3,
        ).pack()

    def _hide(self, _e=None):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


# ── 计数 ──

def get_download_count() -> int:
    # TG（tdl）和煎蛋两个下载文件夹都算上
    total = 0
    for d in (DOWNLOAD_DIR, JANDAN_DOWNLOAD_DIR):
        if not os.path.exists(d):
            continue
        total += sum(
            1 for f in os.scandir(d)
            if f.is_file() and f.name.split(".")[-1].lower() in INCLUDE_TYPES
        )
    return total


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
        if ICON_FILE.exists():
            try:
                self.root.iconbitmap(str(ICON_FILE))
            except Exception:
                pass  # 图标加载失败不挡主流程（顶多退回默认图标）
        self.root.geometry("1040x660")
        self.root.minsize(880, 540)

        # 当前运行状态: None | "download" | "jandan" | "upload"
        self.current_action: str | None = None
        # 机器人按钮互斥（启/停/清理 同时只允许一个在跑）
        self._bot_busy = False
        # 机器人运行态（UI 互斥：运行中「启动」置灰；开窗时按端口探测一次，看门狗自动拉起也能识别）
        self._bot_ui_running = False
        # 日志跟随滚动开关（关掉后新日志不强制滚底，方便上滑排查旧日志）
        self._follow_var = tk.BooleanVar(value=True)
        # 任务进度：总数已知走 determinate，未知走 indeterminate
        self._progress_total: int | None = None
        self._progress_done_count = 0
        # 云端待审核数：查询去重 + 5 分钟定时刷新节拍 + 失败只告警一次
        self._pending_fetching = False
        self._pending_fail_logged = False
        self._cloud_tick = 0

        # 样式
        style = ttk.Style()
        style.theme_use("vista")
        # 运行中的停止按钮：红色加粗文字（vista 主题不认背景色，用文字色高亮）
        style.configure("Danger.TButton", foreground="#d93026", font=("", 10, "bold"))
        try:
            style.configure("TPanedwindow", sashwidth=6)  # 分割线加粗可见、好抓
        except tk.TclError:
            pass

        # ─ 顶部：左侧状态栏 + 右侧任务按钮组 ─
        info_frame = ttk.Frame(self.root, padding=12)
        info_frame.pack(fill=tk.X)

        ttk.Label(info_frame, text="📥 已下载:", font=("", 12)).pack(side=tk.LEFT, padx=(0, 4))
        self.dl_count_label = ttk.Label(info_frame, text="0", font=("", 16, "bold"), foreground="#52c41a")
        self.dl_count_label.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(info_frame, text="📤 已上传:", font=("", 12)).pack(side=tk.LEFT, padx=(0, 4))
        self.ul_count_label = ttk.Label(info_frame, text="0", font=("", 16, "bold"), foreground="#667eea")
        self.ul_count_label.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(info_frame, text="⏳ 待审核:", font=("", 12)).pack(side=tk.LEFT, padx=(0, 4))
        self.pending_count_label = ttk.Label(
            info_frame, text="…", font=("", 16, "bold"), foreground="#faad14", cursor="hand2"
        )
        self.pending_count_label.pack(side=tk.LEFT)
        # 点击数字立即刷新（云端查询较慢，不做进 5 秒本地计数轮询）
        self.pending_count_label.bind("<Button-1>", lambda e: self.refresh_pending_count())

        # 任务按钮组（右侧）：运行中三个全置灰，由独立「停止」按钮接管
        task_frame = ttk.Frame(info_frame)
        task_frame.pack(side=tk.RIGHT)

        self.dl_btn = ttk.Button(task_frame, text="⬇ TG下载", command=lambda: self.toggle_action("download"), width=12)
        self.dl_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.jd_btn = ttk.Button(task_frame, text="🥚 煎蛋下载", command=lambda: self.toggle_action("jandan"), width=12)
        self.jd_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.ul_btn = ttk.Button(task_frame, text="⬆ 统一上传", command=lambda: self.toggle_action("upload"), width=12)
        self.ul_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = ttk.Button(
            task_frame, text="⏹ 停止", command=self.stop_process,
            width=10, style="Danger.TButton", state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT)

        # ─ 第二行：左复选框 + 右机器人/辅助按钮组 ─
        ctrl_frame = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        ctrl_frame.pack(fill=tk.X)

        self.clean_cache_var = tk.BooleanVar(value=False)
        self.clean_cache_cb = ttk.Checkbutton(
            ctrl_frame, text="下载前清理缓存", variable=self.clean_cache_var
        )
        self.clean_cache_cb.pack(side=tk.LEFT)

        bot_frame = ttk.Frame(ctrl_frame)
        bot_frame.pack(side=tk.RIGHT)

        self.bot_start_btn = ttk.Button(bot_frame, text="🤖 启动机器人", command=self.bot_start, width=13)
        self.bot_start_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.bot_stop_btn = ttk.Button(bot_frame, text="⏹ 停止机器人", command=self.bot_stop, width=13)
        self.bot_stop_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.bot_panel_btn = ttk.Button(bot_frame, text="📊 打开面板", command=self.bot_panel, width=11)
        self.bot_panel_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.copy_log_btn = ttk.Button(ctrl_frame, text="📋 复制日志", command=self.copy_log, width=11)
        self.copy_log_btn.pack(side=tk.RIGHT)

        self.admin_btn = ttk.Button(ctrl_frame, text="🔍 打开审核", command=self.open_admin, width=11)
        self.admin_btn.pack(side=tk.RIGHT, padx=(0, 6))

        # ─ 日志区（左右分屏：工具日志 | 机器人日志，分割线可拖） ─
        log_frame = ttk.Frame(self.root, padding=(12, 0, 12, 4))
        log_frame.pack(fill=tk.BOTH, expand=True)

        log_paned = ttk.PanedWindow(log_frame, orient=tk.HORIZONTAL)
        log_paned.pack(fill=tk.BOTH, expand=True)

        tool_pane = ttk.Frame(log_paned)
        bot_pane = ttk.Frame(log_paned)
        log_paned.add(tool_pane, weight=1)
        log_paned.add(bot_pane, weight=1)

        # 面板标题栏：标题 + 跟随开关 + 清空/保存 小按钮
        tool_header = ttk.Frame(tool_pane)
        tool_header.pack(fill=tk.X)
        ttk.Label(tool_header, text="工具日志", font=("", 10, "bold")).pack(side=tk.LEFT)
        ttk.Checkbutton(tool_header, text="跟随", variable=self._follow_var).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(tool_header, text="清空", width=5,
                   command=lambda: self.clear_log(self.log)).pack(side=tk.RIGHT)
        ttk.Button(tool_header, text="保存", width=5,
                   command=lambda: self.save_log(self.log, "工具日志")).pack(side=tk.RIGHT, padx=(0, 4))

        self.log = scrolledtext.ScrolledText(
            tool_pane, font=("Consolas", 10), wrap=tk.WORD,
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
            state=tk.DISABLED,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        bot_header = ttk.Frame(bot_pane)
        bot_header.pack(fill=tk.X)
        ttk.Label(bot_header, text="机器人日志（qqbot/logs/bot.log）", font=("", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(bot_header, text="清空", width=5,
                   command=lambda: self.clear_log(self.botlog)).pack(side=tk.RIGHT)
        ttk.Button(bot_header, text="保存", width=5,
                   command=lambda: self.save_log(self.botlog, "机器人日志")).pack(side=tk.RIGHT, padx=(0, 4))

        self.botlog = scrolledtext.ScrolledText(
            bot_pane, font=("Consolas", 10), wrap=tk.WORD,
            bg="#1e1e1e", fg="#9cdcfe", insertbackground="white",
            state=tk.DISABLED,
        )
        self.botlog.pack(fill=tk.BOTH, expand=True)

        # 关键词着色 tag（深底配色，ERROR红/警告橙/完成绿/INFO蓝）
        for w in (self.log, self.botlog):
            w.tag_configure("tag_err", foreground="#f14c4c")
            w.tag_configure("tag_warn", foreground="#ffa657")
            w.tag_configure("tag_ok", foreground="#56d364")
            w.tag_configure("tag_info", foreground="#7aa2f7")

        # 右键菜单（复制选中/复制整行；机器人面板可打开 bot.log 源文件）
        self._attach_log_menu(self.log, source_file=None)
        self._attach_log_menu(self.botlog, source_file=QQBOT_BOT_LOG)

        # 任务进度条 + 文字（工具区底部）
        progress_frame = ttk.Frame(self.root, padding=(12, 2, 12, 0))
        progress_frame.pack(fill=tk.X)
        self.progress_label = ttk.Label(progress_frame, text="空闲")
        self.progress_label.pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        # 折叠面板：命令行原始输出（默认收起降噪音；长输出截断保留尾部）
        self._raw_visible = False
        self.raw_toggle_btn = ttk.Button(
            self.root, text="▶ 命令行原始输出", command=self.toggle_raw_output,
            width=22, takefocus=0,
        )
        self.raw_toggle_btn.pack(anchor=tk.W, padx=12, pady=(2, 2))
        self.raw_log = scrolledtext.ScrolledText(
            self.root, height=8, font=("Consolas", 9), wrap=tk.WORD,
            bg="#141414", fg="#8a8a8a", insertbackground="white",
            state=tk.DISABLED,
        )
        # 故意不 pack —— 默认收起，toggle_raw_output 里按需展开

        # 启动自检：解释器/脚本目录解析结果打进日志，路径错了第一时间可见
        self.log_write(f"解释器: {VENV_PYTHON}\n")
        self.log_write(f"脚本目录: {BASE_DIR / 'tools'}\n")
        if getattr(sys, 'frozen', False) and VENV_PYTHON == Path(sys.executable):
            self.log_write("ERROR 未找到 .venv 解释器（回退到 exe 自身），下载/上传按钮将无法运行！\n")

        # 刷新计数
        self.refresh_counts()
        self.refresh_pending_count()

        # 机器人初始运行态：8080 在监听即视为运行中（看门狗自动拉起的场景也能识别）
        self._set_bot_state(self._port_listening())

        # 按钮 hover 提示
        self._attach_tooltips()

        # 机器人日志尾随线程（不管 bot 由谁启动，tail bot.log 都能看到）
        threading.Thread(target=self._tail_bot_log, daemon=True).start()

        # 窗口关闭时清理子进程
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ── 日志写入（按关键词着色；「跟随」关掉时不强制滚底）──

    @staticmethod
    def _line_tag(line: str) -> str:
        for tag, pat in LOG_TAG_PATTERNS:
            if pat.search(line):
                return tag
        return ""

    def _insert_highlighted(self, widget: scrolledtext.ScrolledText, text: str):
        widget.config(state=tk.NORMAL)
        for line in text.splitlines(keepends=True):
            widget.insert(tk.END, line, (self._line_tag(line),))
        widget.config(state=tk.DISABLED)
        if self._follow_var.get():
            widget.see(tk.END)

    def log_write(self, text: str):
        self._insert_highlighted(self.log, text)
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
        self._cloud_tick += 1
        if self._cloud_tick >= 60:  # 云端待审核数每 5 分钟跟刷一次
            self._cloud_tick = 0
            self.refresh_pending_count()
        self.root.after(5000, self.refresh_counts)

    def refresh_pending_count(self):
        """异步刷新云端待审核数（SCF 查询约 1-2 秒，子进程跑 cloud_stats.py）。"""
        if self._pending_fetching:
            return
        if getattr(sys, 'frozen', False) and VENV_PYTHON == Path(sys.executable):
            return  # exe 无 .venv 时跑不了查询脚本（启动日志已有 ERROR 提示）
        self._pending_fetching = True

        def worker():
            pending = None
            err = None
            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                _NO_WIN = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
                r = subprocess.run(
                    [str(VENV_PYTHON), str(CLOUD_STATS_SCRIPT)],
                    capture_output=True, timeout=30, encoding="utf-8",
                    errors="replace", env=env, creationflags=_NO_WIN,
                )
                for line in reversed((r.stdout or "").splitlines()):
                    if line.startswith(PENDING_JSON_MARK):
                        data = json.loads(line[len(PENDING_JSON_MARK):])
                        if data.get("ok"):
                            pending = int(data.get("pending", 0))
                        else:
                            err = data.get("error", "未知错误")
                        break
                if pending is None and err is None:
                    err = f"无结果输出 (返回码 {r.returncode})"
            except Exception as e:
                err = str(e)

            def apply():
                self._pending_fetching = False
                if pending is not None:
                    self.pending_count_label.config(text=str(pending))
                    if self._pending_fail_logged:
                        self._pending_fail_logged = False
                        self.log_write("INFO 待审核数查询已恢复\n")
                else:
                    self.pending_count_label.config(text="-")
                    if not self._pending_fail_logged:
                        self._pending_fail_logged = True
                        self.log_write(f"WARN 待审核数查询失败: {err}\n")

            self.root.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    # ── 机器人日志面板 ──

    def bot_log_write(self, text: str):
        self._insert_highlighted(self.botlog, text)
        # 行数封顶，超出删最旧的，避免长跑撑爆内存
        lines = int(self.botlog.index("end-1c").split(".")[0])
        if lines > BOT_LOG_MAX_LINES:
            self.botlog.config(state=tk.NORMAL)
            self.botlog.delete("1.0", f"{lines - BOT_LOG_MAX_LINES}.0")
            self.botlog.config(state=tk.DISABLED)

    # ── 日志清空/保存/右键菜单 ──

    def clear_log(self, widget):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.config(state=tk.DISABLED)

    def save_log(self, widget, default_name: str):
        content = widget.get("1.0", tk.END)
        if not content.strip():
            self.toast("日志为空，无需保存", ok=False)
            return
        file = filedialog.asksaveasfilename(
            defaultextension=".log", initialfile=f"{default_name}.log",
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt")],
        )
        if not file:
            return
        try:
            Path(file).write_text(content, encoding="utf-8")
            self.toast(f"日志已保存 {Path(file).name}")
        except OSError as e:
            self.toast(f"保存失败: {e}", ok=False)

    def _attach_log_menu(self, widget, source_file: Path | None):
        menu = tk.Menu(widget, tearoff=0)
        last_pos = {"x": 0, "y": 0}

        def copy_selection():
            try:
                text = widget.get(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError:
                return
            if text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)

        def copy_line():
            idx = widget.index(f"@{last_pos['x']},{last_pos['y']}")
            line = widget.get(f"{idx} linestart", f"{idx} lineend")
            if line:
                self.root.clipboard_clear()
                self.root.clipboard_append(line + "\n")

        menu.add_command(label="复制选中内容", command=copy_selection)
        menu.add_command(label="复制整行", command=copy_line)
        if source_file is not None:
            menu.add_separator()
            menu.add_command(label="打开日志源文件",
                             command=lambda: self._open_file(source_file))

        def popup(event):
            last_pos.update(x=event.x, y=event.y)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        widget.bind("<Button-3>", popup)

    @staticmethod
    def _open_file(path: Path):
        try:
            os.startfile(path)  # Windows
        except (OSError, AttributeError):
            webbrowser.open(path.as_uri())

    # ── 轻提示 Toast（右下角，2.6 秒自动消失）──

    def toast(self, text: str, ok: bool = True):
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        bg = "#2e7d32" if ok else "#c62828"
        tk.Label(t, text=f" {text} ", padx=14, pady=8, bg=bg, fg="#ffffff",
                 font=("", 10, "bold")).pack()
        self.root.update_idletasks()
        t.update_idletasks()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        t.geometry(f"+{rx + rw - t.winfo_width() - 24}+{ry + rh - t.winfo_height() - 44}")
        t.after(2600, t.destroy)

    # ── 按钮 hover 提示 ──

    def _attach_tooltips(self):
        tips = (
            (self.dl_btn, "TG下载：从 Telegram 频道批量拉取图片"),
            (self.jd_btn, "煎蛋下载：抓取煎蛋无聊图"),
            (self.ul_btn, "统一上传：把下载文件夹图片上传云端并写库"),
            (self.stop_btn, "停止当前下载/上传任务"),
            (self.clean_cache_cb, "下载前清空 tdl/煎蛋 的缓存与去重台账"),
            (self.bot_start_btn, "启动机器人：经计划任务拉起 NapCat 与 bot 进程"),
            (self.bot_stop_btn, "停止机器人：只停 bot 进程，不动 NapCat/QQ"),
            (self.bot_panel_btn, "打开机器人状态面板（独立窗口，每5秒刷新）"),
            (self.copy_log_btn, "复制工具日志全文到剪贴板"),
            (self.admin_btn, "打开网页审核后台（本地服务，缺失时回退托管版）"),
            (self.pending_count_label, "云端待审核数量，点击立即刷新"),
        )
        for w, text in tips:
            ToolTip(w, text)

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
        self._apply_bot_mutex()

    def _set_bot_state(self, running: bool):
        """记录机器人运行态并应用按钮互斥（运行中「启动」置灰，未运行「停止」置灰）。"""
        self._bot_ui_running = running
        self._apply_bot_mutex()

    def _apply_bot_mutex(self):
        self.bot_start_btn.config(state=tk.DISABLED if self._bot_ui_running else tk.NORMAL)
        self.bot_stop_btn.config(state=tk.NORMAL if self._bot_ui_running else tk.DISABLED)

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
        self._set_bot_state(True)  # 已发起启动：按钮互斥切换（连接是否恢复看日志滚动）
        self.bot_log_write("启动指令执行完毕，连接是否恢复看上方日志滚动。\n")

    def _do_bot_stop(self):
        """轻停：只停机器人 python，不动 NapCat/QQ（避免触发风控），看门狗写标志暂停。"""
        self.bot_log_write("\n" + "─" * 46 + "\n⏹ 停止机器人……\n")
        QQBOT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        QQBOT_STOP_FLAG.touch()
        self.bot_log_write("已写停止标志，看门狗不会再自动拉起\n")
        killed = self._kill_bot_pythons()
        self.bot_log_write(f"已结束 {killed} 个机器人进程；NapCat/QQ 未动。\n")
        self._set_bot_state(False)

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
        # 运行中三个任务按钮都已置灰，理论到不了这里；兜底忽略
        if self.current_action is None:
            if action == "download":
                self.start_download()
            elif action == "jandan":
                self.start_jandan()
            else:
                self.start_upload()

    def _set_task_buttons(self, running: bool):
        """任务运行中：三个任务按钮+复选框置灰，停止按钮红色高亮；空闲恢复。"""
        state = tk.DISABLED if running else tk.NORMAL
        for btn in (self.dl_btn, self.jd_btn, self.ul_btn):
            btn.config(state=state)
        self.clean_cache_cb.config(state=state)
        self.stop_btn.config(state=tk.NORMAL if running else tk.DISABLED)

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
        if self.current_action is None:
            return
        self._kill_tree()
        self.log_write("\n⏹ 已手动停止\n")
        self._task_finish(ok=False, stopped=True)

    # ── 运行子进程 ──

    def run_subprocess(self, cmd: list[str], desc: str, action: str):
        global running_process
        self.log_write(f"{'=' * 50}\n{desc}\n{' '.join(cmd)}\n{'=' * 50}\n")
        self._raw_write(f"===== {desc}\n$ {' '.join(cmd)}\n")

        # 运行中：三个任务按钮全置灰，独立「停止」接管（红色高亮）
        self.current_action = action
        self._set_task_buttons(running=True)
        self._progress_begin(f"{desc}启动…")

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
                    self._raw_write(line)
                    self._progress_feed(line)

                p.wait()

                with process_lock:
                    if running_process == p:
                        running_process = None

                self.root.after(0, lambda: self._task_finish(ok=p.returncode == 0, desc=desc))
            except Exception as e:
                self.log_write(f"\n✗ 错误: {e}\n")
                self.root.after(0, lambda: self._task_finish(ok=False, desc=desc))
            finally:
                self.root.after(0, self._after_task_refresh)

        threading.Thread(target=worker, daemon=True).start()

    def _after_task_refresh(self):
        self.root.after(0, self.refresh_counts)
        self.root.after(0, self.refresh_pending_count)

    # ── 任务进度条 ──

    def _progress_begin(self, text: str):
        self._progress_total = None
        self._progress_done_count = 0
        self.progress_label.config(text=text)
        self.progress_bar.config(mode="indeterminate", value=0)
        self.progress_bar.start(12)

    def _progress_feed(self, line: str):
        """worker 线程里逐行调用；命中进度行后转主线程更新 UI。"""
        for pat, rule in PROGRESS_RULES:
            m = pat.search(line)
            if m:
                self.root.after(0, self._progress_update, rule, m)
                return

    def _progress_update(self, rule: str, m: re.Match):
        if rule == "total":  # tdl：已下载 N 张（预期 M 张）
            n, total = int(m.group(1)), int(m.group(2))
            self._progress_total = total
            self._progress_done_count = n
            self.progress_bar.stop()
            self.progress_bar.config(mode="determinate", maximum=max(total, 1), value=min(n, total))
            self.progress_label.config(text=f"已下载 {n} / {total} 张")
        elif rule == "count":  # tdl/煎蛋：只知道当前张数
            self._progress_done_count = int(m.group(1))
            self.progress_label.config(text=f"已下载 {m.group(1)} 张…")
        elif rule == "upload_summary":  # uploader 汇总：共 X 张: 新增 a, 重复 b, 跳过 c, 失败 d
            total, up = int(m.group(1)), int(m.group(2))
            self.progress_bar.stop()
            self.progress_bar.config(mode="determinate", maximum=max(total, 1), value=total)
            self.progress_label.config(
                text=f"扫描完成 共{total}张（新增{up} 重复{m.group(3)} 跳过{m.group(4)} 失败{m.group(5)}）"
            )
        elif rule == "upload":  # uploader：逐张 ✓
            self._progress_done_count += 1
            self.progress_label.config(text=f"已上传 {self._progress_done_count} 张…")

    def _progress_end(self, ok: bool, stopped: bool):
        self.progress_bar.stop()
        if stopped:
            self.progress_label.config(text="已停止")
        elif ok:
            self.progress_bar.config(mode="determinate", maximum=1, value=1)
            n = self._progress_done_count
            self.progress_label.config(text="完成" + (f"（{n} 张）" if n else ""))
        else:
            self.progress_label.config(text="失败")

    def _task_finish(self, ok: bool, desc: str = "", stopped: bool = False):
        """任务收尾（主线程）：按钮恢复 + 进度条定格 + Toast。"""
        self.current_action = None
        self._set_task_buttons(running=False)
        self._progress_end(ok=ok, stopped=stopped)
        if stopped:
            self.toast("任务已停止", ok=False)
        elif desc:
            self.log_write(f"\n✓ {desc}完成\n" if ok else f"\n✗ {desc}失败\n")
            self.toast(f"{'✓ ' if ok else '✗ '}{desc}{'完成' if ok else '失败'}", ok=ok)

    # ── 命令行原始输出折叠面板 ──

    def toggle_raw_output(self):
        if self._raw_visible:
            self.raw_log.pack_forget()
            self.raw_toggle_btn.config(text="▶ 命令行原始输出")
        else:
            self.raw_log.pack(fill=tk.BOTH, padx=12, pady=(0, 8))
            self.raw_toggle_btn.config(text="▼ 命令行原始输出")
        self._raw_visible = not self._raw_visible

    def _raw_write(self, line: str):
        def apply():
            self.raw_log.config(state=tk.NORMAL)
            self.raw_log.insert(tk.END, line)
            lines = int(self.raw_log.index("end-1c").split(".")[0])
            if lines > RAW_LOG_MAX_LINES:
                self.raw_log.delete("1.0", f"{lines - RAW_LOG_MAX_LINES}.0")
            self.raw_log.see(tk.END)
            self.raw_log.config(state=tk.DISABLED)
        self.root.after(0, apply)

    # ── 下载 ──

    def start_download(self):
        if self.clean_cache_var.get():
            for f in [DOWNLOADER_CACHE, DOWNLOADER_PROGRESS]:
                if f.exists():
                    f.unlink()
                    self.log_write(f"已清理: {f.name}\n")
        cmd = [str(VENV_PYTHON), str(DOWNLOADER_SCRIPT), "--auto"]
        self.run_subprocess(cmd, "下载图片", "download")

    # ── 煎蛋下载 ──

    def start_jandan(self):
        # 不带 --console-info：GUI 只出阶段/每10张进度/告警，逐张明细在 tools/jandan/logs/jandan.log
        cmd = [str(VENV_PYTHON), str(JANDAN_SCRIPT)]
        self.run_subprocess(cmd, "煎蛋下载", "jandan")

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