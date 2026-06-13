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
NO_OUTPUT_TIMEOUT_RETRY = 15
MAX_STUCK_COUNT = 2
TDL_IGNORE_PATTERNS = [
    "WARN: Export only generates",
    "Occasional suspensions",
    "Type:",
    "Input:",
]
MAX_RETRIES = 3
MD5_CHUNK_SIZE = 8192
SEQUENTIAL_GROUP_MIN = 3
DISCOVER_SAMPLE_LIMIT = 50
DISCOVER_MIN_FORWARDS = 3


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


def _read_process_output(process: subprocess.Popen, output_lines: list, state: dict) -> None:
    try:
        for line in process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            if any(p in stripped for p in TDL_IGNORE_PATTERNS):
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


def run_cmd(cmd: list[str], desc: str = "", target_dir: Optional[str] = None) -> bool:
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

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        output_lines: list[str] = []
        state: dict = {"channel_name": ""}
        current_no_output_timeout = NO_OUTPUT_TIMEOUT_RETRY if attempt > 0 else NO_OUTPUT_TIMEOUT
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
                    stuck_count = 0

            current_len = len(output_lines)
            if current_len > last_output_len:
                last_output_len = current_len
                last_output_time = time.time()
                stuck_count = 0
            elif time.time() - last_output_time > current_no_output_timeout:
                stuck_count += 1
                print(f"\n{current_no_output_timeout}秒无输出，可能卡住 ({stuck_count}/{MAX_STUCK_COUNT})...")
                _send_stdin(process, "y\n")
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

    for filename in new_filenames:
        if not is_image(filename):
            continue

        file_path = os.path.join(target_dir, filename)
        try:
            file_size_kb = os.path.getsize(file_path) / 1024
            if file_size_kb < MIN_FILE_SIZE_KB:
                print(f"图片太小({file_size_kb:.0f}KB)，删除: {filename}")
                os.remove(file_path)
                continue

            md5 = calculate_md5(file_path)
            if md5 in md5_cache:
                print(f"重复图片，删除: {filename}")
                os.remove(file_path)
                skipped += 1
            else:
                md5_cache[md5] = {
                    "channel": channel,
                    "filename": filename,
                    "time": datetime.now().isoformat(),
                }
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
    # -t 4 并发下载加速
    cmd = [TDL_PATH, "dl", "-f", filtered_file, "-d", download_dir,
           "--proxy", PROXY, "--skip-same", "-t", "2"]
    dl_ok = run_cmd(cmd, f"下载 {channel} 的 {len(filtered)} 张图片到 {download_dir}", target_dir=download_dir)

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
    try:
        result = subprocess.run(
            [TDL_PATH, "chat", "export", "-c", "woshadiao", "-T", "last", "-i", "1",
             "--proxy", PROXY, "--with-content"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if result.returncode == 0:
            print("✓ tdl 已登录")
            return True
        else:
            print("✗ tdl 未登录，请先执行登录")
            print("  命令: tdl login --proxy socks5://127.0.0.1:17891")
            return False
    except Exception as e:
        print(f"✗ 检查登录状态失败: {e}")
        return False


def main() -> None:
    if not os.path.exists(TDL_PATH):
        print(f"错误: tdl 不存在于 {TDL_PATH}")
        return

    print("清理残留 tdl 进程...")
    _kill_tdl_processes()

    if not check_tdl_login():
        print("\n请先登录 tdl，然后重新运行脚本")
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

        auto_mode = "--auto" in sys.argv or "-a" in sys.argv
        if auto_mode:
            print("自动模式: 保留现有缓存，继续下载。")
        else:
            response = input("是否清理缓存重新下载? (y/N): ").strip().lower()
            if response == "y":
                print("正在清理缓存...")
                md5_cache = {}
                save_json_cache(MD5_CACHE_FILE, md5_cache)
                print("缓存已清理。")
            else:
                print("保留现有缓存，继续下载。")
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
