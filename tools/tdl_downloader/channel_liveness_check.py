"""频道活跃度体检：各频道最后一条消息距今多久，识别「已停更」频道。

判定口径：频道最后一条消息（不限图片）距今 ≥ N 天（默认 3）→ 视为已停更。
实现：对每个频道 tdl export `-T last -i 5`（只导最近 5 条消息的元数据，
不下载文件，流量远小于一轮日常增量），取 max(date) 判断。
只读操作：不加群、不下载、不写水位（progress_cache 不动）。

用法：
    python channel_liveness_check.py            # 默认 3 天阈值
    python channel_liveness_check.py --days 7   # 自定义阈值
    python channel_liveness_check.py --gap 30   # 频道间间歇秒数（默认 20~40 随机）
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tdl_downloader_v2 import (  # noqa: E402
    CHANNELS, DOWNLOAD_DIR, TDL_PATH, _tdl_base_args, run_cmd,
)

CST = timezone(timedelta(hours=8))
SCAN_DIR = Path(__file__).parent / "cache" / "liveness"


def check_channel(channel: str, out_file: str) -> dict:
    """导出最近 5 条消息元数据，返回 {last_date, days, imgs_in_last5, msg_count}。"""
    cmd = [TDL_PATH, "chat", "export", "-c", channel, "-o", out_file,
           "-T", "last", "-i", "5", "--with-content"] + _tdl_base_args()
    ok, _ = run_cmd(cmd, f"导出: {channel} (最近 5 条，仅元数据)", enable_stuck_check=False)
    if not ok or not os.path.exists(out_file):
        return {"error": "export失败"}

    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    msgs = [m for m in data.get("messages", []) if isinstance(m, dict)]
    if not msgs:
        return {"error": "0消息(不可读或已清空)"}

    def as_ts(v):
        if isinstance(v, (int, float)):
            return float(v)
        try:  # ISO 字符串兜底
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    ts_list = [as_ts(m.get("date", 0)) for m in msgs]
    last_ts = max(ts_list)
    img_cnt = sum(1 for m in msgs if m.get("file"))
    now = datetime.now(CST).timestamp()
    return {
        "last_date": datetime.fromtimestamp(last_ts, CST).strftime("%Y-%m-%d %H:%M"),
        "days": round((now - last_ts) / 86400, 1),
        "imgs_in_last5": img_cnt,
        "msg_count": len(msgs),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=3, help="停更判定阈值（天），默认 3")
    ap.add_argument("--gap", type=int, nargs=2, default=(20, 40),
                    metavar=("MIN", "MAX"), help="频道间歇秒数范围，默认 20~40")
    args = ap.parse_args()

    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for idx, channel in enumerate(CHANNELS):
        if idx:
            gap = random.randint(*args.gap)
            print(f"[节奏] 间歇 {gap}s...", flush=True)
            time.sleep(gap)
        out_file = str(SCAN_DIR / f"{channel}_last5.json")
        r = check_channel(channel, out_file)
        results[channel] = r
        if "error" in r:
            print(f"  {channel}: ⚠ {r['error']}", flush=True)
        else:
            flag = "🪦停更" if r["days"] >= args.days else "✅活跃"
            print(f"  {channel}: 最后消息 {r['last_date']} ({r['days']}天前) "
                  f"近5条含图{r['imgs_in_last5']}/{r['msg_count']} {flag}", flush=True)

    dead = [c for c, r in results.items() if r.get("days", -1) >= args.days]
    print(f"\n===== 汇总（阈值 {args.days} 天）=====")
    if dead:
        print(f"停更频道 ({len(dead)}/{len(CHANNELS)}): {', '.join(dead)}")
    else:
        print(f"无停更频道（10/10 活跃）")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
