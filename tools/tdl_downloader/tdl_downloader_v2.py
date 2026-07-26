import subprocess
import json
import os
import hashlib
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(line_buffering=True)

TDL_PATH = r"C:\tdl\tdl.exe"
PROXY = "socks5://127.0.0.1:17891"

CHANNELS = {
    "woshadiao": 200,
    "shadiao_refuse": 200,
    "xinjingdaily": 300,
    "xinjingdaily_reject": 100,
    "wtmsd": 300,
}

DOWNLOAD_DIR = r"C:\Users\w\Downloads\tdl"
INCLUDE_TYPES = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
MIN_FILE_SIZE_KB = 20

BASE_DIR = Path(__file__).parent
MD5_CACHE_FILE = BASE_DIR / "cache" / "md5_cache.json"
PROGRESS_CACHE_FILE = BASE_DIR / "cache" / "progress_cache.json"
DISCOVER_CACHE_FILE = BASE_DIR / "cache" / "discover_cache.json"

CMD_TIMEOUT = 600
NO_OUTPUT_TIMEOUT = 60
MAX_STUCK_COUNT = 2
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


def run_cmd(cmd: list[str], desc: str = "", target_dir: Optional[str] = None, expected_count: int = 0) -> bool:
    print(f"\n{'=' * 50}")
    print(f"{desc}")
    print(f"{'=' * 50}")

    for attempt in range(MAX_RETRIES):
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
        current_no_output_timeout = NO_OUTPUT_TIMEOUT
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
                return True

            current_len = len(output_lines)
            # 优先看进程活跃度（含被过滤的进度条行）：tdl 跳过重复文件时
            # 既不写新文件也不输出非过滤行，但 stdout 仍有进度条输出
            last_activity = state.get("last_activity_time", last_output_time)
            if current_len > last_output_len or last_activity > last_output_time:
                last_output_len = current_len
                last_output_time = max(last_output_time, last_activity)
                stuck_count = 0
            elif time.time() - last_output_time > current_no_output_timeout:
                # tdl 不接受 stdin 输入，不再发送 "y\n"
                # 仅基于文件数增长和 stdout 输出判断是否卡住
                stuck_count += 1
                print(f"\n{current_no_output_timeout}秒无输出，可能卡住 ({stuck_count}/{MAX_STUCK_COUNT})...")
                last_output_time = time.time()
                if stuck_count >= MAX_STUCK_COUNT:
                    print(f"连续{stuck_count}次卡住，终止并重启...")
                    process.terminate()
                    process.wait(5)
                    should_break = True
                    break
            elif time.time() - start_time > CMD_TIMEOUT:
                print(f"\n总超时 ({CMD_TIMEOUT}秒)，终止命令")
                process.terminate()
                process.wait(5)
                should_break = True
                break

        thread.join(5)

        if should_break:
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
            return True

        if attempt < MAX_RETRIES - 1:
            print(f"\n命令失败，返回码 {process.returncode}，重试 ({attempt + 1}/{MAX_RETRIES})...")

    print(f"\nError: 命令执行失败，已重试 {MAX_RETRIES} 次")
    print(f"最后命令: {' '.join(cmd)}")
    return False


def export_channel(channel: str, limit: int, output_file: str, progress_cache: dict) -> bool:
    last_id = progress_cache.get(channel, {}).get("last_id", 0)
    if last_id:
        start_id = last_id + 1
        cmd = [TDL_PATH, "chat", "export", "-c", channel, "-o", output_file,
               "-T", "id", "-i", str(start_id), "--proxy", PROXY, "--with-content"]
        desc = f"导出频道: {channel} (增量模式，从消息ID {start_id} 开始)"
    else:
        cmd = [TDL_PATH, "chat", "export", "-c", channel, "-o", output_file,
               "-T", "last", "-i", str(limit), "--proxy", PROXY, "--with-content"]
        desc = f"导出频道: {channel} (全量模式，最近 {limit} 条)"

    return run_cmd(cmd, desc)


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
    md5_cache: dict, channel: str
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


def filter_and_download(
    export_file: str, download_dir: str, channel: str, limit: int,
    md5_cache: dict, progress_cache: dict
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
    print(f"目录已有 {len(cached_files)} 个文件")

    # 检查已存在的文件是否已覆盖所有待下载图片
    pending_filenames = {msg.get("file") for msg in filtered if msg.get("file")}
    already_exist = pending_filenames & cached_files
    if already_exist and len(already_exist) == len(pending_filenames):
        print(f"所有 {len(pending_filenames)} 张图片已存在于目录中，跳过下载")
    else:
        if already_exist:
            print(f"其中 {len(already_exist)} 张已存在，需下载 {len(pending_filenames) - len(already_exist)} 张")

    # --continue 容易因残留 .tdl 缓存导致卡住，去掉
    # -t 2 并发下载（不要设太大，避免触发 Telegram 限速）
    need_download_count = len(pending_filenames) - len(already_exist)
    cmd = [TDL_PATH, "dl", "-f", filtered_file, "-d", download_dir,
           "--proxy", PROXY, "--skip-same", "-t", "2"]
    dl_ok = run_cmd(cmd, f"下载 {channel} 的 {len(filtered)} 张图片到 {download_dir}",
                    target_dir=download_dir, expected_count=need_download_count)

    if not dl_ok:
        print(f"⚠ 下载命令执行失败，可能部分或全部图片未下载成功")

    new_files = [
        f for f in os.listdir(download_dir)
        if os.path.isfile(os.path.join(download_dir, f)) and f not in cached_files
    ]

    downloaded, skipped = _deduplicate_new_files(download_dir, new_files, md5_cache, channel)
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

    max_id = max(
        (m.get("id", 0) for m in messages if isinstance(m.get("id"), int)),
        default=0,
    )
    if max_id > 0:
        progress_cache[channel] = {
            "last_id": max_id,
            "last_time": datetime.now().isoformat(),
        }
        save_json_cache(PROGRESS_CACHE_FILE, progress_cache)
        print(f"已记录进度: 频道 {channel} 最后消息ID: {max_id}")

    if os.path.exists(filtered_file):
        os.remove(filtered_file)


def check_tdl_login() -> bool:
    """检查 tdl 登录状态。

    用 chat ls（只列对话列表，不拉内容）替代 chat export --with-content，
    避免内容下载限速被误判为未登录。区分三类结果：
    - 明确未登录（输出含 not authorized / please login）：直接返回 False
    - 限速/网络抖动：重试，不轻易判未登录
    - 成功：返回 True
    """
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  正在检查 tdl 登录状态（{attempt}/{max_retries}，超时 30 秒）...")
            start = time.time()
            result = subprocess.run(
                [TDL_PATH, "chat", "ls", "--proxy", PROXY],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            elapsed = time.time() - start
            if result.returncode == 0:
                print(f"✓ tdl 已登录（耗时 {elapsed:.1f}s）")
                return True

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
                return False

            # 其它失败（限速/网络抖动）：重试，不判未登录
            print(f"⚠ 连接异常（耗时 {elapsed:.1f}s，返回码 {result.returncode}），可能是限速或网络抖动")
            if combined:
                for line in combined.splitlines()[:3]:
                    line = line.strip()
                    if line and not any(p in line for p in TDL_IGNORE_PATTERNS):
                        print(f"  {line}")
            if attempt < max_retries:
                print(f"  等待 5 秒后重试...")
                time.sleep(5)
            else:
                print(f"  -> 重试 {max_retries} 次仍失败，代理可能不通或 Telegram 限速严重")
                print(f"  -> 这不代表未登录，可稍后重试或直接运行下载观察")
                return False
        except subprocess.TimeoutExpired:
            print(f"⚠ 检查登录超时（30 秒）")
            if attempt < max_retries:
                print(f"  等待 5 秒后重试...")
                time.sleep(5)
            else:
                print(f"  -> 重试 {max_retries} 次均超时，代理可能不通")
                return False
        except Exception as e:
            print(f"✗ 检查登录状态失败: {e}")
            return False
    return False


def tdl_login(login_type: str = "desktop") -> bool:
    """调起 tdl 交互式登录。login_type: desktop / code / qr。

    登录是交互式操作（选用户/输验证码/扫码），必须由用户在终端完成，
    本函数只负责清理残留进程后拉起命令，完成后自动验证登录状态。
    """
    if login_type not in ("desktop", "code", "qr"):
        print(f"✗ 不支持的登录方式: {login_type}（可选 desktop / code / qr）")
        return False

    print("登录前清理残留 tdl 进程（避免数据库锁冲突）...")
    _kill_tdl_processes()

    print(f"\n启动 tdl 登录（方式: {login_type}）...")
    print("提示: 登录会覆盖 default namespace 的现有会话")
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
    return check_tdl_login()


def check_channels() -> None:
    """对比 CHANNELS 配置和 chat ls 结果，列出已加入/未加入的频道。

    tdl 无 join 命令，未加入的频道只能输出 t.me 链接由用户手动添加。
    """
    print("获取当前账号已加入的对话列表...")
    _kill_tdl_processes()
    try:
        result = subprocess.run(
            [TDL_PATH, "chat", "ls", "-o", "json", "--proxy", PROXY],
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
        print(f"\n✗ 未加入 ({len(missing)}):")
        print("  tdl 无自动加群命令，请手动加入以下链接:")
        for c in missing:
            print(f"  - https://t.me/{c}  ( @{c} )")
        print("\n  全部加入后重新运行: python tdl_downloader_v2.py --check-channels")
    else:
        print("\n✓ 全部频道已加入，可以开始下载")
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

    if not check_tdl_login():
        print("\n请先登录 tdl，然后重新运行脚本")
        print("  登录命令: python tdl_downloader_v2.py --login")
        return

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

    for channel, limit in CHANNELS.items():
        print(f"\n\n处理频道: {channel} (限制 {limit} 条)")
        export_file = os.path.join(DOWNLOAD_DIR, f"{channel}_export.json")

        if export_channel(channel, limit, export_file, progress_cache):
            filter_and_download(export_file, DOWNLOAD_DIR, channel, limit, md5_cache, progress_cache)

        if os.path.exists(export_file):
            os.remove(export_file)

    print("\n\n完成!")


if __name__ == "__main__":
    main()
