import subprocess
import json
import os
import hashlib
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
import tensorflow as tf

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
MODEL_PATH = BASE_DIR / "converted_model.tflite"

_interpreter = None
_input_details = None
_output_details = None
_input_shape = None


def load_model():
    global _interpreter, _input_details, _output_details, _input_shape
    if _interpreter is None:
        if not MODEL_PATH.exists():
            print(f"模型文件不存在: {MODEL_PATH}")
            return False
        _interpreter = tf.lite.Interpreter(model_path=str(MODEL_PATH))
        _interpreter.allocate_tensors()
        _input_details = _interpreter.get_input_details()
        _output_details = _interpreter.get_output_details()
        _input_shape = _input_details[0]['shape']
        print(f"模型加载成功，输入尺寸: {_input_shape[1]}x{_input_shape[2]}")
    return True


def is_meme(image_path, threshold=0.5):
    if not load_model():
        return True
    try:
        img = Image.open(image_path).convert('RGB')
        img = img.resize((_input_shape[1], _input_shape[2]))
        img = np.array(img, dtype=np.float32) / 255.0
        img = np.expand_dims(img, axis=0)

        _interpreter.set_tensor(_input_details[0]['index'], img)
        _interpreter.invoke()
        prob = _interpreter.get_tensor(_output_details[0]['index'])[0][0]

        return prob > threshold
    except Exception as e:
        print(f"模型推理失败: {e}")
        return True


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

    filtered = []
    for msg in messages:
        file_path = msg.get("file")
        if not file_path:
            continue
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        if ext in INCLUDE_TYPES:
            filtered.append(msg)

    print(f"图片消息数: {len(filtered)}")

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

            if not is_meme(file_path):
                print(f"非梗图，删除: {filename}")
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

    if not MODEL_PATH.exists():
        print(f"错误: 模型文件不存在: {MODEL_PATH}")
        print("请下载模型到该路径")
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
