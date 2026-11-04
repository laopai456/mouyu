import subprocess
import json
import os
import hashlib
import queue
import random
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.stdout.reconfigure(line_buffering=True)

TDL_PATH = r"C:\tdl\tdl.exe"
PROXY = "socks5://127.0.0.1:17891"
# tdl 内部静默重连退避上限（默认 5m）：握手失败时它会悄悄重试，实测贡献了
# 20~30s 的神秘耗时。收紧到 60s 让失败更快浮出，由脚本外层统一重试
RECONNECT_TIMEOUT = "60s"

CHANNELS = {
    "woshadiao": 200,
    "shadiao_refuse": 200,
    "xinjingdaily": 300,
    "xinjingdaily_reject": 100,
    "wtmsd": 300,
    # 2026-11-04 新增批次（用户指定）：更新频率未观察，先入随机 1~2 天组，
    # 全量模式兜底 200 条；跑几轮后按实际更新量决定是否升入每日组
    "jandan_pic": 200,
    "fucku_idiot": 200,
    "rvalue_daily": 200,
    "douban_read": 200,
    "acgdaily": 200,
}

# 每频道拉取频次（防风控调度，2026-11 起随封号对策加入）：量大频道每日拉，其余
# 1~2 天随机间隔，避免固定节奏。量小频道拉得勤只是白付握手税+流量指纹，无收益。
# 调整频道分组只动这两个配置；--all-now 可临时忽略调度全拉。
CHANNEL_PULL_DAILY = {"xinjingdaily", "wtmsd"}
CHANNEL_PULL_RANDOM_DAYS = (1, 2)

# 单轮单频道的拉取时间窗（小时）：账号切换/久未运行后的积压不再一口气扫完，
# 而是每轮只拉时间窗内的量，剩余积压由后续调度轮次消化——「分几天慢慢看完」
# 的回访读者形状，避免长距离扫描+大批量下载的搬运工形状。
MAX_BATCH_HOURS = 24

# 单频道单轮下载张数截断（2026-11-05）：单频道连拉超过 N 张先转下一个频道，
# 余量留给后续调度轮——缩短单频道连续拉取时长，打散「逐群清仓」的机器形状。
# 必须配套水位=实际处理列表的 max id（见 filter_and_download），余量才不会丢。
DOWNLOAD_CAP_PER_RUN = 50

# 同一轮里相邻频道之间的随机间歇（秒）：5 个频道背靠背连跑是机器节拍，
# 散布成几十分钟的零散活动更像真人。仅影响单轮总时长，不影响结果。
CHANNEL_GAP_SECONDS = (90, 300)

DOWNLOAD_DIR = r"C:\Users\w\Downloads\tdl"
INCLUDE_TYPES = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
MIN_FILE_SIZE_KB = 20
# 下载并发线程数：Telegram 单连接吞吐有上限，慢 DC 线路（如 xinjingdaily 媒体所在
# DC）靠多连接聚合提速；太高易触发临时限速（tdl 会自动退避），8 是小文件场景平衡点
DOWNLOAD_THREADS = 8

BASE_DIR = Path(__file__).parent

# pHash 近重复过滤（2026-11-04）：64 位汉明距离阈值。8 = 抓重压缩/缩放/小水印，
# 对「同模板改字」的图（聊天截图 meme）偏保守不误杀。误杀可从隔离区回捞。
PHASH_THRESHOLD = 8
# 滚动窗口（2026-11-05 用户模型）：梗图重复集中在流行期 1~2 天，之后衰减——
# 只比对近 48h 入库的指纹，过期自动清理。库恒定几百条，也免于无限膨胀。
PHASH_WINDOW_HOURS = 48
PHASH_CACHE_FILE = BASE_DIR / "cache" / "phash_cache.json"
# 隔离区放 DOWNLOAD_DIR 之外：uploader os.walk 递归扫描，放里面会被捞走上传
DUPLICATES_DIR = r"C:\Users\w\Downloads\tdl_duplicates"
MD5_CACHE_FILE = BASE_DIR / "cache" / "md5_cache.json"
PROGRESS_CACHE_FILE = BASE_DIR / "cache" / "progress_cache.json"
DISCOVER_CACHE_FILE = BASE_DIR / "cache" / "discover_cache.json"
BAD_FILES_CACHE_FILE = BASE_DIR / "cache" / "bad_files_cache.json"

CMD_TIMEOUT = 600
NO_OUTPUT_TIMEOUT = 60
# 下载场景卡死超时：tdl 卡在某张图重试时既无输出也不写文件，缩短到 30s 快速重启
DOWNLOAD_NO_OUTPUT_TIMEOUT = 30
# 连接/初始化阶段（0 文件下载）容忍更久：tdl 连 Telegram/代理慢，避免误杀
DOWNLOAD_CONNECT_TIMEOUT = 90
MAX_STUCK_COUNT = 2
# 下载坏文件剔除最大轮数：每轮移除 tdl 卡死遗留的 .tmp 对应文件，重试剩余
MAX_BAD_FILE_ROUNDS = 3
# 下载停滞判定：目录有未完成 .tmp 且 N 秒无新文件落盘即记一次停滞。
# tdl 停滞时进度条仍在刷新 stdout，会不断重置静默计时，毒文件（连接成功
# 但 0 字节，常见于转发的他 DC 媒体）必须靠本判定兜底杀掉
DOWNLOAD_STALL_TIMEOUT = 90
# 坏文件列入黑名单阈值：累计 N 次下载失败，之后 export 直接跳过该文件
BAD_FILE_BLACKLIST_THRESHOLD = 2
# 文件数达到预期后，再等待多少秒让 tdl 自然退出，超时则强制终止
FINISH_WAIT_TIMEOUT = 30
TDL_IGNORE_PATTERNS = [
    "WARN: Export only generates",
    "Occasional suspensions",
    "CPU:",
    "Memory:",
    "Goroutines:",
    "Type: id | Input:",
]
MAX_RETRIES = 3
MD5_CHUNK_SIZE = 8192
SEQUENTIAL_GROUP_MIN = 3
DISCOVER_SAMPLE_LIMIT = 50
DISCOVER_MIN_FORWARDS = 3
ADMIN_URL = "https://MOYU_ENV_ID_PLACEHOLDER-1414730090.tcloudbaseapp.com/admin.html"


def load_json_cache(filepath: Path) -> dict:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"缓存文件损坏，将重建: {filepath} ({e})")
            return {}
    return {}


def save_json_cache(filepath: Path, data: dict) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_image(filename: str) -> bool:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext in INCLUDE_TYPES


def count_images_in_dir(directory: str) -> int:
    if not os.path.exists(directory):
        return 0
    return sum(
        1 for f in os.scandir(directory)
        if f.is_file() and is_image(f.name)
    )


def calculate_md5(file_path: str) -> str:
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(MD5_CHUNK_SIZE), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


# 剥离 ANSI 转义序列（tdl 用 [A[K 实现进度条覆盖）
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\[\d*[A-K]')


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


def _read_process_output(process: subprocess.Popen, output_lines: list, state: dict) -> None:
    try:
        for line in process.stdout:
            # 任何 stdout 输出都说明进程活着，记录时间戳
            # （含被过滤的进度条行，避免跳过重复文件时误判卡死）
            state["last_activity_time"] = time.time()
            # 先剥离 ANSI 转义序列
            line = _strip_ansi(line)
            stripped = line.strip()
            if not stripped:
                continue
            # 任何非空输出都算进程活跃（含被过滤的进度条行）：
            # tdl 跳过重复文件时不写新文件、也不输出非过滤行，但 stdout 仍有进度条
            state["last_activity_time"] = time.time()
            if any(p in stripped for p in TDL_IGNORE_PATTERNS):
                continue
            # 过滤 tdl 进度条行及 done! 行（如 "频道名 ... done! [8 in 609ms; 9/s]"）
            if 'done!' in stripped or re.search(r'\[[<#>.]+\]', stripped):
                continue
            output_lines.append(line)
            if '(' in line and ')' in line:
                parts = line.split('(')
                if len(parts) > 1:
                    state["channel_name"] = parts[0].strip()
    except (OSError, ValueError):
        pass


def _send_stdin(process: subprocess.Popen, text: str) -> None:
    try:
        process.stdin.write(text)
        process.stdin.flush()
    except (OSError, BrokenPipeError):
        pass


def _kill_tdl_processes() -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "tdl.exe"],
            capture_output=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        pass


def run_cmd(cmd: list[str], desc: str = "", target_dir: Optional[str] = None,
            expected_count: int = 0, enable_stuck_check: bool = True,
            no_output_timeout: Optional[int] = None,
            max_retries: Optional[int] = None) -> tuple[bool, bool]:
    """执行命令。

    返回 (success, stuck_terminated)：
    - success: 命令是否成功
    - stuck_terminated: 是否因「无输出卡死」被强制终止（用于上层判断要不要剔除坏文件）
    """
    print(f"\n{'=' * 50}")
    print(f"{desc}")
    print(f"{'=' * 50}")

    retries = max_retries if max_retries is not None else MAX_RETRIES
    stuck_terminated = False  # 是否因「无输出卡死」被终止

    for attempt in range(retries):
        _kill_tdl_processes()

        # 重试时清理 tdl 断点续传缓存，避免残留状态导致卡住
        if attempt > 0 and target_dir:
            for f in os.listdir(target_dir):
                if f.startswith(".tdl"):
                    try:
                        os.remove(os.path.join(target_dir, f))
                        print(f"清理 tdl 缓存: {f}")
                    except OSError:
                        pass

        # 首次下载前清理上次失败的 .tmp 残留文件
        if attempt == 0 and target_dir and os.path.isdir(target_dir):
            for f in os.listdir(target_dir):
                if f.endswith(".tmp"):
                    try:
                        os.remove(os.path.join(target_dir, f))
                        print(f"清理失败残留: {f}")
                    except OSError:
                        pass

        # tdl dl 不需要 stdin 交互，用 DEVNULL 避免意外写入导致崩溃
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        output_lines: list[str] = []
        state: dict = {"channel_name": "", "last_activity_time": time.time()}
        # 重试时不缩短超时：重试常因暂时性问题，给更多时间才对
        current_no_output_timeout = no_output_timeout or NO_OUTPUT_TIMEOUT
        start_time = time.time()
        initial_count = count_images_in_dir(target_dir) if target_dir else 0
        download_count = 0

        thread = threading.Thread(
            target=_read_process_output,
            args=(process, output_lines, state),
            daemon=True,
        )
        thread.start()

        last_output_len = 0
        last_output_time = time.time()
        last_file_count_time = time.time()
        finish_time = None  # 文件数达到预期时记录时间
        stuck_count = 0
        file_stuck_count = 0  # 文件停滞计数（独立于 stdout 静默计数）
        should_break = False

        while process.poll() is None:
            time.sleep(1)

            if target_dir:
                current_count = count_images_in_dir(target_dir)
                new_count = current_count - initial_count
                if new_count > download_count:
                    download_count = new_count
                    print(f"  {state['channel_name']}: 第{download_count}张 done")
                    last_output_time = time.time()
                    last_file_count_time = time.time()
                    stuck_count = 0
                    file_stuck_count = 0
                    # 达到预期文件数，开始倒计时等待 tdl 自然退出
                    if expected_count > 0 and download_count >= expected_count and finish_time is None:
                        print(f"已下载 {download_count} 张（预期 {expected_count} 张），等待 tdl 退出...")
                        finish_time = time.time()

            # 文件数已达标，给 tdl FINISH_WAIT_TIMEOUT 秒自然退出
            if finish_time and time.time() - finish_time > FINISH_WAIT_TIMEOUT:
                print(f"文件已全部下载，tdl 未在 {FINISH_WAIT_TIMEOUT} 秒内退出，强制终止")
                process.terminate()
                process.wait(5)
                # 下载已完成，视为成功
                return True, False

            current_len = len(output_lines)
            # 优先看进程活跃度（含被过滤的进度条行）：tdl 跳过重复文件时
            # 既不写新文件也不输出非过滤行，但 stdout 仍有进度条输出
            last_activity = state.get("last_activity_time", last_output_time)
            if current_len > last_output_len or last_activity > last_output_time:
                last_output_len = current_len
                last_output_time = max(last_output_time, last_activity)
                stuck_count = 0
            else:
                # 自适应超时：连接/初始化阶段（0 文件）给更长时间；下载中卡住则快速终止
                is_connecting = bool(target_dir and download_count == 0)
                effective_timeout = DOWNLOAD_CONNECT_TIMEOUT if is_connecting else current_no_output_timeout
                idle = time.time() - last_output_time
                if enable_stuck_check and idle > effective_timeout:
                    # 仅基于文件数增长和 stdout 输出判断是否卡住
                    phase = "连接" if is_connecting else "下载"
                    stuck_count += 1
                    print(f"\n[{phase}阶段] {effective_timeout}秒无输出，可能卡住 ({stuck_count}/{MAX_STUCK_COUNT})...")
                    last_output_time = time.time()
                    if stuck_count >= MAX_STUCK_COUNT:
                        print(f"连续{stuck_count}次卡住，终止并重启...")
                        process.terminate()
                        process.wait(5)
                        should_break = True
                        stuck_terminated = True
                        break
                elif time.time() - start_time > CMD_TIMEOUT:
                    print(f"\n总超时 ({CMD_TIMEOUT}秒)，终止命令")
                    process.terminate()
                    process.wait(5)
                    should_break = True
                    break

            # 文件停滞检测（独立于 stdout 静默）：tdl 停滞时进度条仍在刷新输出，
            # 会不断重置 stdout 活跃计时。判据：有未完成 .tmp 且停滞超时无新文件落盘
            if enable_stuck_check and target_dir and finish_time is None:
                has_tmp = any(f.endswith(".tmp") for f in os.listdir(target_dir))
                if has_tmp and time.time() - last_file_count_time > DOWNLOAD_STALL_TIMEOUT:
                    file_stuck_count += 1
                    print(f"\n[文件停滞] {DOWNLOAD_STALL_TIMEOUT}秒无新文件完成且存在 .tmp，疑似坏文件 ({file_stuck_count}/{MAX_STUCK_COUNT})...")
                    last_file_count_time = time.time()
                    if file_stuck_count >= MAX_STUCK_COUNT:
                        print("连续文件停滞，终止并剔除坏文件...")
                        process.terminate()
                        process.wait(5)
                        should_break = True
                        stuck_terminated = True
                        break
                else:
                    file_stuck_count = 0

        thread.join(5)

        if should_break:
            # 卡死/总超时终止：打印 tdl 最后输出，便于诊断（限速？连接失败？）
            if output_lines:
                tail = 15
                print(f"\n[卡死终止] tdl 最后输出 ({len(output_lines)} 行，显示最后 {min(tail, len(output_lines))} 行):")
                for line in output_lines[-tail:]:
                    print(f"  {line.strip()}")
            continue

        if output_lines:
            if process.returncode != 0:
                print(f"\n命令输出 ({len(output_lines)} 行):")
                for line in output_lines:
                    print(f"  {line.strip()}")
            else:
                tail = 10
                print(f"\n命令输出 ({len(output_lines)} 行，显示最后 {min(tail, len(output_lines))} 行):")
                for line in output_lines[-tail:]:
                    print(f"  {line.strip()}")
        elif process.returncode != 0:
            print(f"\ntdl 无任何输出就退出了 (返回码 {process.returncode})，可能代理不通或 Telegram 限速")

        if process.returncode == 0:
            return True, stuck_terminated

        if attempt < retries - 1:
            print(f"\n命令失败，返回码 {process.returncode}，重试 ({attempt + 1}/{retries})...")

    print(f"\nError: 命令执行失败，已重试 {retries} 次")
    print(f"最后命令: {' '.join(cmd)}")
    return False, stuck_terminated


def export_channel(channel: str, limit: int, output_file: str, progress_cache: dict) -> bool:
    last_id = progress_cache.get(channel, {}).get("last_id", 0)
    if last_id:
        start_id = last_id + 1
        # 积压超窗时按时间窗切分：只拉 last_time~last_time+MAX_BATCH_HOURS，
        # 防止单轮长距离扫描+大批量下载（详见 MAX_BATCH_HOURS 注释）
        last_time_str = progress_cache.get(channel, {}).get("last_time")
        window_mode = False
        try:
            last_dt = datetime.fromisoformat(last_time_str) if last_time_str else None
            if last_dt and (datetime.now() - last_dt).total_seconds() > MAX_BATCH_HOURS * 3600:
                window_end = last_dt + timedelta(hours=MAX_BATCH_HOURS)
                ts_input = f"{int(last_dt.timestamp())},{int(window_end.timestamp())}"
                window_mode = True
        except (ValueError, TypeError, OSError):
            window_mode = False  # 脏数据兜底：退回常规增量

        if window_mode:
            cmd = [TDL_PATH, "chat", "export", "-c", channel, "-o", output_file,
                   "-T", "time", "-i", ts_input, "--with-content"] + _tdl_base_args()
            desc = f"导出频道: {channel} (积压切窗模式，从 {last_dt:%m-%d %H:%M} 起 {MAX_BATCH_HOURS}h)"
        else:
            cmd = [TDL_PATH, "chat", "export", "-c", channel, "-o", output_file,
                   "-T", "id", "-i", str(start_id), "--with-content"] + _tdl_base_args()
            desc = f"导出频道: {channel} (增量模式，从消息ID {start_id} 开始)"
    else:
        cmd = [TDL_PATH, "chat", "export", "-c", channel, "-o", output_file,
               "-T", "last", "-i", str(limit), "--with-content"] + _tdl_base_args()
        desc = f"导出频道: {channel} (全量模式，最近 {limit} 条)"

    # export 期间 stdout 几乎无输出，靠 stuck check 会误报；只看总超时
    ok, _ = run_cmd(cmd, desc, enable_stuck_check=False)
    return ok


def _build_sequential_groups(file_list: list[dict]) -> set[str]:
    sequential_groups: list[list[dict]] = []
    current_group: list[dict] = []
    last_base: Optional[str] = None
    last_num: Optional[int] = None
    prev_msg: Optional[dict] = None

    for msg in file_list:
        filename = msg.get("file", "")
        name_part = filename.rsplit(".", 1)[0] if "." in filename else filename

        if name_part.isdigit():
            base, num = "", int(name_part)
        else:
            match = re.match(r"^(.+?)(\d+)$", name_part)
            if match:
                base, num = match.group(1), int(match.group(2))
            else:
                base, num = name_part, None

        is_sequential = (
            num is not None
            and last_num is not None
            and base == last_base
            and num == last_num + 1
        )

        if is_sequential:
            if not current_group and prev_msg:
                current_group.append(prev_msg)
            current_group.append(msg)
        else:
            if len(current_group) >= SEQUENTIAL_GROUP_MIN:
                sequential_groups.append(current_group)
            current_group = []

        prev_msg = msg
        last_base = base
        last_num = num

    if len(current_group) >= SEQUENTIAL_GROUP_MIN:
        sequential_groups.append(current_group)

    result: set[str] = set()
    for group in sequential_groups:
        for msg in group:
            result.add(msg.get("file"))
    return result


def _deduplicate_new_files(
    target_dir: str, new_filenames: list[str],
    md5_cache: dict, channel: str,
    phash_cache: dict, phash_ints: list,
) -> tuple[int, int]:
    downloaded = 0
    skipped = 0

    # 构建 size -> [md5] 索引，用于快速预筛
    # 原理：文件相同 -> size 必相同；故 size 不同 -> 必不重复，可跳过 MD5 计算
    # （老缓存记录可能缺 size 字段，此处跳过它们，按旧逻辑算 MD5 兜底）
    size_index: dict[int, set[str]] = {}
    for cached_md5, info in md5_cache.items():
        sz = info.get("size")
        if sz is not None:
            size_index.setdefault(sz, set()).add(cached_md5)

    for filename in new_filenames:
        if not is_image(filename):
            continue

        file_path = os.path.join(target_dir, filename)
        try:
            file_size = os.path.getsize(file_path)
            file_size_kb = file_size / 1024
            if file_size_kb < MIN_FILE_SIZE_KB:
                print(f"图片太小({file_size_kb:.0f}KB)，删除: {filename}")
                os.remove(file_path)
                continue

            # size 预筛：该 size 在缓存中从未出现 -> 必为新图，免算 MD5
            candidate_md5s = size_index.get(file_size)
            if not candidate_md5s:
                md5 = calculate_md5(file_path)
                md5_cache[md5] = {
                    "channel": channel,
                    "filename": filename,
                    "size": file_size,
                    "time": datetime.now().isoformat(),
                }
                size_index.setdefault(file_size, set()).add(md5)
                downloaded += 1
                continue

            # size 命中候选 -> 算 MD5 确认是否真重复
            md5 = calculate_md5(file_path)
            if md5 in candidate_md5s:
                print(f"重复图片，删除: {filename}")
                os.remove(file_path)
                skipped += 1
            else:
                # pHash 近重复门：字节不同但视觉相同的图（重压缩/缩放/水印版）在此拦截
                if _phash_dedup_gate(file_path, filename, channel, phash_cache, phash_ints):
                    skipped += 1
                    continue
                md5_cache[md5] = {
                    "channel": channel,
                    "filename": filename,
                    "size": file_size,
                    "time": datetime.now().isoformat(),
                }
                size_index.setdefault(file_size, set()).add(md5)
                downloaded += 1
        except OSError as e:
            print(f"处理失败 {filename}: {e}")

    return downloaded, skipped


_TDL_NAME_PREFIX_RE = re.compile(r"^\d+_\d+_")


# ── pHash 近重复过滤（2026-11-04）：MD5 只认字节，TG 客户端发图默认压缩，
# 同一张梗图经手 N 人就有 N 个字节版本 → 字节级去重抓不住视觉重复。
# pHash 对压缩/缩放/水印稳健，Hamming 距离 ≤ 阈值判近重复。
# 库只增不清（防旧梗隔月被其他频道重发）；历史 2 万张字节已随上传删除，
# 无法回填，库自今日前向积累——头几个月内与历史图的重复仍会漏，如实告知。
# 隔离区放 DOWNLOAD_DIR 之外：uploader os.walk 递归扫描，放里面会被捞走上传。
def _load_phash_cache() -> dict:
    if os.path.exists(PHASH_CACHE_FILE):
        try:
            with open(PHASH_CACHE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # 滚动窗口：只留近 PHASH_WINDOW_HOURS 的指纹，流行期外的重复按衰减模型放弃
            cutoff = datetime.now() - timedelta(hours=PHASH_WINDOW_HOURS)
            fresh = {}
            for h, v in raw.items():
                try:
                    if datetime.fromisoformat(v.get("time", "")) >= cutoff:
                        fresh[h] = v
                except (ValueError, TypeError):
                    pass  # 脏记录直接丢弃
            return fresh
        except (OSError, json.JSONDecodeError) as e:
            print(f"⚠ pHash 缓存损坏，重建: {e}")
    return {}


def _save_phash_cache(cache: dict) -> None:
    os.makedirs(PHASH_CACHE_FILE.parent, exist_ok=True)
    with open(PHASH_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def _phash_ints(cache: dict) -> list[tuple[str, int]]:
    return [(h, int(h, 16)) for h in cache]


def _phash_of(path: str) -> Optional[int]:
    try:
        import imagehash
        from PIL import Image
        with Image.open(path) as im:
            return int(str(imagehash.phash(im)), 16)
    except Exception as e:
        print(f"⚠ pHash 计算失败({os.path.basename(path)}): {e}")
        return None


def _phash_match(ph: int, cache: dict, ints: list[tuple[str, int]]):
    best_h, best_d = None, 65
    for h, v in ints:
        d = (ph ^ v).bit_count()
        if d < best_d:
            best_h, best_d = h, d
    if best_d <= PHASH_THRESHOLD:
        return best_h, best_d
    return None


def _phash_dedup_gate(file_path: str, filename: str, channel: str,
                      phash_cache: dict, phash_ints: list) -> bool:
    """近重复=True（文件已移入隔离区）；新图=False（hash 已入库）。"""
    ph = _phash_of(file_path)
    if ph is None:
        return False
    hit = _phash_match(ph, phash_cache, phash_ints)
    if hit:
        h, d = hit
        print(f"近重复(pHash距离{d}≤{PHASH_THRESHOLD})，隔离不上传: {filename}")
        print(f"    └ 与库内 {phash_cache[h].get('channel','?')}/{phash_cache[h].get('file','?')} 相似")
        os.makedirs(DUPLICATES_DIR, exist_ok=True)
        try:
            shutil.move(file_path, os.path.join(DUPLICATES_DIR, filename))
        except (OSError, shutil.Error) as e:
            print(f"⚠ 隔离移动失败(保留原图): {e}")
        return True
    phash_cache[f"{ph:016x}"] = {"file": filename, "channel": channel,
                                 "time": datetime.now().isoformat()}
    phash_ints.append((f"{ph:016x}", ph))
    return False


def _strip_tdl_name_prefix(filename: str) -> str:
    """剥掉 tdl 落盘自动加的 <dialog_id>_<msg_id>_ 前缀，还原为 export 的 file 字段名。

    export 的 file 字段是裸 unique_id（如 6123176226865222252.jpg），而 tdl dl
    实际保存为 1434817225_319102_6123176226865222252.jpg，比对前必须归一化。
    """
    return _TDL_NAME_PREFIX_RE.sub("", filename, count=1)


def filter_and_download(
    export_file: str, download_dir: str, channel: str, limit: int,
    md5_cache: dict, progress_cache: dict, bad_cache: dict
) -> None:
    if not os.path.exists(export_file):
        print(f"导出文件不存在: {export_file}")
        return

    with open(export_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    print(f"获取消息数: {len(messages)}")

    file_list = [
        msg for msg in messages
        if msg.get("file") and is_image(msg["file"])
    ]
    print(f"图片消息数: {len(file_list)}")

    if not file_list:
        print("没有找到图片")
        return

    sequential_files = _build_sequential_groups(file_list)
    filtered = [msg for msg in file_list if msg.get("file") not in sequential_files]
    print(f"过滤后图片数: {len(filtered)} (跳过连续漫画: {len(sequential_files)} 张)")

    if len(filtered) > limit:
        print(f"限制下载数量: {len(filtered)} → {limit} 张")
        filtered = filtered[:limit]

    # 黑名单剔除：失败达阈值的坏文件（如转发的 0 字节毒文件）直接跳过，
    # 否则每次 export 都会把它们加回来，整批永远差一张、进度推不动
    before_black = len(filtered)
    filtered = [m for m in filtered
                if bad_cache.get(m.get("file", ""), {}).get("count", 0) < BAD_FILE_BLACKLIST_THRESHOLD]
    if len(filtered) < before_black:
        print(f"黑名单剔除坏文件 {before_black - len(filtered)} 张（失败≥{BAD_FILE_BLACKLIST_THRESHOLD}次，永久跳过）")

    # 单频道单轮截断：超出的余量留给后续调度轮（水位配套改造，见 max_id 处）
    if len(filtered) > DOWNLOAD_CAP_PER_RUN:
        print(f"单轮截断: {len(filtered)} → {DOWNLOAD_CAP_PER_RUN} 张（余量下轮继续）")
        filtered = filtered[:DOWNLOAD_CAP_PER_RUN]

    if not filtered:
        print("没有找到图片")
        return

    filtered_file = str(Path(export_file).with_suffix(".filtered.json"))
    if os.path.exists(filtered_file):
        os.remove(filtered_file)
        print(f"清理残留文件: {filtered_file}")
    with open(filtered_file, "w", encoding="utf-8") as f:
        json.dump({"id": data["id"], "messages": filtered}, f, ensure_ascii=False, indent=2)

    os.makedirs(download_dir, exist_ok=True)

    cached_files = set(os.listdir(download_dir)) if os.path.exists(download_dir) else set()
    # tdl 落盘名带 <dialog_id>_<msg_id>_ 前缀，归一化后才能与 export 的 file 字段比对
    cached_basenames = {_strip_tdl_name_prefix(f) for f in cached_files}
    print(f"目录已有 {len(cached_files)} 个文件")

    # 检查已存在的文件是否已覆盖所有待下载图片
    pending_filenames = {msg.get("file") for msg in filtered if msg.get("file")}
    already_exist = pending_filenames & cached_basenames
    if already_exist and len(already_exist) == len(pending_filenames):
        print(f"所有 {len(pending_filenames)} 张图片已存在于目录中（tdl 将跳过重复文件）")
    else:
        if already_exist:
            print(f"其中 {len(already_exist)} 张已存在，需下载 {len(pending_filenames) - len(already_exist)} 张")

    # --continue 容易因残留 .tdl 缓存导致卡住，去掉
    # 并发用 DOWNLOAD_THREADS（原 2 太保守：单连接吞吐被封顶，慢 DC 频道下载极慢）
    need_download_count = len(pending_filenames) - len(already_exist)

    dl_ok = False
    # 坏文件剔除循环：tdl 卡在某文件死重试时，识别遗留的 .tmp，
    # 把对应文件从列表剔除后重试，避免因单个坏文件卡死整个频道
    for bad_round in range(MAX_BAD_FILE_ROUNDS):
        cmd = [TDL_PATH, "dl", "-f", filtered_file, "-d", download_dir,
               "--skip-same", "-t", str(DOWNLOAD_THREADS)] + _tdl_base_args()
        # 下载只重试 1 次：同列表重试坏文件无意义，靠外层剔除坏文件
        ok, stuck = run_cmd(
            cmd, f"下载 {channel} 的 {len(filtered)} 张图片到 {download_dir}",
            target_dir=download_dir, expected_count=need_download_count,
            no_output_timeout=DOWNLOAD_NO_OUTPUT_TIMEOUT, max_retries=1,
        )
        dl_ok = dl_ok or ok
        if ok or not stuck:
            break

        # 卡死终止：扫描 .tmp 残留，剔除对应文件后进入下一轮
        bad_files = {f[:-4] for f in os.listdir(download_dir)
                     if f.endswith(".tmp")} if os.path.isdir(download_dir) else set()
        if not bad_files:
            print("卡死但未发现 .tmp 残留，无法定位坏文件，放弃")
            break
        print(f"⚠ 检测到坏文件 {len(bad_files)} 个，从列表剔除后重试: {sorted(bad_files)}")
        # 记录坏文件失败次数，达到阈值进黑名单，后续运行 export 后直接跳过
        now_iso = datetime.now().isoformat()
        for disk_name in bad_files:
            bare = _strip_tdl_name_prefix(disk_name)
            entry = bad_cache.setdefault(bare, {"count": 0})
            entry["count"] += 1
            entry["channel"] = channel
            entry["last_time"] = now_iso
        save_json_cache(BAD_FILES_CACHE_FILE, bad_cache)
        blacklisted = sorted({n for n in bad_files
                              if bad_cache[_strip_tdl_name_prefix(n)]["count"] >= BAD_FILE_BLACKLIST_THRESHOLD})
        if blacklisted:
            print(f"⚠ 坏文件已列入黑名单（后续运行跳过）: {blacklisted}")
        filtered = [m for m in filtered if m.get("file") not in bad_files]
        if not filtered:
            print("剔除坏文件后无待下载图片，跳过")
            break
        # 重写 filtered.json，并更新 need_download_count
        with open(filtered_file, "w", encoding="utf-8") as f:
            json.dump({"id": data["id"], "messages": filtered}, f, ensure_ascii=False, indent=2)
        pending_filenames = {m.get("file") for m in filtered if m.get("file")}
        need_download_count = len(pending_filenames - cached_basenames)

    if not dl_ok:
        print(f"⚠ 下载命令执行失败，可能部分或全部图片未下载成功")

    new_files = [
        f for f in os.listdir(download_dir)
        if os.path.isfile(os.path.join(download_dir, f)) and f not in cached_files
    ]

    # pHash 近重复过滤：跨 batch 复用同一份缓存（本批内即插即比），批末落盘
    phash_cache = _load_phash_cache()
    phash_ints = _phash_ints(phash_cache)
    before_phash = len(phash_ints)

    downloaded, skipped = _deduplicate_new_files(download_dir, new_files, md5_cache, channel,
                                                 phash_cache, phash_ints)
    if len(phash_ints) != before_phash:
        _save_phash_cache(phash_cache)
        print(f"pHash 库已更新: {before_phash} → {len(phash_ints)} 条")
    save_json_cache(MD5_CACHE_FILE, md5_cache)

    if downloaded == 0 and skipped == 0:
        if not dl_ok:
            print(f"下载失败: 命令执行出错，请检查上方日志")
        elif already_exist and len(already_exist) == len(pending_filenames):
            print(f"下载完成: 所有图片均已存在，无需下载")
        else:
            print(f"下载完成: 无新增图片 (可能是 tdl --skip-same 跳过了已存在的文件)")
    else:
        print(f"下载完成: 新增 {downloaded} 张, 跳过重复 {skipped} 张")

    # 水位=本轮实际处理列表(filtered，含截断/黑名单剔除后)的 max id，而非整批
    # 导出的 max——单轮截断时余量保持在水位之下，下轮增量自然续上，不会丢图
    max_id = max(
        (m.get("id", 0) for m in filtered if isinstance(m.get("id", int), int)),
        default=0,
    )
    if max_id > 0:
        if dl_ok:
            progress_cache[channel] = {
                "last_id": max_id,
                "last_time": datetime.now().isoformat(),
            }
            # 防风控调度：导出+下载都成功才写下轮到期日；失败则下轮立即重试本频道
            mark_pulled(progress_cache, channel)
            save_json_cache(PROGRESS_CACHE_FILE, progress_cache)
            print(f"已记录进度: 频道 {channel} 最后消息ID: {max_id}")
        else:
            # 下载失败不推进进度，避免没下成的文件被永久跳过（下次重试）
            print(f"⚠ 下载未成功，保留旧进度（不推进到 {max_id}），下次将重试本批")
    else:
        # 无新消息：导出往返已成功，同样写到期日——否则沉默频道每轮都到期，
        # 天天被重复导出，分频调度对它们形同虚设
        mark_pulled(progress_cache, channel)
        save_json_cache(PROGRESS_CACHE_FILE, progress_cache)

    if os.path.exists(filtered_file):
        os.remove(filtered_file)


def probe_proxy_port(timeout: float = 2.0) -> bool:
    """快速探测本地代理端口是否可连。

    用于区分两类失败：代理客户端没开（端口不可达，重试无意义）
    vs 节点/到 Telegram 链路慢（端口可达，重试可能恢复）。
    """
    parsed = urlparse(PROXY)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 1080
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _socks5_e2e_probe(timeout: float = 8.0) -> bool:
    """端到端探测：经 SOCKS5 代理对 Telegram DC 边缘建 TCP（stdlib 裸握手）。

    成功说明「本地端口→节点→Telegram」整条链路通（顺带预热代理客户端的
    节点连接，tdl 随后的 MTProto 握手更快）；失败说明节点或其到 TG 的线路
    不通，此时跑 tdl 只会干等到超时。tg_ip 用 Telegram DC2 边缘 IP 免本地 DNS。
    """
    parsed = urlparse(PROXY)
    proxy_host = parsed.hostname or "127.0.0.1"
    proxy_port = parsed.port or 1080
    tg_ip, tg_port = "149.154.167.51", 443
    try:
        with socket.create_connection((proxy_host, proxy_port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(b"\x05\x01\x00")  # SOCKS5 握手：无认证
            if s.recv(2) != b"\x05\x00":
                return False
            # CONNECT tg_ip:443（ATYP=1 IPv4）
            s.sendall(b"\x05\x01\x00\x01" + socket.inet_aton(tg_ip) + tg_port.to_bytes(2, "big"))
            resp = s.recv(32)
            return len(resp) >= 4 and resp[1] == 0
    except OSError:
        return False


def _tdl_base_args() -> list[str]:
    """所有 tdl 调用的公共参数：代理 + 内部重连退避上限 + 防风控降强度。

    每个 tdl 进程都要付一次 MTProto 握手税（实测 1.5~30s 波动），公共参数
    收敛到这里统一管理。
    降强度（2026-11 起频繁封号后加）：串行任务 -l 1、单线程 -t 1、任务间
    延迟 500ms、DC 连接池收窄 --pool 2——拉低「高并发爬虫」流量指纹。
    代价：批量下载变慢（千张图约多 8 分钟），远低于换号成本。
    """
    return [
        "--proxy", PROXY, "--reconnect-timeout", RECONNECT_TIMEOUT,
        "--limit", "1", "--threads", "1", "--delay", "500ms", "--pool", "2",
    ]


# 与 tdl 共用会话密钥的官方客户端（desktop 导入模式）：拉取期间并行运行 =
# 同一 auth key 上双客户端指纹并存（软异常信号，老号实测能活但白扣分）。
# 启动拉取前自动检测提醒；--close-desktop 自动结束它（会话密钥早已拷贝，
# tdl 不依赖 Desktop 运行，中途退出无副作用）。
SHARED_KEY_CLIENTS = ("Telegram.exe",)


def check_shared_key_clients(auto_close: bool = False) -> None:
    for client in SHARED_KEY_CLIENTS:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {client}"],
            capture_output=True, text=True,
        ).stdout
        if client.lower() not in out.lower():
            continue
        if auto_close:
            subprocess.run(["taskkill", "/F", "/IM", client], capture_output=True)
            print(f"[共钥检查] 已自动结束 {client}（--close-desktop）：避免拉取期间同 key 双客户端指纹并存")
        else:
            print(f"\n[共钥检查] ⚠ 检测到 {client} 正在运行：它和 tdl 共用同一把会话密钥，"
                  f"拉取期间并存 = 双客户端指纹（软扣分项，建议避免）。")
            print("          建议：托盘退出后重跑；或下次直接用 --close-desktop 自动结束（不影响拉取）。")


def due_channels(progress_cache: dict, force_all: bool = False) -> list[str]:
    """防风控频次调度：筛出本轮该拉的频道。

    progress_cache 每频道记 next_pull（ISO 日期）；无记录/解析失败视为到期，
    新频道或脏数据不会饿死。force_all 忽略调度全部立即拉（--all-now）。
    """
    if force_all:
        return list(CHANNELS)
    today = date.today()
    due = []
    for ch in CHANNELS:
        np = progress_cache.get(ch, {}).get("next_pull")
        try:
            need = not np or today >= date.fromisoformat(np)
        except ValueError:
            need = True
        if need:
            due.append(ch)
    return due


def mark_pulled(progress_cache: dict, channel: str) -> None:
    """拉取成功后写下轮到期日：量大频道次日，其余 1~2 天随机。"""
    if channel in CHANNEL_PULL_DAILY:
        interval = 1
    else:
        interval = random.randint(*CHANNEL_PULL_RANDOM_DAYS)
    progress_cache.setdefault(channel, {})["next_pull"] = (
        date.today() + timedelta(days=interval)
    ).isoformat()


def check_tdl_login() -> str:
    """检查 tdl 登录状态，返回三态：
    - "ok"：已登录
    - "not_authorized"：明确未登录（输出含 not authorized / please login），
      此时可安全自动重登——旧会话已失效，desktop 导入覆盖它无损失
    - "failed"：代理客户端没开 / 节点不通 / 限速抖动，绝不触发自动重登
      （否则可能把还活着的会话覆盖掉）

    用 chat ls（只列对话列表，不拉内容）替代 chat export --with-content，
    避免内容下载限速被误判为未登录。探测细节：
    - 节点到 Telegram 不通（端到端探测失败）：跳过 tdl 干等，等恢复再查
    - 链路通但 tdl 冷启动握手慢：递增超时重试（探测顺带预热代理链路）
    """
    max_retries = 3
    timeouts = [30, 60, 90]  # 递增：实测 chat ls 冷启动可达 ~27s（裸隧道瞬时通也一样），30s 保底一刀过
    last_e2e_ok: Optional[bool] = None
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            print("  等待 5 秒后重试...")
            time.sleep(5)
        timeout = timeouts[attempt - 1]
        print(f"  正在检查 tdl 登录状态（{attempt}/{max_retries}，超时 {timeout} 秒）...")
        try:
            if not probe_proxy_port():
                print(f"  -> 本地代理端口不可达（{PROXY}），代理客户端可能未运行")
                print(f"  -> 请先启动代理客户端，再重新运行脚本")
                return "failed"
            if last_e2e_ok is False:
                # 上一轮已确认节点不通：先探测，恢复了才值得跑 tdl（否则只是干等超时）
                last_e2e_ok = _socks5_e2e_probe()
                if not last_e2e_ok:
                    print("  ⚠ 节点到 Telegram 仍不通，跳过本轮 tdl 检查")
                    continue
                print("  ✓ 节点已恢复连通（已顺带预热代理链路）")
            start = time.time()
            result = subprocess.run(
                [TDL_PATH, "chat", "ls"] + _tdl_base_args(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            elapsed = time.time() - start
            if result.returncode == 0:
                print(f"✓ tdl 已登录（耗时 {elapsed:.1f}s）")
                return "ok"

            # 返回非 0：区分"未登录"和"其它失败"
            combined = (result.stdout + result.stderr).strip()
            combined_lower = combined.lower()
            if "not authorized" in combined_lower or "please login" in combined_lower:
                print(f"✗ tdl 未登录（耗时 {elapsed:.1f}s）")
                if combined:
                    for line in combined.splitlines():
                        line = line.strip()
                        if line and not any(p in line for p in TDL_IGNORE_PATTERNS):
                            print(f"  {line}")
                print("  -> 请登录: tdl login --proxy socks5://127.0.0.1:17891")
                return "not_authorized"

            # 其它失败（限速/网络抖动）：重试，不判未登录
            print(f"⚠ 连接异常（耗时 {elapsed:.1f}s，返回码 {result.returncode}），可能是限速或网络抖动")
            if combined:
                for line in combined.splitlines()[:3]:
                    line = line.strip()
                    if line and not any(p in line for p in TDL_IGNORE_PATTERNS):
                        print(f"  {line}")
        except subprocess.TimeoutExpired:
            print(f"⚠ 检查登录超时（{timeout} 秒）")
            if not probe_proxy_port():
                print(f"  -> 本地代理端口不可达（{PROXY}），代理客户端可能未运行")
                print(f"  -> 请先启动代理客户端，再重新运行脚本")
                return "failed"
            last_e2e_ok = _socks5_e2e_probe()
            if last_e2e_ok:
                print("  -> 代理链路端到端连通（已顺带预热），应是 tdl 冷启动握手慢，下一轮加长超时")
            else:
                print("  -> 节点到 Telegram 不通，下一轮先等恢复再检查")
        except Exception as e:
            print(f"✗ 检查登录状态失败: {e}")
            return "failed"

    if last_e2e_ok is False:
        print(f"  -> 重试 {max_retries} 次节点均到不了 Telegram，临时故障，稍后重试或更换节点")
    else:
        print(f"  -> 重试 {max_retries} 次仍失败，可稍后重试或直接运行下载观察")
    print(f"  -> 这不代表未登录（登录态存在本地）")
    return "failed"


# Telegram Desktop 主账户数据文件：gotd 按 key_datas 内的账户索引解密 data 系列
# 文件（data 的哈希名即 D877F783D5D3EF8C），缺任何一个都会导入报错
TG_MAIN_ACCOUNT_KEYS = ("key_datas", "D877F783D5D3EF8Cs", "D877F783D5D3EF8C")


def _find_winpty() -> Optional[str]:
    """定位 Git 自带的 winpty.exe（伪终端，用于自动应答 tdl 的交互菜单）。"""
    found = shutil.which("winpty")
    if found:
        return found
    for cand in (r"C:\Program Files\Git\usr\bin\winpty.exe",
                 r"C:\Program Files (x86)\Git\usr\bin\winpty.exe"):
        if os.path.exists(cand):
            return cand
    return None


def _auto_desktop_login() -> bool:
    """全自动 desktop 登录：嫁接最小 tdata + winpty 伪终端自动应答 tdl 菜单。

    tdl 0.20.1 的 desktop 导入会无条件弹账户选择菜单（survey 库，需要真终端），
    非交互环境直接报 Incorrect function。绕法分两步：
    1. 只拷 key_datas + 主账户 data 文件到临时 tdata（-d 指临时父目录，tdl 会
       自动拼 tdata 子目录），排除真实 tdata 里历史残留账户的干扰
    2. winpty -Xallow-non-tty 把管道输入转进伪终端：见菜单发回车选唯一账户，
       见导入成功即收手——后续「是否登出桌面端」确认保持默认否（不登出用户
       的 Telegram Desktop），且 winpty 在该确认步有 assert 崩溃的已知问题，
       导入落库后进程怎么退出都不影响结果
    """
    winpty = _find_winpty()
    if not winpty:
        print("✗ 未找到 winpty（Git 自带），无法自动应答 tdl 交互菜单")
        return False
    tdata = os.path.join(os.environ.get("APPDATA", ""), "Telegram Desktop", "tdata")
    if not os.path.isdir(tdata):
        print(f"✗ 未找到 Telegram Desktop 会话目录: {tdata}")
        return False

    tmp_root = tempfile.mkdtemp(prefix="tdl_login_")
    tmp_tdata = os.path.join(tmp_root, "tdata")
    os.makedirs(tmp_tdata)
    try:
        for name in TG_MAIN_ACCOUNT_KEYS:
            src = os.path.join(tdata, name)
            dst = os.path.join(tmp_tdata, name)
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            except OSError as e:
                print(f"✗ 嫁接临时 tdata 失败（{name}）: {e}")
                return False

        cmd = [winpty, "-Xallow-non-tty", TDL_PATH, "login", "-T", "desktop",
               "-d", tmp_root, "--proxy", PROXY]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as e:
            print(f"✗ 启动自动登录进程失败: {e}")
            return False
        return _feed_tdl_login_menu(proc)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _feed_tdl_login_menu(proc: subprocess.Popen) -> bool:
    """监视 tdl 登录输出，在账户菜单出现时自动发回车。返回是否导入成功。

    winpty 输出经管道逐字节读入（Windows 管道无超时读，用读线程 + 队列，
    主线程带总超时轮询），关键词触发写 stdin。
    """
    out_q: "queue.Queue[bytes]" = queue.Queue()

    def _reader() -> None:
        try:
            while True:
                byte = proc.stdout.read(1)
                if not byte:
                    break
                out_q.put(byte)
        except OSError:
            pass
        out_q.put(b"")  # EOF 哨兵

    threading.Thread(target=_reader, daemon=True).start()

    deadline = time.time() + 90
    buf = b""
    sent_user = False
    imported = False
    while time.time() < deadline:
        try:
            chunk = out_q.get(timeout=1.0)
        except queue.Empty:
            continue
        if not chunk:
            break  # 进程已退出
        buf += chunk
        text = buf.decode("utf-8", errors="replace")
        if not sent_user and "Choose a user id" in text:
            proc.stdin.write(b"\r")
            proc.stdin.flush()
            sent_user = True
            print("  -> 已自动选择账户")
        elif sent_user and "successfully" in text:
            imported = True
            print("  -> 会话导入成功")
            try:
                proc.stdin.close()  # 不再应答，登出确认走默认否
            except OSError:
                pass
            break
    if not imported:
        proc.kill()
        proc.wait(timeout=10)
        tail = buf.decode("utf-8", errors="replace").replace("\r", "").strip()[-400:]
        print(f"✗ 自动登录未完成（超时或失败），输出尾部:\n{tail}")
        return False
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()  # tdl 卡在登出确认收不到输入，杀掉即可，导入已落库
    return True


def tdl_login(login_type: str = "desktop") -> bool:
    """调起 tdl 登录。login_type: desktop / code / qr。

    desktop 方式先走全自动（读取本机 Telegram Desktop 的 tdata 导入会话，
    winpty 自动应答菜单）；自动方式不可用时退回交互式（继承终端，需手动
    按回车选账户）。code / qr 必须人工参与（验证码 / 扫码），直接交互式。
    完成后统一验证登录状态。
    """
    if login_type not in ("desktop", "code", "qr"):
        print(f"✗ 不支持的登录方式: {login_type}（可选 desktop / code / qr）")
        return False

    print("登录前清理残留 tdl 进程（避免数据库锁冲突）...")
    _kill_tdl_processes()

    if login_type == "desktop":
        print("\n尝试全自动 desktop 登录（读取本机 Telegram Desktop 会话）...")
        print("提示: 登录会覆盖 default namespace 的现有会话")
        if _auto_desktop_login():
            _kill_tdl_processes()
            print("\n验证登录状态...")
            return check_tdl_login() == "ok"
        print("-> 全自动登录未成功，退回交互式登录（按提示回车/输入）")

    print(f"\n启动 tdl 交互式登录（方式: {login_type}）...")
    cmd = [TDL_PATH, "login", "-T", login_type, "--proxy", PROXY]
    try:
        # 交互式登录，继承当前终端的 stdin/stdout
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"✗ 登录命令返回码 {result.returncode}")
            return False
    except KeyboardInterrupt:
        print("\n用户中断登录")
        return False

    # 登录后清理可能的残留进程，再验证
    _kill_tdl_processes()
    print("\n验证登录状态...")
    return check_tdl_login() == "ok"


def check_channels() -> None:
    """对比 CHANNELS 配置和 chat ls 结果，列出已加入/未加入的频道。

    实测（2026-09 换新号后仅加入 1/5 个频道）：公开频道不加入也能 chat export
    拉全量历史下载（同 t.me 网页预览机制，MTProto 允许非成员读公开频道历史）。
    加群非必需，只为频道万一转私/改用户名时不失联；私有频道才必须加入。
    tdl 无 join 命令，未加入频道只输出 t.me 链接供手动添加（可选）。
    """
    print("获取当前账号已加入的对话列表...")
    _kill_tdl_processes()
    try:
        result = subprocess.run(
            [TDL_PATH, "chat", "ls", "-o", "json"] + _tdl_base_args(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("✗ 获取对话列表超时")
        return

    if result.returncode != 0:
        combined = (result.stdout + result.stderr).strip()
        print(f"✗ 获取失败（返回码 {result.returncode}）")
        for line in combined.splitlines()[:5]:
            line = line.strip()
            if line:
                print(f"  {line}")
        if "not authorized" in combined.lower() or "please login" in combined.lower():
            print("  -> 未登录，请先运行: python tdl_downloader_v2.py --login")
        elif "another process" in combined.lower():
            print("  -> 数据库被占用，请关闭其它 tdl 进程后重试")
        return

    # 解析 JSON 输出（比表格解析稳，避免 VisibleName 含空格导致列错位）
    joined_usernames: set[str] = set()
    try:
        chats = json.loads(result.stdout) if result.stdout.strip() else []
        for chat in chats:
            username = chat.get("username") or ""
            username = username.lstrip("@").strip()
            if username:
                joined_usernames.add(username)
    except json.JSONDecodeError as e:
        print(f"✗ 解析对话列表失败: {e}")
        print(f"原始输出前200字符: {(result.stdout or '')[:200]}")
        return

    print(f"\n{'=' * 50}")
    print(f"频道加群状态检查")
    print(f"{'=' * 50}")
    joined: list[str] = []
    missing: list[str] = []
    for channel in CHANNELS:
        if channel in joined_usernames:
            joined.append(channel)
        else:
            missing.append(channel)

    print(f"\n✓ 已加入 ({len(joined)}/{len(CHANNELS)}):")
    for c in joined:
        print(f"  @{c}")

    if missing:
        print(f"\n○ 未加入 ({len(missing)})（公开频道不加也能正常下载）:")
        print("  tdl 无自动加群命令；加群仅为防频道转私后失联，如需加入请点:")
        for c in missing:
            print(f"  - https://t.me/{c}  ( @{c} )")
    else:
        print("\n✓ 全部频道已加入")
    print(f"{'=' * 50}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="tdl 下载器：下载/去重/上传 Telegram 频道图片",
    )
    parser.add_argument("-a", "--auto", action="store_true",
                        help="自动模式：保留缓存继续下载，不询问")
    parser.add_argument("--login", nargs="?", const="desktop", default=None,
                        choices=["desktop", "code", "qr"],
                        help="重新登录 tdl（默认 desktop，可选 code/qr）")
    parser.add_argument("--check-channels", action="store_true",
                        help="检查频道加群状态，列出未加入频道的 t.me 链接")
    parser.add_argument("--all-now", action="store_true",
                        help="忽略拉取调度，全部频道本轮立即拉（手动补拉用）")
    parser.add_argument("--close-desktop", action="store_true",
                        help="启动拉取前自动结束 Telegram Desktop（避免同 key 双指纹并存）")
    args = parser.parse_args()

    if not os.path.exists(TDL_PATH):
        print(f"错误: tdl 不存在于 {TDL_PATH}")
        return

    # 子命令：登录
    if args.login is not None:
        ok = tdl_login(args.login)
        sys.exit(0 if ok else 1)

    # 子命令：检查加群状态
    if args.check_channels:
        check_channels()
        return

    # 默认：下载流程
    print("清理残留 tdl 进程...")
    _kill_tdl_processes()

    # 不做登录预检：预检本身要付一次 MTProto 握手税（实测 1.5~30s 波动）。
    # 真掉登录/网络不通时首个 export 会失败，由下方频道循环里的懒诊断兜底
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # 清理上次中断遗留的残留文件（export/filtered/tdl缓存）
    for f in os.listdir(DOWNLOAD_DIR):
        if f.endswith(".filtered.json") or f.endswith("_export.json") or f.startswith(".tdl"):
            path = os.path.join(DOWNLOAD_DIR, f)
            try:
                os.remove(path)
                print(f"清理残留文件: {path}")
            except OSError:
                pass

    md5_cache = load_json_cache(MD5_CACHE_FILE)
    progress_cache = load_json_cache(PROGRESS_CACHE_FILE)
    bad_cache = load_json_cache(BAD_FILES_CACHE_FILE)

    if md5_cache:
        image_count = sum(1 for v in md5_cache.values() if is_image(v.get("filename", "")))
        dates = [v.get("time", "") for v in md5_cache.values() if v.get("time")]
        earliest = min(dates) if dates else "未知"
        latest = max(dates) if dates else "未知"

        print(f"\n{'=' * 50}")
        print(f"当前缓存状态:")
        print(f"  总记录数: {len(md5_cache)}")
        print(f"  图片记录: {image_count}")
        print(f"  下载时间范围: {earliest[:10] if earliest else '未知'} ~ {latest[:10] if latest else '未知'}")
        print(f"{'=' * 50}")

        auto_mode = args.auto
        if auto_mode:
            print("自动模式: 保留现有缓存，继续下载。")
        else:
            print("\n缓存清理选项（去重记录和下载进度相互独立，可分别清理）:")
            print("  1. 清理去重记录 (md5_cache)  - 清后已下过的图可能被重新下载")
            print("  2. 清理下载进度 (progress)   - 清后各频道从头全量导出")
            print("  3. 全部清理")
            print("  其它/回车: 保留全部缓存，继续增量下载（推荐）")
            choice = input("选择 [1/2/3/N]: ").strip()
            if choice == "1":
                print("正在清理去重记录 (md5_cache)...")
                md5_cache = {}
                save_json_cache(MD5_CACHE_FILE, md5_cache)
                print("去重记录已清理（下载进度保留）。")
            elif choice == "2":
                print("正在清理下载进度 (progress_cache)...")
                progress_cache = {}
                save_json_cache(PROGRESS_CACHE_FILE, progress_cache)
                print("下载进度已清理（去重记录保留）。")
            elif choice == "3":
                print("正在清理全部缓存...")
                md5_cache = {}
                save_json_cache(MD5_CACHE_FILE, md5_cache)
                progress_cache = {}
                save_json_cache(PROGRESS_CACHE_FILE, progress_cache)
                print("全部缓存已清理。")
            else:
                print("保留全部缓存，继续增量下载。")
    else:
        print("\n首次运行，无缓存，将开始全新下载。")

    # 防风控频次调度：只拉到期频道，全部未到期则零 tdl 流量直接退出（省握手税）
    due = due_channels(progress_cache, force_all=args.all_now)
    skipped = [ch for ch in CHANNELS if ch not in due]
    if skipped:
        print(f"\n[调度] 本轮跳过(未到期): {', '.join(skipped)}")
    if not due:
        print("[调度] 本轮无到期频道，直接退出（--all-now 可强制全拉）")
        return

    # 有实际拉取动作才做共钥客户端检查（无到期的早退轮零 tdl 流量，无需提醒）
    check_shared_key_clients(auto_close=args.close_desktop)

    login_diag: Optional[str] = None  # export 失败时的登录/网络诊断结果缓存（"ok"/"not_authorized"/"failed"）
    for idx, channel in enumerate(due):
        if idx:
            gap = random.randint(*CHANNEL_GAP_SECONDS)
            print(f"\n[节奏] 频道间歇 {gap}s（打散机器节拍）...")
            time.sleep(gap)
        limit = CHANNELS[channel]
        print(f"\n\n处理频道: {channel} (限制 {limit} 条)")
        export_file = os.path.join(DOWNLOAD_DIR, f"{channel}_export.json")

        export_ok = False
        abort_round = False
        auto_relogin_done = False  # 整轮最多自动重登一次，防反复覆盖会话
        while True:
            if export_channel(channel, limit, export_file, progress_cache):
                export_ok = True
                break
            # export 失败：诊断一次区分「掉登录」「网络不通」和偶发失败
            if login_diag is None:
                login_diag = check_tdl_login()
            if login_diag == "ok":
                print(f"⚠ 登录正常，频道 {channel} 导出失败疑似偶发，跳过本频道")
                break
            if login_diag == "failed":
                print("\n请检查代理客户端/节点，然后重新运行脚本")
                abort_round = True
                break
            # 明确未登录：自动 desktop 重登（读取本机 Telegram Desktop 会话，非交互）
            if auto_relogin_done:
                print("\n自动重登后仍未恢复登录，请人工登录后重新运行脚本")
                print("  登录命令: python tdl_downloader_v2.py --login")
                abort_round = True
                break
            auto_relogin_done = True
            print("\n检测到 tdl 掉登录，尝试自动重登（desktop 方式，读取本机 Telegram Desktop 会话）...")
            if tdl_login("desktop"):
                print("✓ 自动重登成功，重试当前频道导出")
                login_diag = "ok"  # 已恢复，后续失败按偶发处理，不再触发重登
                continue
            print("✗ 自动重登失败（本机 Telegram Desktop 会话可能也失效，需人工扫码/验证码）")
            abort_round = True
            break

        if abort_round:
            break

        if export_ok:
            filter_and_download(export_file, DOWNLOAD_DIR, channel, limit, md5_cache, progress_cache, bad_cache)

        if os.path.exists(export_file):
            os.remove(export_file)

    print("\n\n完成!")


if __name__ == "__main__":
    main()
