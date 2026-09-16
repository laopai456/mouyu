# -*- coding: utf-8 -*-
"""
煎蛋无聊图日报抓取器（慢速拟人版）

数据源（前端 SPA 同款接口，无需登录）：
  1. GET /api/v1/daily-hot/reports?page=1&page_size=50   → 日报日期列表
  2. GET /api/v1/daily-hot/comments?date=YYYY-MM-DD&sort=vote_desc&page=N&page_size=50&from=weixin
     → 当日热门吐槽，content 字段内嵌 <img src>，图床为 img.toto.im / img.wangmoyu.com 等
     注：未登录只有「微信来源(from=weixin) + 昨天日报」能拿全量分页（~50 条/天），
     其余日期无论怎么传参都只有赞数 top10——最新一份日报永远是"昨天"，正好全量覆盖。

拟人策略（默认参数刻意保守，慢是特性不是缺陷）：
  - 整轮固定一个真实 Chrome UA + 完整浏览器头（API 仿 axios，图片仿 <img> 加载）
  - requests.Session 复用连接 + 保留服务端下发的 cookie
  - 请求间隔在区间内随机抖动；每 15~25 个请求随机长歇 0.5~1.5 分钟（像人在翻页看图）
  - 启动前随机等待，避免定时任务每次在同一秒打点
  - 429/5xx 指数退避重试，连续失败即整轮收手装死，下轮再续
  - 图片连续失败达阈值即熔断装死（疑似被图床限流时立即收手）
  - 目标文件已存在则幂等跳过（增量状态丢失也不会重复下载）
  - 每轮滴灌式上限（默认 50 图 / 10 个 API 页），跑完静默退出，增量状态记在 cache/state.json

产物落盘到 save_dir（默认 C:\\Users\\w\\Downloads\\jandan），由 uploader 的 watch_folders
接力上传 COS（uploader 侧还有 md5 去重兜底）。

用法：
  py tools/jandan/jandan_scraper.py                     # 默认慢速滴灌
  py tools/jandan/jandan_scraper.py --max-images 5      # 临时改上限
  py tools/jandan/jandan_scraper.py --dry-run           # 只看候选不下载
  py tools/jandan/jandan_scraper.py --delay-scale 0.2   # 测试用：等比压缩所有延迟（勿常驻）
可选 tools/jandan/config.json 覆盖默认参数（键同 DEFAULT_CONFIG，运行时目录不入库）。
"""

import argparse
import json
import logging
import random
import re
import sys
import time
import warnings
from pathlib import Path

# venv 里 requests 启动自检的提示性告警（urllib3 版本不匹配），不影响功能，别污染 GUI 日志
warnings.filterwarnings("ignore", message=".*doesn't match a supported version.*")

import requests

BASE = "https://jandan.net"
REPORTS_URL = f"{BASE}/api/v1/daily-hot/reports"
COMMENTS_URL = f"{BASE}/api/v1/daily-hot/comments"
PAGE_URL = f"{BASE}/new/daily"

# 近两年主流桌面 Chrome，轮换太勤反而假，整轮抽一个固定用
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

IMG_URL_RE = re.compile(r'<img\s[^>]*?src="(https?://[^"]+)"', re.I)
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MIN_BYTES, MAX_BYTES = 5 * 1024, 25 * 1024 * 1024

DEFAULT_CONFIG = {
    "save_dir": r"C:\Users\w\Downloads\jandan",
    "api_delay_range": [6, 15],        # API 请求间隔（秒，区间随机）
    "img_delay_range": [5, 12],        # 图片下载间隔（秒，区间随机；真人浏览器秒级并行拉几十张，这已约其 1/20 强度）
    "rest_every_range": [15, 25],      # 每随机 N 个请求歇一会儿
    "rest_range": [30, 90],            # 长歇时长（秒）
    "start_jitter_range": [10, 70],    # 启动前随机等待（秒）
    "max_images_per_run": 300,         # 单轮图片安全上限，0=不限制（有多少下多少）；两天窗口实际全量约100-120张，此值只兜底异常跑不完的情况
    "max_api_pages_per_run": 10,       # 每轮最多翻的 API 页数（weixin 全量态每日期仅 1-2 页）
    "min_vote_positive": 0,            # 吐槽最低赞数过滤（0=不限，日报本身已按热度排序）
    "page_size": 50,                   # 仿前端 pageSize=50；须配 from=weixin 才拿得到全量（服务端只对微信来源+昨天放行分页，其余只有赞数 top10）
    "max_consecutive_img_fail": 5,     # 图片连续失败 N 次即熔断装死（疑似被限流时立即收手）
    "backfill_days": 2,                # 只处理最新 N 天日报（默认 2：昨天+今天；旧的无时效性不回溯）
    "connect_timeout": 10,
    "read_timeout": 30,
    "max_retries": 3,
    "retry_backoff_range": [60, 120],  # 429/5xx 重试前退避（秒）
}

LOGGER = logging.getLogger("jandan")


# 控制台白名单：阶段/进度/收尾行。逐张明细（IMG_OK/IMG_SKIP/IMG_HAVE/PACE_WAIT）只进文件不进控制台
CONSOLE_PHASE_KEYWORDS = (
    "JANDAN_RUN_START", "JANDAN_RUN_END", "JANDAN_REPORTS_OK",
    "JANDAN_DATE_START", "JANDAN_DATE_DONE", "JANDAN_PAGE_OK", "JANDAN_PAGE_DUP",
    "JANDAN_PROGRESS", "JANDAN_CAP_REACHED", "JANDAN_ABORT",
    "JANDAN_CONFIG_LOADED", "JANDAN_CONFIG_BAD",
)


class _ConsolePhaseFilter(logging.Filter):
    """WARNING+ 一律放行；INFO 按 CONSOLE_PHASE_KEYWORDS 白名单放行"""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        msg = record.getMessage()
        return any(k in msg for k in CONSOLE_PHASE_KEYWORDS)


def setup_logging(log_dir: Path, console_info: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(log_dir / "jandan.log", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    # 控制台：WARNING+（失败/退避/熔断）全出；INFO 只出白名单阶段行，GUI 日志不刷屏。
    # --console-info 才放全量逐张明细（排障用）
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    if not console_info:
        sh.addFilter(_ConsolePhaseFilter())
    LOGGER.addHandler(fh)
    LOGGER.addHandler(sh)
    LOGGER.setLevel(logging.INFO)


def load_config(base_dir: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg_file = base_dir / "config.json"
    if cfg_file.exists():
        try:
            cfg.update(json.loads(cfg_file.read_text(encoding="utf-8")))
            LOGGER.info("JANDAN_CONFIG_LOADED 覆盖默认配置: %s", cfg_file)
        except (json.JSONDecodeError, OSError) as e:
            LOGGER.warning("JANDAN_CONFIG_BAD 配置读取失败，用默认值: %s", e)
    return cfg


def load_state(cache_dir: Path) -> dict:
    f = cache_dir / "state.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            LOGGER.warning("JANDAN_STATE_BAD 状态文件损坏，从头开始（uploader md5 去重兜底）")
    return {"seen_comment_ids": {}, "done_dates": []}


def save_state(cache_dir: Path, state: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / "state.json"
    f.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


class HumanPacer:
    """拟人节奏器：抖动间隔 + 周期性长歇 + 可整体缩放（测试用）"""

    def __init__(self, cfg: dict, scale: float):
        self.cfg = cfg
        self.scale = max(0.0, scale)
        self._req_count = 0
        self._rest_at = random.randint(*cfg["rest_every_range"])

    def _sleep(self, sec: float, reason: str) -> None:
        sec = sec * self.scale
        if sec > 0:
            LOGGER.info("JANDAN_PACE_WAIT %s %.1fs", reason, sec)
            time.sleep(sec)

    def pace(self, kind: str) -> None:
        lo, hi = self.cfg[f"{kind}_delay_range"]
        self._sleep(random.uniform(lo, hi), f"{kind}_delay")
        self._req_count += 1
        if self._req_count >= self._rest_at:
            lo, hi = self.cfg["rest_range"]
            self._sleep(random.uniform(lo, hi), "rest")
            self._rest_at = self._req_count + random.randint(*self.cfg["rest_every_range"])


class JandanScraper:
    def __init__(self, cfg: dict, dry_run: bool, scale: float):
        self.cfg = cfg
        self.dry_run = dry_run
        self.pacer = HumanPacer(cfg, scale)
        self.state = load_state(Path(__file__).parent / "cache")
        self.save_dir = Path(cfg["save_dir"])
        if not self.dry_run:
            self.save_dir.mkdir(parents=True, exist_ok=True)
        self.downloaded = 0
        self.pages_used = 0
        self.img_fail_streak = 0
        self.stop_reason = None

        self.sess = requests.Session()
        self.sess.headers.update({
            "User-Agent": random.choice(UA_POOL),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

    # ---------- 底层请求 ----------

    def _get(self, url: str, headers: dict, **kw) -> requests.Response:
        timeout = (self.cfg["connect_timeout"], self.cfg["read_timeout"])
        last_exc = None
        for attempt in range(1, self.cfg["max_retries"] + 1):
            try:
                r = self.sess.get(url, headers=headers, timeout=timeout, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                return r
            except requests.RequestException as e:
                last_exc = e
                if attempt >= self.cfg["max_retries"]:
                    break
                lo, hi = self.cfg["retry_backoff_range"]
                wait = random.uniform(lo, hi) * attempt
                LOGGER.warning("JANDAN_BACKOFF 第%d次失败(%s) 退避%.0fs", attempt, e, wait)
                time.sleep(wait * self.pacer.scale)
        raise last_exc

    def get_reports(self) -> list:
        # 先像真人一样"打开页面"（CDN 缓存的 SPA 壳，顺带预热 cookie），再调接口
        self.pacer.pace("api")
        self._get(PAGE_URL, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": "https://jandan.net/",
        })
        self.pacer.pace("api")
        r = self._get(REPORTS_URL, params={"page": 1, "page_size": 50}, headers={
            "Accept": "application/json, text/plain, */*",   # 仿站内 axios
            "Referer": PAGE_URL,
        })
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"reports 接口返回 code={data.get('code')} msg={data.get('msg')}")
        dates = [item["report_date"] for item in data["data"]["list"]]
        LOGGER.info("JANDAN_REPORTS_OK 共%d天日报 最新%s", len(dates), dates[0] if dates else "-")
        return dates

    def get_comments(self, date: str, page: int) -> dict:
        self.pacer.pace("api")
        self.pages_used += 1
        r = self._get(COMMENTS_URL, params={
            "date": date, "sort": "vote_desc", "page": page,
            "page_size": self.cfg["page_size"],
            # 未登录时服务端仅对「微信来源的昨天日报」放行全量分页（对齐前端 isWeixinYesterday 逻辑）；
            # 其余日期带了也只回 top10，无副作用
            "from": "weixin",
        }, headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{PAGE_URL}/date/{date}",
        })
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"comments 接口返回 code={data.get('code')} msg={data.get('msg')}")
        return data["data"]

    # ---------- 图片 ----------

    def _img_fail(self, level: int, comment_id: int, msg: str) -> None:
        """图片失败/跳过统一入口：连击计数，连续失败达到阈值即熔断装死（疑似被限流）"""
        LOGGER.log(level, msg)
        self.img_fail_streak += 1
        if self.img_fail_streak >= self.cfg["max_consecutive_img_fail"]:
            self.stop_reason = f"图片连续失败{self.img_fail_streak}次，疑似被限流，装死收工"
            LOGGER.warning("JANDAN_IMG_BREAKER %s", self.stop_reason)

    def download_image(self, url: str, comment_id: int, idx: int) -> bool:
        ext = Path(url.split("?")[0]).suffix.lower()
        if ext not in ALLOWED_EXTS:
            ext = ""  # 从 Content-Type 补
        path = self.save_dir / f"{comment_id}_{idx}{ext}"

        # 幂等兜底：目标文件已在本地（状态文件丢失/重置过也不重复下载、不报错）
        if not self.dry_run and path.exists():
            LOGGER.info("JANDAN_IMG_HAVE id=%s 本地已存在 %s", comment_id, path.name)
            return True

        self.pacer.pace("img")
        try:
            r = self._get(url, headers={
                # 仿浏览器加载 <img>：页面同源 Referer + 图片专用 Accept
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Referer": f"{BASE}/",
            }, stream=True)
        except requests.RequestException as e:
            self._img_fail(logging.ERROR, comment_id, f"JANDAN_IMG_FAIL id={comment_id} {url} err={e}")
            return False

        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if r.status_code == 404 or "text/html" in ctype:
            self._img_fail(logging.WARNING, comment_id, f"JANDAN_IMG_SKIP id={comment_id} 无效资源({ctype or r.status_code}) {url}")
            return False
        if not ctype.startswith("image/"):
            self._img_fail(logging.WARNING, comment_id, f"JANDAN_IMG_SKIP id={comment_id} 非图片Content-Type={ctype} {url}")
            return False
        if not ext:
            ext = "." + (ctype.split("/", 1)[1] if "/" in ctype else "jpg")
            ext = ext.replace("jpeg", "jpg")
            path = self.save_dir / f"{comment_id}_{idx}{ext}"

        if self.dry_run:
            LOGGER.info("JANDAN_CAND(DRY) id=%s %s", comment_id, url)
            return True

        size = 0
        tmp = path.with_suffix(path.suffix + ".part")
        try:
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("超过大小上限")
                    f.write(chunk)
            if size < MIN_BYTES:
                tmp.unlink(missing_ok=True)
                self._img_fail(logging.WARNING, comment_id, f"JANDAN_IMG_SKIP id={comment_id} 过小{size}B {url}")
                return False
            tmp.rename(path)
        except Exception as e:  # 下载中途断流/超大
            tmp.unlink(missing_ok=True)
            self._img_fail(logging.ERROR, comment_id, f"JANDAN_IMG_FAIL id={comment_id} size={size}B err={e} {url}")
            return False

        self.downloaded += 1
        self.img_fail_streak = 0
        LOGGER.info("JANDAN_IMG_OK id=%s %dB %s", comment_id, size, path.name)
        if self.downloaded % 10 == 0:
            LOGGER.info("JANDAN_PROGRESS 本轮已下载%d张", self.downloaded)
        return True

    # ---------- 主流程 ----------

    def run(self) -> None:
        cache_dir = Path(__file__).parent / "cache"
        dates = self.get_reports()[: self.cfg["backfill_days"]]
        done = set(self.state["done_dates"])
        seen = self.state["seen_comment_ids"]
        candidates = 0

        for date in dates:
            if self.stop_reason:
                break
            # 不按 done_dates 跳过：窗口内日报当天可能仍在滚动增长，每轮重扫，
            # 已处理过的评论靠 seen_comment_ids 去重（秒过，不重复下载）
            page, date_done = 1, False
            LOGGER.info("JANDAN_DATE_START %s 扫描中", date)
            while not date_done and not self.stop_reason:
                if self.pages_used >= self.cfg["max_api_pages_per_run"]:
                    self.stop_reason = f"API页数达上限{self.cfg['max_api_pages_per_run']}"
                    LOGGER.info("JANDAN_CAP_REACHED %s", self.stop_reason)
                    break
                try:
                    data = self.get_comments(date, page)
                except (RuntimeError, requests.RequestException, ValueError) as e:
                    # 连续退避重试后仍失败：装死收手，状态留在半途，下轮续传
                    self.stop_reason = f"接口异常:{e}"
                    LOGGER.error("JANDAN_ABORT %s", self.stop_reason)
                    break

                items = data.get("list") or []
                if not items:
                    date_done = True
                    break
                if page > 1 and all(item["id"] in seen for item in items):
                    # 接口实测 page 参数被忽略（p2 返回内容=p1），整页全已处理即停翻本日，省请求
                    LOGGER.info("JANDAN_PAGE_DUP %s p%d 整页与已处理重复，停翻本日", date, page)
                    date_done = True
                    break
                LOGGER.info("JANDAN_PAGE_OK %s p%d %d条", date, page, len(items))

                for item in items:
                    cid = item["id"]
                    if cid in seen:
                        continue
                    if item.get("vote_positive", 0) < self.cfg["min_vote_positive"]:
                        if not self.dry_run:
                            seen[cid] = {"date": date, "why": "low_vote"}
                        continue
                    urls = [u for u in IMG_URL_RE.findall(item.get("content") or "")]
                    if not urls:
                        if not self.dry_run:
                            seen[cid] = {"date": date, "why": "no_img"}
                        continue
                    candidates += len(urls)
                    ok_all = True
                    for i, u in enumerate(urls, 1):
                        if self.cfg["max_images_per_run"] and self.downloaded >= self.cfg["max_images_per_run"]:
                            self.stop_reason = f"图片数达上限{self.cfg['max_images_per_run']}"
                            LOGGER.info("JANDAN_CAP_REACHED %s", self.stop_reason)
                            ok_all = False
                            break
                        if not self.download_image(u, cid, i):
                            ok_all = False
                    # 无论成败都记 seen：失败项多为源已失效，不无限重试（uploader md5 兜底重复）
                    if not self.dry_run:
                        seen[cid] = {"date": date, "imgs": len(urls), "ok": ok_all}
                        save_state(cache_dir, self.state)
                    if self.stop_reason:
                        break

                total_pages = -(-data.get("total", 0) // self.cfg["page_size"])  # ceil
                page += 1
                if page > total_pages:
                    date_done = True

            if date_done and not self.stop_reason and not self.dry_run:
                done.add(date)
                self.state["done_dates"] = sorted(done)
                save_state(cache_dir, self.state)
                LOGGER.info("JANDAN_DATE_DONE %s", date)

        # 收尾
        LOGGER.info(
            "JANDAN_RUN_END 下载%d张 候选%d张 API页%d 已完成天数%d 停因=%s",
            self.downloaded, candidates, self.pages_used, len(done), self.stop_reason or "自然跑完",
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="煎蛋无聊图日报慢速抓取器")
    ap.add_argument("--max-images", type=int, help="本轮最多下载图片数（默认取配置）")
    ap.add_argument("--max-pages", type=int, help="本轮最多 API 页数（默认取配置）")
    ap.add_argument("--backfill-days", type=int, help="只抓最新 N 天日报（默认 2：昨天+今天）")
    ap.add_argument("--min-votes", type=int, help="最低赞数过滤（默认取配置）")
    ap.add_argument("--save-dir", help="图片保存目录（默认取配置）")
    ap.add_argument("--delay-scale", type=float, default=1.0,
                    help="所有延迟等比缩放，仅测试用（0.2=五分之一速）")
    ap.add_argument("--console-info", action="store_true",
                    help="控制台输出 INFO 级逐请求进度（GUI 按钮运行时用；默认只有告警/汇总）")
    ap.add_argument("--dry-run", action="store_true", help="只列候选图片不落盘")
    args = ap.parse_args()

    base_dir = Path(__file__).parent
    setup_logging(base_dir / "logs", console_info=args.console_info)
    cfg = load_config(base_dir)
    for k, a in (("max_images_per_run", args.max_images), ("max_api_pages_per_run", args.max_pages),
                 ("backfill_days", args.backfill_days), ("min_vote_positive", args.min_votes),
                 ("save_dir", args.save_dir)):
        if a is not None:
            cfg[k] = a

    jitter = random.uniform(*cfg["start_jitter_range"]) * max(0.0, args.delay_scale)
    LOGGER.info("JANDAN_RUN_START dry_run=%s 上限=图%d/页%s 启动等待%.0fs",
                args.dry_run, cfg["max_images_per_run"], cfg["max_api_pages_per_run"], jitter)
    time.sleep(jitter)

    try:
        JandanScraper(cfg, args.dry_run, args.delay_scale).run()
    except Exception:
        LOGGER.exception("JANDAN_FATAL 未预期异常")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
