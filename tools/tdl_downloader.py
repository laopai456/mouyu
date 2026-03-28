import subprocess
import json
import os
from datetime import datetime
from pathlib import Path

TDL_PATH = r"C:\tdl\tdl.exe"
PROXY = "socks5://127.0.0.1:7897"

CHANNELS = [
    "woshadiao",
    "shadiao_refuse",
    "xinjingdaily",
    "wtmsd",
]

DOWNLOAD_DIR = r"C:\Users\w\Downloads\tdl"
START_DATE = "2026-03-28"
INCLUDE_TYPES = ["jpg", "jpeg", "png", "gif", "webp", "bmp"]


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


def export_channel(channel, output_file):
    cmd = f'"{TDL_PATH}" chat export -c {channel} -o "{output_file}" --proxy {PROXY} --with-content'
    return run_cmd(cmd, f"导出频道: {channel}")


def filter_and_download(export_file, download_dir, channel, since_ts=None):
    if not os.path.exists(export_file):
        print(f"导出文件不存在: {export_file}")
        return

    with open(export_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    print(f"总消息数: {len(messages)}")

    if since_ts:
        messages = [m for m in messages if m.get("date", 0) >= since_ts]
        print(f"过滤后消息数: {len(messages)} (since {datetime.fromtimestamp(since_ts)})")

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

    target_dir = os.path.join(download_dir, channel)
    os.makedirs(target_dir, exist_ok=True)

    cmd = f'"{TDL_PATH}" dl -f "{filtered_file}" -d "{target_dir}" --proxy {PROXY}'
    run_cmd(cmd, f"下载 {channel} 的 {len(filtered)} 张图片到 {target_dir}")

    os.remove(filtered_file)


def main():
    if not os.path.exists(TDL_PATH):
        print(f"错误: tdl 不存在于 {TDL_PATH}")
        return

    since_ts = None
    if START_DATE:
        try:
            dt = datetime.strptime(START_DATE, "%Y-%m-%d")
            since_ts = int(dt.timestamp())
            print(f"将下载 {START_DATE} 之后的图片")
        except ValueError:
            print(f"日期格式错误: {START_DATE}, 将下载所有图片")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    for channel in CHANNELS:
        print(f"\n\n处理频道: {channel}")
        export_file = os.path.join(DOWNLOAD_DIR, f"{channel}_export.json")

        if export_channel(channel, export_file):
            filter_and_download(export_file, DOWNLOAD_DIR, channel, since_ts)

        if os.path.exists(export_file):
            os.remove(export_file)

    print("\n\n完成!")


if __name__ == "__main__":
    main()
