import subprocess
import json
import os
import hashlib
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

TDL_PATH = r"C:\tdl\tdl.exe"
PROXY = "socks5://127.0.0.1:7897"
MAX_WORKERS = 2

CHANNELS = {
    "woshadiao": 200    ,
    "shadiao_refuse": 200,
    "xinjingdaily": 300,
    "wtmsd": 300,
}

DOWNLOAD_DIR = r"C:\Users\w\Downloads\tdl"
INCLUDE_TYPES = ["jpg", "jpeg", "png", "gif", "webp", "bmp"]
MIN_FILE_SIZE_KB = 20

BASE_DIR = Path(__file__).parent
MD5_CACHE_FILE = BASE_DIR / "cache" / "md5_cache.json"
PROGRESS_CACHE_FILE = BASE_DIR / "cache" / "progress_cache.json"

cache_lock = threading.Lock()


def load_md5_cache():
    with cache_lock:
        MD5_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if MD5_CACHE_FILE.exists():
            try:
                with open(MD5_CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}


def save_md5_cache(cache):
    with cache_lock:
        with open(MD5_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)


def load_progress_cache():
    with cache_lock:
        PROGRESS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if PROGRESS_CACHE_FILE.exists():
            try:
                with open(PROGRESS_CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}


def save_progress_cache(cache):
    with cache_lock:
        with open(PROGRESS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)


def is_image(filename):
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext in INCLUDE_TYPES


def calculate_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def run_cmd(cmd, desc="", max_retries=3, target_dir=None, channel_prefix=""):
    prefix = f"[{channel_prefix}] " if channel_prefix else ""
    print(f"\n{'='*50}")
    print(f"{prefix}{desc}")
    print(f"{'='*50}")

    for attempt in range(max_retries):
        process = subprocess.Popen(
            cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )

        output_lines = []
        start_time = time.time()

        def read_output():
            try:
                for line in process.stdout:
                    if line.strip():
                        output_lines.append(line)
            except:
                pass

        thread = threading.Thread(target=read_output, daemon=True)
        thread.start()

        last_output = 0
        last_output_time = time.time()
        timeout = 600
        no_output_timeout = 60
        stuck_count = 0
        max_stuck = 5

        while process.poll() is None:
            time.sleep(1)
            current_len = len(output_lines)
            if current_len > last_output:
                new_lines = output_lines[last_output:]
                for line in new_lines:
                    stripped = line.strip()
                    if stripped:
                        print(f"  {prefix}{stripped}")
                last_output = current_len
                last_output_time = time.time()
                stuck_count = 0
            elif time.time() - last_output_time > no_output_timeout:
                stuck_count += 1
                print(f"  {prefix}{no_output_timeout}秒无输出，可能卡住 ({stuck_count}/{max_stuck})...")
                try:
                    process.stdin.write("y\n")
                    process.stdin.flush()
                except:
                    pass
                last_output_time = time.time()
                if stuck_count >= max_stuck:
                    print(f"  {prefix}连续{stuck_count}次卡住，终止并重启...")
                    process.terminate()
                    process.wait(5)
                    break
            elif time.time() - start_time > timeout:
                print(f"  {prefix}总超时 ({timeout}秒)，终止命令")
                process.terminate()
                process.wait(5)
                break

        thread.join(5)

        if process.returncode == 0:
            return True

        if attempt < max_retries - 1:
            print(f"  {prefix}命令失败，返回码 {process.returncode}，重试 ({attempt + 1}/{max_retries})...")

    print(f"  {prefix}Error: 命令执行失败，已重试 {max_retries} 次")
    return False


def export_channel(channel, limit, output_file, start_id=None):
    progress_cache = load_progress_cache()
    last_id = progress_cache.get(channel, {}).get("last_id", 0)
    if last_id:
        start_id = last_id + 1
        cmd = f'"{TDL_PATH}" chat export -c {channel} -o "{output_file}" -T id -i {start_id} --proxy {PROXY} --with-content'
        desc = f"导出频道: {channel} (从消息ID {start_id} 开始)"
    else:
        cmd = f'"{TDL_PATH}" chat export -c {channel} -o "{output_file}" -T last -i {limit} --proxy {PROXY} --with-content'
        desc = f"导出频道: {channel} (最近 {limit} 条)"
    
    return run_cmd(cmd, desc, channel_prefix=channel)


def filter_and_download(export_file, download_dir, channel):
    if not os.path.exists(export_file):
        print(f"  [{channel}] 导出文件不存在: {export_file}")
        return

    with open(export_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    print(f"  [{channel}] 获取消息数: {len(messages)}")

    file_list = []
    for msg in messages:
        file_path = msg.get("file")
        if not file_path:
            continue
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        if ext not in INCLUDE_TYPES:
            continue
        file_list.append(msg)

    print(f"  [{channel}] 图片消息数: {len(file_list)}")

    if not file_list:
        print(f"  [{channel}] 没有找到图片")
        return

    sequential_groups = []
    current_group = []
    last_base = None
    last_num = None

    for msg in file_list:
        filename = msg.get("file", "")
        name_part = filename.rsplit(".", 1)[0] if "." in filename else filename

        if name_part.isdigit():
            base = ""
            num = int(name_part)
        else:
            match = re.match(r"^(.+?)(\d+)$", name_part)
            if match:
                base = match.group(1)
                num = int(match.group(2))
            else:
                base = name_part
                num = None

        is_sequential = False
        if num is not None and last_num is not None:
            if base == last_base and num == last_num + 1:
                is_sequential = True

        if is_sequential:
            if not current_group:
                current_group.append(prev_msg)
            current_group.append(msg)
        else:
            if current_group and len(current_group) >= 3:
                sequential_groups.append(current_group)
            current_group = []

        prev_msg = msg
        last_base = base
        last_num = num

    if current_group and len(current_group) >= 3:
        sequential_groups.append(current_group)

    sequential_files = set()
    for group in sequential_groups:
        for msg in group:
            sequential_files.add(msg.get("file"))

    filtered = [msg for msg in file_list if msg.get("file") not in sequential_files]

    print(f"  [{channel}] 过滤后图片数: {len(filtered)} (跳过连续漫画: {len(sequential_files)} 张)")

    if not filtered:
        print(f"  [{channel}] 没有找到图片")
        return

    filtered_file = export_file.replace(".json", "_filtered.json")
    with open(filtered_file, "w", encoding="utf-8") as f:
        json.dump({"id": data["id"], "messages": filtered}, f, ensure_ascii=False, indent=2)

    target_dir = download_dir
    os.makedirs(target_dir, exist_ok=True)

    cmd = f'"{TDL_PATH}" dl -f "{filtered_file}" -d "{target_dir}" --proxy {PROXY} --skip-same --continue'
    run_cmd(cmd, f"下载 {channel} 的 {len(filtered)} 张图片", channel_prefix=channel)

    new_files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f)) and is_image(f)]
    
    with cache_lock:
        md5_cache = load_md5_cache()

    skipped = 0
    downloaded = 0

    for filename in new_files:
        file_path = os.path.join(target_dir, filename)
        try:
            file_size_kb = os.path.getsize(file_path) / 1024
            if file_size_kb < MIN_FILE_SIZE_KB:
                print(f"  [{channel}] 图片太小({file_size_kb:.0f}KB)，删除: {filename}")
                os.remove(file_path)
                continue

            md5 = calculate_md5(file_path)
            if md5 in md5_cache:
                print(f"  [{channel}] 重复图片，删除: {filename}")
                os.remove(file_path)
                skipped += 1
            else:
                md5_cache[md5] = {
                    "channel": channel,
                    "filename": filename,
                    "time": datetime.now().isoformat()
                }
                downloaded += 1
        except Exception as e:
            print(f"  [{channel}] 处理失败 {filename}: {e}")

    with cache_lock:
        save_md5_cache(md5_cache)
    print(f"  [{channel}] 下载完成: 新增 {downloaded} 张, 跳过重复 {skipped} 张")

    max_id = 0
    if messages:
        for msg in messages:
            msg_id = msg.get("id", 0)
            if msg_id and isinstance(msg_id, int):
                max_id = max(max_id, msg_id)
    
    if max_id > 0:
        with cache_lock:
            progress_cache = load_progress_cache()
            progress_cache[channel] = {
                "last_id": max_id,
                "last_time": datetime.now().isoformat()
            }
            save_progress_cache(progress_cache)
        print(f"  [{channel}] 已记录进度: 最后消息ID: {max_id}")
    
    try:
        os.remove(filtered_file)
    except:
        pass


def process_channel(channel, limit):
    export_file = os.path.join(DOWNLOAD_DIR, f"{channel}_export.json")

    if export_channel(channel, limit, export_file):
        return export_file

    if os.path.exists(export_file):
        try:
            os.remove(export_file)
        except:
            pass
    return None


def main():
    if not os.path.exists(TDL_PATH):
        print(f"错误: tdl 不存在于 {TDL_PATH}")
        return

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    cache = load_md5_cache()
    if cache:
        image_count = sum(1 for v in cache.values() if is_image(v.get("filename", "")))
        dates = [v.get("time", "") for v in cache.values() if v.get("time")]
        earliest = min(dates) if dates else "未知"
        latest = max(dates) if dates else "未知"

        print(f"\n{'='*50}")
        print(f"当前缓存状态:")
        print(f"  总记录数: {len(cache)}")
        print(f"  图片记录: {image_count}")
        print(f"  下载时间范围: {earliest[:10] if earliest else '未知'} ~ {latest[:10] if latest else '未知'}")
        print(f"{'='*50}")

        response = input("是否清理缓存重新下载? (y/N): ").strip().lower()
        if response == "y":
            print("正在清理缓存...")
            cache = {}
            save_md5_cache(cache)
            print("缓存已清理。")
        else:
            print("保留现有缓存，继续下载。")
    else:
        print(f"\n首次运行，无缓存，将开始全新下载。")

    print(f"\n阶段1: 串行导出 {len(CHANNELS)} 个频道...")
    export_results = {}
    for channel, limit in CHANNELS.items():
        export_file = process_channel(channel, limit)
        if export_file:
            export_results[channel] = export_file

    print(f"\n阶段2: 并发下载 {len(export_results)} 个频道 (并发数: {MAX_WORKERS})...")

    def download_task(channel, export_file):
        try:
            filter_and_download(export_file, DOWNLOAD_DIR, channel)
            return channel
        finally:
            if os.path.exists(export_file):
                try:
                    os.remove(export_file)
                except:
                    pass

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(download_task, channel, export_file): channel
            for channel, export_file in export_results.items()
        }

        for future in as_completed(futures):
            channel = futures[future]
            try:
                future.result()
                print(f"\n频道 {channel} 全部完成")
            except Exception as e:
                print(f"\n频道 {channel} 处理异常: {e}")

    print("\n\n所有频道处理完成!")


if __name__ == "__main__":
    main()
