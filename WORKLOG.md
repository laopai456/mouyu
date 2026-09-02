# WORKLOG

> 工作日志，最新在前。任务完成或归档时在顶部追加一条。新对话先读这里续接。

## 2026-09-02 admin 批量上传 → 重新载入

- **需求**：图片上传实际走 uploader.py（COS 直传），admin 页里的批量上传是冗余功能，改成一键「重新载入」——刷新顶部统计数量 + 当前 tab 的图片列表。
- **改动**（`admin/admin.html`）：
  - tab 栏「批量上传」→「🔄 重新载入」按钮（紫色强调样式，非 tab，不切页），点击调用新增 `reloadAll()`：`loadStats()` + 按 `currentTab` 刷新对应列表（pending→`loadBatchImages`，passed/forward/rejected→`loadImages`，qrcode→`loadQRCode`，monthDelete→`loadMonthList`）。
  - 整块移除上传功能：uploadTab HTML（拖拽区/预览/开始上传）、`setupDropZone/handleFiles/renderPreview/removeFile/clearPreview/calculateMD5/startUpload` 全部 JS、`selectedFiles` 变量、`drop-zone/preview-item/upload-actions` CSS、spark-md5 CDN 引用。二维码上传（`saveQRCode`，走 uploadFile 云函数）是独立逻辑，保留未动。
  - `switchTab` 增加 `currentTab` 跟踪（初始 'qrcode'，与 HTML 默认 active 一致）。
- **验证**：内联 script `node --check` 通过；div/button 标签配平（112/112、35/35）；本地 http.server 起服 curl 确认页面含「重新载入」且无批量上传残留；无任何对已删符号的悬空引用（grep 全空）。
- **注意**：admin.html 由本地工具（exe 内嵌 server，no-store）直出磁盘文件，无需重打包；浏览器强刷即生效。若当时 9000 端口的旧服务被误杀，点工具里「打开审核」会自动重启。

## 2026-09-02 md5 查重补上 status=3（转发群组）口径

- **问题**：一张图被勾成转发群组（status=3）后，三条上传通道的 md5 查重都不含 3——同图可再次入库（admin 批量上传查 {0,1}，autoUpload/addImage 云函数查 {0,1,2}）。qqbot 群收集与 admin 手动互查时都会漏。
- **改动**：`cloudfunctions/autoUpload/index.js`、`cloudfunctions/addImage/index.js` 查重改为 `in([0,1,2,3])`；`admin/admin.html` 批量上传查重改为 `in([0,1,3])`——status=2（拒绝）在 admin 端**有意**保持不拦（被拒的图允许手动重传），收集端云函数仍拦 2（自动管线不收死图）。
- **未动**：`cosUploadHandler`（COS 事件兜底通道，事件里拿不到 md5，只能按 fileID 去重）。
- **验证**：三个文件语法检查通过（node --check / 内联 script 提取检查）。
- **待办（人工）**：autoUpload、addImage 两个云函数需在微信开发者工具右键「上传并部署：云端安装依赖」重新部署后才在云端生效；admin.html 由本地工具直出（no-store），强刷即生效。已入库的历史重复不追溯，仅拦新增。

## 2026-08-30 云开发到期迁移预案（mouyu env → july env）

- **产出**（**预案未执行**，触发条件=云开发套餐到期不续）：
  - `docs/migration-cloudbase-to-july.md`：完整迁移方案。核心拓扑已核对（2026-08-30）：mouyu env `MOYU_ENV_ID_PLACEHOLDER`（appid touristappid，桶 `636c-...-1414730090` ap-shanghai）→ july env `JULY_ENV_ID_PLACEHOLDER`（appid JULY_APPID_PLACEHOLDER，西瓜太浪hd）
  - 关键决策：①mouyu 6 集合迁入加 `mouyu_` 前缀（july 有同名 `users` 集合，必冲突）②fileID 全量改写（`cloud://env.bucket/key` 双变化，images 的 fileID+url 两字段）③COS 服务端桶到桶 copyObject（不落本地）④保留 _id（qqbot mouyu_state 不重推）⑤只增不删→回滚=各端 env 指回旧环境
  - `tools/migration/`：4 个可直接跑的 Node 脚本（01 导出+fileID映射 / 02 桶拷贝带断点 / 03 导入加前缀改fileID幂等 / 04 对账验证），全部支持 --dry-run；依赖 `npm i`（@cloudbase/node-sdk + cos-nodejs-sdk-v5）；config.json 放真实密钥已 gitignore（模板 config.example.json）
  - 代码改动清单（集合改名波及面）已列进方案 §5.1：13 云函数 + admin.html + qqbot mouyu_forward.py(L77 集合路径) + uploader config + gui/tdl 的 ADMIN_URL
- **验证**：4 脚本 node --check 通过；json 模板可解析。未连真实环境跑（按需求"现在不用"）
- **执行前置**（方案 §0）：两小程序同主体确认、july 默认桶名/地域查填、密钥有 TCB+COS 权限、旧环境到期≥7 天

## 2026-08-30 admin 审核新增十六宫格

- **改动**（`admin/admin.html`）：宫格下拉新增「十六宫格 (16张)」，按钮文案映射表加 `16:'十六'`。列数固定 4 列不动，16 张即 4 行，`.limit(gridSize)` 原本就参数化，无其它改动。
- **验证**：内联 script 语法检查通过；两处标记 grep 确认。
- **修复**（`tools/gui.py` + 重建 exe）：用户反馈「新打开的页面没有十六宫格」——排查为**浏览器 heuristic 缓存旧 admin.html**（服务端文件与 curl 实测均已是新版）。`_QuietAdminHandler` 加 `Cache-Control: no-store` 响应头，本地服务不再被缓存，以后改 admin.html 即点即新。模拟验证 no-store 生效 + 内容含十六宫格，exe 重建。用户侧需：关旧工具开新 exe + 浏览器 Ctrl+F5 强刷一次。

## 2026-08-28 工具加机器人控制三按钮 + 日志左右分屏

- **改动**（`tools/gui.py` + 重建 `木偶鱼工具.exe`）：
  - 第三行按钮：🤖 启动机器人 / ⏹ 停止机器人 / 🧹 清理所有进程（互斥禁用，后台线程执行，过程写机器人日志面板）
    - 启动 = 删 `logs\STOPPED` + NapCat 不在才经计划任务拉起（在跑则跳过，防重启 QQ 触发风控）+ 8080 未监听才 wscript `silent_start_bot.vbs`
    - 停止 = 写 STOPPED + 杀 8080 监听 python 及所有 cmdline 含 bot.py 的 python（含历史残留实例），**不动 NapCat/QQ**
    - 清理 = 跑 qqbot `一键停止.bat /auto`（bot + NapCat/QQ + 看门狗暂停，GBK 输出流式回显）+ 兜底清 bot.py 残留
  - 日志区改左右分屏（`ttk.PanedWindow`）：左侧工具日志原样；右侧机器人日志 = 每秒 tail `qqbot/logs/bot.log`（UTF-8 解码、剥 loguru ANSI 色码、打开回看末 8KB、超 10MB 轮转自动重置、3000 行封顶），与状态面板同源，bot 由谁启动都能看
  - 窗口 800x600 → 1000x620
- **验证**：py_compile 通过；只读探测单测（8080 监听=True、NapCat=True、枚举到 2 个 bot.py 含残留旧实例）；GUI 冒烟（分屏两面板就位、botlog 实时追到当前秒日志、无 ANSI 残留、半截首行已跳过）；exe 重建 → 覆盖根目录 → 5 秒存活冒烟通过
- **注意**：本机 Python 子进程 text 模式默认 UTF-8，而 netstat/tasklist/wmic 输出 GBK，`subprocess.run(..., text=True)` 会解码崩——所有系统命令捕获显式 `encoding="gbk", errors="replace"`

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
