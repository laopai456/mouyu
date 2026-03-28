import subprocess
import json
import os
import hashlib
import re
from datetime import datetime
from pathlib import Path

try:
    from paddleocr import PaddleOCR
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

TDL_PATH = r"C:\tdl\tdl.exe"
PROXY = "socks5://127.0.0.1:7897"

CHANNELS = {
    "woshadiao": 100,
    "shadiao_refuse": 150,
    "xinjingdaily": 150,
    "wtmsd": 100,
}

DOWNLOAD_DIR = r"C:\Users\w\Downloads\tdl"
INCLUDE_TYPES = ["jpg", "jpeg", "png", "gif", "webp", "bmp"]
MIN_FILE_SIZE_KB = 30

BASE_DIR = Path(__file__).parent
MD5_CACHE_FILE = BASE_DIR / "cache" / "md5_cache.json"

_ocr = None


def get_ocr():
    global _ocr
    if _ocr is None and OCR_AVAILABLE:
        _ocr = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False)
    return _ocr


def has_text(image_path, min_confidence=0.7):
    if not OCR_AVAILABLE:
        return True
    try:
        ocr = get_ocr()
        result = ocr.ocr(image_path, cls=False)
        if result and result[0]:
            for line in result[0]:
                if line[1][1] > min_confidence:
                    return True
    except Exception as e:
        print(f"OCR检测失败: {e}")
    return False


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


def run_cmd(cmd, desc=""):
    print(f"\n{'='*50}")
    print(f"{desc}")
    print(f"{'='*50}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return False
    print(result.stdout)
    return True


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

    cmd = f'"{TDL_PATH}" dl -f "{filtered_file}" -d "{target_dir}" --proxy {PROXY} --skip-same'
    run_cmd(cmd, f"下载 {channel} 的 {len(filtered)} 张图片到 {target_dir}")

    new_files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f))]
    skipped = 0
    downloaded = 0
    not_meme = 0

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

            if not has_text(file_path):
                print(f"无文字内容，删除: {filename}")
                os.remove(file_path)
                not_meme += 1
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
    print(f"下载完成: 新增 {downloaded} 张, 跳过重复 {skipped} 张, 过滤非梗图 {not_meme} 张")

    os.remove(filtered_file)


def main():
    if not os.path.exists(TDL_PATH):
        print(f"错误: tdl 不存在于 {TDL_PATH}")
        return

    if not OCR_AVAILABLE:
        print("警告: PaddleOCR 未安装，将跳过文字检测")
        print("请运行: pip install paddleocr paddlepaddle")

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
