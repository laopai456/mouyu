"""查询云端图片统计（待审核/已通过/已拒绝）—— GUI 顶部计数用。

SCF 直调 admin 云函数 getStats（adminOpenid 走白名单鉴权，须在 admin 函数的
ADMIN_OPENIDS 环境变量里）。独立于 gui.py 运行：GUI（含打包后的 exe）用
.venv 解释器起子进程跑本脚本，stdout 只输出一行 CLOUD_STATS_JSON {...}
便于 GUI 解析（stderr 可能混有 SDK 噪音）。凭据与 uploader 同源：
环境变量 TENCENT_SECRET_ID/KEY 优先，其次 tools/uploader/config.json 的 cos 段。
"""

import json
import logging
import os
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "uploader" / "config.json"

OUT_MARK = "CLOUD_STATS_JSON "


def emit(payload: dict):
    print(OUT_MARK + json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> int:
    # 屏蔽 SDK 的 WARNING 噪音，保持 stdout 干净
    logging.getLogger("tencentcloud").setLevel(logging.CRITICAL)

    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        emit({"ok": False, "error": f"读取配置失败: {e}"})
        return 1

    cos_cfg = config.get("cos", {})
    secret_id = os.environ.get("TENCENT_SECRET_ID") or cos_cfg.get("secret_id", "")
    secret_key = os.environ.get("TENCENT_SECRET_KEY") or cos_cfg.get("secret_key", "")
    env_id = config.get("env_id", "")
    developer_openid = config.get("developer_openid", "")
    region = cos_cfg.get("region", "ap-shanghai")

    if not (secret_id and secret_key and env_id):
        emit({"ok": False, "error": "缺少 secret_id/secret_key/env_id 配置"})
        return 1

    try:
        from tencentcloud.common import credential
        from tencentcloud.scf.v20180416 import scf_client, models

        client = scf_client.ScfClient(credential.Credential(secret_id, secret_key), region)
        req = models.InvokeRequest()
        req.FunctionName = "admin"
        req.Namespace = env_id
        req.ClientContext = json.dumps(
            {"action": "getStats", "adminOpenid": developer_openid},
            ensure_ascii=False,
        )
        resp = client.Invoke(req)
        ret = json.loads(resp.Result.RetMsg)
    except json.JSONDecodeError:
        emit({"ok": False, "error": "云函数返回不是 JSON（检查 admin 函数部署状态）"})
        return 1
    except Exception as e:
        emit({"ok": False, "error": str(e)})
        return 1

    if ret.get("success"):
        emit({"ok": True, **ret.get("stats", {})})
        return 0
    emit({"ok": False, "error": ret.get("msg", "未知错误")})
    return 1


if __name__ == "__main__":
    sys.exit(main())
