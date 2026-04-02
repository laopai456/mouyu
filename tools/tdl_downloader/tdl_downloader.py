import subprocess
import json
import os
import hashlib
import re
from datetime import datetime
from pathlib import Path

TDL_PATH = r"C:\tdl\tdl.exe"
PROXY = "socks5://127.0.0.1:7897"

CHANNELS = {
    "woshadiao": 100    ,
    "shadiao_refuse": 80,
    "xinjingdaily": 200,
    "wtmsd": 160,
}

DOWNLOAD_DIR = r"C:\Users\w\Downloads\tdl"
INCLUDE_TYPES = ["jpg", "jpeg", "png", "gif", "webp", "bmp"]
MIN_FILE_SIZE_KB = 20

BASE_DIR = Path(__file__).parent
MD5_CACHE_FILE = BASE_DIR / "cache" / "md5_cache.json"


def load_md5_cache():
    MD5_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if MD5_CACHE_FILE.exists():
        try:
            with open(MD5_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_md5_cache(cache):
    with open(MD5_CACHE_FILE, "w", encoding="utf-8") as f:
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


def run_cmd(cmd, desc="", max_retries=3):
    print(f"\n{'='*50}")
    print(f"{desc}")
    print(f"{'='*50}")

    for attempt in range(max_retries):
        process = subprocess.Popen(
            cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )

        import threading
        import time
        output_lines = []
        start_time = time.time()

        download_count = 0
        last_file = ""
        channel_name = ""

        def read_output():
            nonlocal download_count, last_file, channel_name
            try:
                for line in process.stdout:
                    if '%' in line and '->' in line:
                        if '100%' in line or '100.0%' in line:
                            parts = line.split('(')
                            if len(parts) > 1:
                                name_part = parts[1].split(')')[0] if ')' in parts[1] else ""
                                if name_part and name_part != last_file:
                                    last_file = name_part
                                    download_count += 1
                                    print(f"  📥 {channel_name}: {download_count} 张", end="\r", flush=True)
                    elif '(' in line and ')' in line and ':' in line:
                        parts = line.split('(')
                        if len(parts) > 1:
                            channel_name = parts[0].strip()
            except Exception as e:
                pass

        thread = threading.Thread(target=read_output, daemon=True)
        thread.start()

        last_output = 0
        last_output_time = time.time()
        timeout = 600
        no_output_timeout = 30
        stuck_count = 0
        max_stuck = 3

        while process.poll() is None:
            time.sleep(0.5)
            current_len = len(output_lines)
            if current_len > last_output:
                last_output = current_len
                last_output_time = time.time()
                stuck_count = 0
            elif time.time() - last_output_time > no_output_timeout:
                stuck_count += 1
                print(f"\n\n{no_output_timeout}秒无输出，可能卡住 ({stuck_count}/{max_stuck})...")
                try:
                    process.stdin.write("y\n")
                    process.stdin.flush()
                except:
                    pass
                last_output_time = time.time()
                if stuck_count >= max_stuck:
                    print(f"连续{stuck_count}次卡住，终止并重启...")
                    process.terminate()
                    process.wait(5)
                    break
            elif time.time() - start_time > timeout:
                print(f"\n\n总超时 ({timeout}秒)，终止命令")
                process.terminate()
                process.wait(5)
                break

        thread.join(5)

        if process.returncode == 0:
            return True

        if attempt < max_retries - 1:
            print(f"\n命令失败，返回码 {process.returncode}，重试 ({attempt + 1}/{max_retries})...")

    print(f"\nError: 命令执行失败，已重试 {max_retries} 次")
    return False


def export_channel(channel, limit, output_file):
    cmd = f'"{TDL_PATH}" chat export -c {channel} -o "{output_file}" -T last -i {limit} --proxy {PROXY} --with-content'
    return run_cmd(cmd, f"导出频道: {channel} (最近 {limit} 条)")


def filter_and_download(export_file, download_dir, channel):
    if not os.path.exists(export_file):
        print(f"导出文件不存在: {export_file}")
        return

    with open(export_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    print(f"获取消息数: {len(messages)}")

    file_list = []
    for msg in messages:
        file_path = msg.get("file")
        if not file_path:
            continue
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        if ext not in INCLUDE_TYPES:
            continue
        file_list.append(msg)

    print(f"图片消息数: {len(file_list)}")

    if not file_list:
        print("没有找到图片")
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

    print(f"过滤后图片数: {len(filtered)} (跳过连续漫画: {len(sequential_files)} 张)")

    if not filtered:
        print("没有找到图片")
        return

    filtered_file = export_file.replace(".json", "_filtered.json")
    with open(filtered_file, "w", encoding="utf-8") as f:
        json.dump({"id": data["id"], "messages": filtered}, f, ensure_ascii=False, indent=2)

    target_dir = DOWNLOAD_DIR
    os.makedirs(target_dir, exist_ok=True)

    md5_cache = load_md5_cache()

    cached_files = set(os.listdir(target_dir)) if os.path.exists(target_dir) else set()
    print(f"目录已有 {len(cached_files)} 个文件")

    cmd = f'"{TDL_PATH}" dl -f "{filtered_file}" -d "{target_dir}" --proxy {PROXY} --skip-same --restart'
    run_cmd(cmd, f"下载 {channel} 的 {len(filtered)} 张图片到 {target_dir}")

    new_files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f)) and f not in cached_files]
    skipped = 0
    downloaded = 0

    for filename in new_files:
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
                    "time": datetime.now().isoformat()
                }
                downloaded += 1
        except Exception as e:
            print(f"处理失败 {filename}: {e}")

    save_md5_cache(md5_cache)
    print(f"下载完成: 新增 {downloaded} 张, 跳过重复 {skipped} 张")

    os.remove(filtered_file)


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
        print("\n首次运行，无缓存，将开始全新下载。")

    for channel, limit in CHANNELS.items():
        print(f"\n\n处理频道: {channel} (限制 {limit} 条)")
        export_file = os.path.join(DOWNLOAD_DIR, f"{channel}_export.json")

        if export_channel(channel, limit, export_file):
            filter_and_download(export_file, DOWNLOAD_DIR, channel)

        if os.path.exists(export_file):
            os.remove(export_file)

    print("\n\n完成!")


if __name__ == "__main__":
    main()
