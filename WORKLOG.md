# WORKLOG

> 工作日志，最新在前。任务完成或归档时在顶部追加一条。新对话先读这里续接。

## 2026-08-27 审核三态勾选框 + 转发群组分类 + 工具改开本地后台

- **改动**（`admin/admin.html`）：
  - 图片状态机新增 **status=3 转发群组**：不进小程序随机池（getRandomImage 只查 status=1）、autoCleanup 不删它（只删 2/0）、云函数零改动（review/getList 按传参工作）
  - 宫格审核勾选框**三态循环**：空 → 填满(绿,过审 status=1) → 打勾(橙✓,转发 status=3) → 空；`selectedMap` 值从 bool 改 0/1/2；勾选框 24px→30px 加大
  - 批量按钮文案改「填满过审，打勾转发，未选删除」+ 颜色图例；全选 = 全部填满 / 再点清空
  - 新 tab「转发群组」（已通过后面）：复用 `loadImages(3)` 通用列表，含通过(转回已通过)/删除/批量删除/预览；顶部统计栏加转发群组计数
  - 顺手修复：已拒绝 tab 的「通过」按钮此前误刷待审核列表（`reviewImage` 增加 `fromStatus` 参数；批量操作改用 `reviewImageRequest` 统一刷新）
- **改动**（`tools/gui.py` + 重建 `木偶鱼工具.exe`）：
  - 「打开审核」改为内置 ThreadingHTTPServer（localhost:9000 serve `admin/` 目录）后打开 `http://localhost:9000/admin.html`；admin.html 缺失回退托管版；端口被占则复用现有服务
  - **修复 windowed exe 下 ERR_EMPTY_RESPONSE**：console=False 的 exe 里 sys.stderr 为 None，SimpleHTTPRequestHandler 每请求写访问日志抛异常掐断连接（用户实测浏览器 ERR_EMPTY_RESPONSE，curl/python 控制台正常所以先前未暴露）。覆写 `_QuietAdminHandler.log_message` + `_QuietAdminServer.handle_error` 静默，serve 线程加异常兜底日志；stderr=None 模拟复现并验证修复（200 OK），exe 已重建
- **验证**：inline script node 语法检查通过；mock 测试壳浏览器实测三态/统计/tab，用户人工确认点击正常；本地真实后台 openid 登录读数 待审核194/已通过587/转发0/已拒绝0；gui 本地服务单测（起服务/页面200含转发群组/复用）通过；exe 重建冒烟（进程存活）通过
- **注意**：线上托管版 admin.html 仍是 7-26（a39af08）旧代码，无本次新功能，用户决定暂不管；`tdl_downloader_v2.py` 内 ADMIN_URL 仍指托管版（仅日志提示用），未改
- **提交**：`feat(admin)` 三态+转发群组、`feat(tools)` 本地审核链接+exe

## 2026-07-26 换号后封装登录/加群 + 缓存清理拆分 + 八宫格十二宫格

- **背景**：tdl 换 Telegram 账号，新会话写入 default namespace，社群需重新加。
- **改动**（`tools/tdl_downloader/tdl_downloader_v2.py`，提交 `70a74c5`）：
  - CLI 重构：`sys.argv` -> argparse
  - `--login [desktop|code|qr]`：清理残留进程后调起交互式登录，完成后自动验证（实测 1.3s 判定已登录）
  - `--check-channels`：用 `chat ls -o json` 对比 CHANNELS 配置，列出已加入/未加入；未加入输出 t.me 链接（tdl 无 join 命令）
  - 缓存清理拆分：原「清理缓存 y/N」拆为 1.清md5_cache 2.清progress_cache 3.全清 N.保留；默认保留，去重与进度解耦
- **改动**（`admin/admin.html`，提交 `a39af08`）：
  - 八宫格长图截断：`clampLongImage` 在 onload 按原图比例判定，长图（高>宽×1.8）内联设 max-height 截断，短图原比例不拉伸
  - 审核模式下拉新增「十二宫格 (12张)」，4列×3行，按钮文案三档映射
- **数据状态**（重要）：用户误勾清理缓存导致 md5_cache 从 22275 条清空到 277 条，progress_cache 从 5 频道变 2 频道。用户选择不恢复 git 历史，从头累积。git 历史的 22275 条仍可恢复（如需）。
- **待验证**：`--check-channels` 真实运行（下载进程占用数据库锁，未实测解析）；换号后重新下载已触发，部分频道全量重下。
- **下一步**：等下载结束后实测 `--check-channels`；观察新去重 size 预筛在真实流量下的效果。

## 2026-07-09 tdl_downloader 三项修复 + 八宫格截断调整

- **改动**（`tools/tdl_downloader/tdl_downloader_v2.py`，提交 `ebd0650` 已 push）：
  1. **看门狗误杀修复**：批量跳过重复文件时 tdl 不写新文件、stdout 只输出被过滤的进度条，看门狗两个进展信号同时失效被误判卡死。`_read_process_output` 新增 `last_activity_time`（含被过滤行），看门狗优先用进程活跃度判断；重试超时不再降到 15s，统一 60s；删除无用 `NO_OUTPUT_TIMEOUT_RETRY`。
  2. **登录检查误判修复**：原用 `chat export --with-content` 拉内容验证登录，限速被误判为未登录。改用 `chat ls`（只列对话不拉内容）；严格三分法（not authorized 才判未登录，其它失败重试 3 次间隔 5s，超时 60s->30s）；提示语区分未登录 vs 限速。实测 1.8s 判定。
  3. **去重 size 预筛**：缓存新增 `size` 字段 + `size->[md5]` 索引。size 在缓存从未出现 -> 必为新图免算 MD5 直接入库；size 命中候选 -> 算 MD5 确认。基于"文件相同->size必相同"逆否命题，老缓存缺 size 时兜底回填。单元测试 4 场景全过。
- **改动**（`admin/admin.html`，**未提交**）：八宫格缩略图从 `aspect-ratio:1;object-fit:cover` 改为 `max-height:300px;object-fit:cover`，只截断超长图，普通图完整显示不影响审核。点击放大看原图（已有 modal）。仍待用户确认效果后提交。
- **验证**：去重逻辑单测 4 场景全过；登录检查实测 1.8s 判定已登录；py_compile 通过。
- **下一步**：admin.html 八宫格改动待用户确认效果后提交；其它工作区改动（tdl-export.json / md5_cache.json / uploader 等）非本次范围，未动。

## 2026-07-08 取消每日定时任务邮件 + 修复八宫格长图拉长

- **改动**：
  - `.github/workflows/daily-job.yml`：注释 `schedule` cron，仅保留 `workflow_dispatch` 手动触发 -> 不再每天自动跑、不再发成功/失败邮件。
  - `admin/admin.html`：`.batch-review-item img` 加 `aspect-ratio:1; object-fit:cover`，长图不再无限拉长；点击放大（`openPreview` modal，已有）看完整原图。（注：此方案后于 07-09 改为 max-height 截断，见上条）
- **提交**：`bfc4d3c`（已 push master）。
- **验证**：CSS 改动复用 `.grid-item-large img` 已验证模式；放大 modal 代码已存在无需新增。
- **下一步**：无。其它工作区改动（tdl-export.json / md5_cache.json / uploader 等）未提交，保持原样。

## 2026-06-15 初始化
- 项目 AI 配置初始化：CLAUDE.md + AGENTS.md 软链 + WORKLOG 规范接入
- 改动文件：CLAUDE.md, AGENTS.md(软链), WORKLOG.md
