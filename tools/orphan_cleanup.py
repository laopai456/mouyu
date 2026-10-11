"""存储桶孤儿文件清理：桶里存在但数据库没引用的对象。

背景（2026-10-11 实测）：uploader 历史「先传桶后查重」导致 ~79k 个未入库文件堆积
16.5GB，把个人版 3GB 容量额度撑爆。uploader 已补「duplicate 时同步删桶文件」，
本脚本作为兜底定期清扫（建议每月跑一次；也可观察云开发控制台「容量」面板酌情）。

用法（在仓库根目录，用 .venv 解释器）：
  .venv/Scripts/python.exe tools/orphan_cleanup.py            # dry-run：只出报告
  .venv/Scripts/python.exe tools/orphan_cleanup.py --delete   # 真删（审计日志在 %TEMP%）

白名单 = images 集合全部 fileID + qrcode 集合全部 fileID（网关匿名查询，与 qqbot
mouyu_forward 同款链路：signin 需 x-device-id 头）。删除三重保险：
  1. 只删 memes/ 前缀，其他前缀只报告不动手；
  2. Key 不在白名单；
  3. LastModified 距今 > 3 天（防在途上传）。
删除不可逆但安全：删的都是数据库无引用的孤儿；批删失败可安全重跑。
"""
import json, sys, time, uuid
from pathlib import Path
from collections import defaultdict

import requests

CONFIG = Path(__file__).parent / "uploader" / "config.json"
cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
cos = cfg.get("cos", {})
import os
SID = os.environ.get("TENCENT_SECRET_ID") or cos.get("secret_id", "")
SKEY = os.environ.get("TENCENT_SECRET_KEY") or cos.get("secret_key", "")
ENV_ID = cfg.get("env_id", "")
BUCKET = cos.get("bucket", "")
REGION = cos.get("region", "ap-shanghai")
assert SID and SKEY and ENV_ID and BUCKET, "配置缺失"

GATEWAY = f"https://{ENV_ID}.api.tcloudbasegateway.com"
DB_DOCS = f"{GATEWAY}/v1/database/instances/(default)/databases/(default)/collections"
DELETE_FLAG = "--delete" in sys.argv
NOW = time.time()


def unwrap(v):
    if isinstance(v, dict):
        return next(iter(v.values()), None)
    return v


def signin():
    r = requests.post(f"{GATEWAY}/auth/v1/signin/anonymously",
                      params={"client_id": ENV_ID}, json={},
                      headers={"x-device-id": uuid.uuid4().hex}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_fileids(token, collection):
    keys, status_seen = set(), defaultdict(int)
    offset, limit = 0, 100
    hdr = {"Authorization": f"Bearer {token}", "x-device-id": uuid.uuid4().hex}
    while True:
        params = {"offset": offset, "limit": limit,
                  "query": json.dumps({}), "order": json.dumps([])}
        r = requests.get(f"{DB_DOCS}/{collection}/documents",
                         params=params, headers=hdr, timeout=30)
        r.raise_for_status()
        docs = r.json().get("list") or []
        if not docs:
            break
        for d in docs:
            status_seen[unwrap(d.get("status"))] += 1
            fid = unwrap(d.get("fileID"))
            if isinstance(fid, str) and fid.startswith("cloud://"):
                prefix = f"cloud://{ENV_ID}.{BUCKET}/"
                if fid.startswith(prefix):
                    keys.add(fid[len(prefix):])
                else:
                    print(f"  [警告] fileID 前缀异常: {fid[:80]}")
        offset += limit
        if len(docs) < limit:
            break
    return keys, status_seen


def main():
    print("== 1) 建白名单（数据库引用的文件）==", flush=True)
    token = signin()
    img_keys, img_status = fetch_fileids(token, "images")
    print(f"images: {sum(img_status.values())} 条记录, 提取到 {len(img_keys)} 个文件Key; 状态分布={dict(img_status)}", flush=True)
    qr_keys, _ = fetch_fileids(token, "qrcode")
    print(f"qrcode: 提取到 {len(qr_keys)} 个文件Key", flush=True)
    whitelist = img_keys | qr_keys
    if len(whitelist) < 500:
        print(f"[中止] 白名单仅 {len(whitelist)} 项，远低于预期，疑似查询异常，拒绝继续。", flush=True)
        return 2

    print("\n== 2) 拉桶清单 ==", flush=True)
    from qcloud_cos import CosConfig, CosS3Client
    client = CosS3Client(CosConfig(Region=REGION, SecretId=SID, SecretKey=SKEY))
    all_objs, marker = [], ""
    while True:
        kw = dict(Bucket=BUCKET, MaxKeys=1000)
        if marker:
            kw["Marker"] = marker
        resp = client.list_objects(**kw)
        batch = resp.get("Contents") or []
        if not batch:
            break
        all_objs.extend((c["Key"], int(c["Size"]), c["LastModified"]) for c in batch)
        if resp.get("IsTruncated") != "true":
            break
        marker = batch[-1]["Key"]
    print(f"桶内对象: {len(all_objs)} 个", flush=True)

    MB = 1024 * 1024
    orphans, kept_whitelist, kept_outside, kept_recent = [], [], [], []
    orphan_bytes = 0
    by_month = defaultdict(lambda: [0, 0])
    for key, size, lm in all_objs:
        if key in whitelist:
            kept_whitelist.append(key)
            continue
        if not key.startswith("memes/"):
            kept_outside.append((key, size))
            continue
        age_days = NOW - lm.timestamp() if hasattr(lm, "timestamp") else NOW
        if age_days <= 3 * 86400:
            kept_recent.append((key, size))
            continue
        orphans.append(key)
        orphan_bytes += size
        parts = key.split("/")
        month = "/".join(parts[:2]) if len(parts) > 2 else "(桶根目录)"
        by_month[month][0] += 1
        by_month[month][1] += size

    print(f"\n== 3) 对账报告（{'DELETE 模式' if DELETE_FLAG else 'DRY-RUN 模式'}）==", flush=True)
    print(f"白名单命中(保留): {len(kept_whitelist)} 个", flush=True)
    print(f"memes/ 外(保留+需人工看): {len(kept_outside)} 个", flush=True)
    for k, s in kept_outside[:20]:
        print(f"    {s/MB:8.2f} MB  {k[:80]}", flush=True)
    print(f"孤儿但<3天(保留,防在途): {len(kept_recent)} 个", flush=True)
    print(f"可删孤儿: {len(orphans)} 个, {orphan_bytes/MB:.0f} MB = {orphan_bytes/1024/MB:.2f} GB", flush=True)
    for month, (n, b) in sorted(by_month.items()):
        print(f"    {month}: {n:6d} 个  {b/MB:8.0f} MB", flush=True)
    print("\n可删样本(前10):", flush=True)
    for k in orphans[:10]:
        print(f"    {k[:90]}", flush=True)

    if not DELETE_FLAG:
        print("\n[DRY-RUN] 未删除任何文件。确认后加 --delete 执行。", flush=True)
        return 0

    print("\n== 4) 开始删除 ==", flush=True)
    audit = Path(os.environ.get("TEMP", "/tmp")) / "orphan_cleanup_audit.log"
    with audit.open("w", encoding="utf-8") as f:
        for i in range(0, len(orphans), 1000):
            chunk = orphans[i:i + 1000]
            # SDK 键名是单数 Object（不是 Objects），拼错会报 InvalidArgument
            resp = client.delete_objects(Bucket=BUCKET,
                                         Delete={"Object": [{"Key": k} for k in chunk], "Quiet": "true"})
            errs = resp.get("Error") or []
            f.write("\n".join(chunk) + "\n")
            print(f"  已删 {min(i + 1000, len(orphans))}/{len(orphans)} (失败 {len(errs)})", flush=True)
            if errs:
                for e in errs[:5]:
                    print(f"    失败样例: {e}", flush=True)
    print(f"审计日志: {audit}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
