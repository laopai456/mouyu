# WORKLOG

> 工作日志，最新在前。任务完成或归档时在顶部追加一条。新对话先读这里续接。

## 2026-09-06 工具「清理所有进程」→「打开面板」；qqbot 开机面板去误杀

- **需求**：工具内机器人日志面板与开机状态面板内容重复，且开机面板藏陷阱——`机器人控制台.vbs` 设计为关窗即跑一键停止.bat（bot+NapCat/QQ 全杀）。用户拍板：面板改纯展示（关窗不杀），工具里用不到的「清理所有进程」按钮换成「打开面板」。
- **改动**：
  - qqbot 仓库（b5eb89a）：`机器人控制台.vbs` 改 fire-and-forget（清 STOPPED 标志→弹面板→退出，GBK+CR-LF 重写），快捷方式描述同步，详见该仓库 WORKLOG。
  - `tools/gui.py`：`🧹 清理所有进程` → `📊 打开面板`；`_do_bot_clean`/`_run_bat_streamed`/`QQBOT_STOPALL_BAT` 死代码全删。**坑**：hidden 父进程（CREATE_NO_WINDOW）里 `cmd /c start` 弹的窗口不可见——必须对子进程直接用 `CREATE_NEW_CONSOLE` 才出真窗口（实测 Windows Terminal 弹出「QQ机器人 - 状态监控面板」）。
  - exe 重打包，根目录/dist 均已更新（打包时工具正开着锁文件，已关闭进程后换入，**用户需重开工具**）。
- **验证**：py_compile 过；CREATE_NEW_CONSOLE 弹窗实测出现面板标题；测试残留 status_dashboard 进程已清。
- **注意**：全量清退能力没有消失——qqbot 目录 `一键停止.bat` 仍在；工具里「停止机器人」仍是轻停（不动 NapCat/QQ）。

## 2026-09-06 exe 图标重制：白底细线鱼 → 透明底满格鱼（对齐灵感板观感）

- **需求**：「木偶鱼工具.exe 图标设置成和灵感工具一样大小」——灵感板.exe（`cc/兄弟你不死我怎么成神/`，桌面 lnk 解析目标）是满格像素画；旧鱼图标是**不透明白底方块**包细线圆环鱼，同尺寸下视觉小一圈。
- **改动**（`tools/icon.ico` + 重打包两个 exe）：边缘泛洪抠掉圆外白底（圆内白底是封闭域保留）→ 连通域分析清掉 77 个噪点碎块 → 内容居中放大撑满 256 画布（bbox 1,5,255,251）→ 多尺寸 ico（16–256 七档）→ pyinstaller 重打包，根目录与 dist 的 exe 均已更新，ExtractAssociatedIcon 回读确认新图已嵌入。
- **注意**：Windows 图标缓存可能让资源管理器短暂显示旧图；任务栏/重启资源管理器或改路径后即为新图。

## 2026-09-02 getRandomImage 轻量化：7天窗口下推DB+轻字段投影，冷调用快一个数量级

- **背景**：该函数（正式版路径）一直**全表拉取**过审图再在 JS 里过滤——8 页×100 条全字段顺序翻页（现 774 条会更多），探针实测冷调用 3.7s，库再涨迟早顶到函数超时上限，正式版会偶发 `system error`。
- **改动**（`cloudfunctions/getRandomImage/index.js`，取池逻辑重写，返回协议不变）：
  1. **7 天窗口下推 DB**：常规调用直接 `where({status:1, reviewTime:_.gte(窗口起点)})`，窗口内通常远小于全表（实测 214/774）；窗口为空仍回退整个过审池（保持旧语义，含 10 条缺 reviewTime 的老图——窗口查询天然排除、全量池天然包含）。
  2. **轻字段投影**：`.field({_id, url})`——客户端（`pages/index/index.js`）只消费 `_id`（seenIds/点赞/删除）和 `url/tempUrl`（显示），已逐处核对。分页 `limit 100→1000`（云函数端上限，实测单页拉全表 89ms，分页循环保留兜底）。调试分支（status:0）同样加投影。
  3. **顺带堵信息泄露**：旧版把整份文档返回前端（含 `uploaderOpenid`、`md5` 等字段，任何匿名用户可见）；新版只回 `_id/url/tempUrl`。
- **验证**（`@cloudbase/js-sdk` 匿名探针对真实库）：新旧窗口集合逐 _id 比对**完全一致**（214 条）；DB 窗口查询 1 页轻字段 40ms vs 旧 8 页全字段 500ms；首访全量路径 774 条集合一致、79ms；`reviewTime` 确认为数值时间戳（DB gte 与旧 JS 过滤同语义）。node --check 通过。
- **待办（人工）**：微信开发者工具里右键 `cloudfunctions/getRandomImage` → 上传并部署（云端安装依赖）。部署前线上仍是旧版。
- **注意**：早前探针抽样 3 条打印 reviewTime=undefined 是撞上了全库仅 10 条的无此字段老数据（无排序查询的自然序），**不是**字段类型问题——已用窗口内文档全字段复核为数值。

## 2026-09-02 开源脱敏：全历史重写清除环境ID/openid/appid，真实值改走本地配置

- **背景**：仓库确认对外公开（MIT），但历史里散布云开发环境 ID（两个）、开发者 openid（两个）、小程序 appid（两个）、TG 下载缓存（含频道号）——匿名登录 + 公开 openid 意味着任何人可读库甚至伪装管理员删库，必须清。
- **历史重写**（git filter-repo，备份 `../mouyu-pre-scrub-backup.bundle`）：replace-text 六组值→占位符；`tools/tdl_downloader/cache/md5_cache.json` 与 `__pycache__` 整体出历史（仅改缓存的两个空提交被剪，117→115）；作者邮箱→GitHub noreply。重写后全历史 grep 敏感串=0。
- **结构改造（防再泄漏）**：小程序 `app.js`、审核后台 `admin/admin.html`、审计脚本 `tools/db_dedup_check.js` 改读 gitignore 的本地配置（example 模板入库）；admin/addImage/deleteImages 白名单改读云函数环境变量 `ADMIN_OPENIDS`（缺省空名单=拒绝，fail-safe）；cosUploadHandler 的 fileID 环境 ID 改读 `ENV_ID` 变量、缺失跳过不写坏数据；gui.py 回退地址改读 `MOYU_ADMIN_URL`。`.gitignore` 补 `tdl-export.json`（TG 会话！）、`__pycache__/`、三个 config.local。
- **代价**：本地 md5 缓存被历史清理连带删掉（自动重建，云端 md5 查重兜底）；README 新增「本地部署配置」表。
- **待办（人工，重新部署云函数前必做）**：云开发控制台给 admin/addImage/deleteImages 配 `ADMIN_OPENIDS`、给 cosUploadHandler 配 `ENV_ID`，否则下次部署后管理操作会被拒、COS 触发器会跳过写库。旧部署未动，当前线上不受影响。
- **补记**：四项环境变量已配置+新代码已部署（16:53–16:54），匿名探测全绿（admin 真 openid isAdmin:true、伪造 COS 事件实测 ENV_ID 拼出真实 fileID 后清理）。`project.config.json` 的 appid 脱敏成 touristappid 后 DevTools 报「更改 AppID 失败」——真实 AppID 改放 `project.private.config.json`（DevTools 优先读、已出库+gitignore）。

## 2026-09-02 uploader 服务端重复图不删本地文件的根因修复 + 传前查重

- **现象**：日志报「✗ 该图片已存在，请勿重复上传」，但文件仍留在源文件夹，每轮重扫都会再撞一遍。
- **根因（两层）**：
  1. `uploader.py`：本地缓存查重（`md5 in cache`）会删文件，但服务端返回「已存在」走的是 `db_result['success']=False` 分支——只 error 日志，**不删文件也不记缓存**。
  2. 更深一层：上传顺序是「先传 COS → 再调云函数查重」，COS 触发器（cosUploadHandler）只按 fileID 去重（事件里拿不到 md5），而重复图每次上传的文件名带时间戳、fileID 必然不同——**重复图先落 COS 对象、触发器写一条新待审记录，之后才被 autoUpload 按 md5 拒掉**。即：库进重复待审图 + COS 落孤儿对象。
- **改动**：
  - `tools/uploader/uploader.py`：(a) md5 算出后、传 COS 前新增 `check_md5_on_server()`（调 autoUpload 新动作 `checkMd5`），查到重复/黑名单 → 删本地文件 + md5 记入本地缓存（file_id=None 的 marker）；(b) addImage 阶段返回「已存在/永久拒绝」的兜底分支同样删文件+记缓存（防其他通道竞态抢先入库）。查重调用失败/云函数未部署 → 放行走原流程，不卡上传。
  - `cloudfunctions/autoUpload/index.js`：新增 `checkMd5` 动作，查 images（status in [0,1,2,3]）+ md5_blacklist，口径与 addImage 完全一致。
- **验证**：py_compile / node --check 通过；check_md5_on_server 用桩 SCF 客户端单测 5 分支（库中存在/黑名单/新图放行/未部署 Unknown action/网络异常）全部符合预期。
- **待办（人工）**：autoUpload 云函数需再次在微信开发者工具上传部署（上午部署的版本不含 checkMd5；部署前 uploader 自动降级为老流程——重复仅本地文件暂留，不会再进库）。存量库里经审计无重复（见下一条），无需清理。

## 2026-09-02 全库 md5 判重审计：0 组重复，「存量重复」系 _id 前缀误读（虚惊）

- **起因**：上午修完 status=3 查重口径后，我汇报"库里 24 张 status=3 有同图重复入库（同 md5 前缀、不同 key）"，用户要求清理存量。
- **审计结果**（`@cloudbase/js-sdk` 匿名登录全量翻页，1100 条）：md5 重复组 **0**、fileID 重复组 **0**、空 md5 0 条；47 张 status=3 的 md5 两两不同。**库里没有重复图，无需删除。**
- **误判根因**：当时按 `_id[:8]` 分组当成了 md5 前缀——实际那是 TCB 自动 id 的**批次前缀**（同批/同通道入库的文档共享，全库仅 `3dcd4ae6/a9defcfd/10b550da/4c2f81c7` 等寥寥几种，和内容无关；例：`3dcd4ae6…` 开头 5 条的 md5 为 `00e58570/2c76c3a0/c7de0f7b/02460ff2/3d6d9bd2…` 各不相同）。qqbot WORKLOG 早前已记过同一次虚惊（"前缀只是上传者/批次标识"），这次又踩——**判重只认 md5/fileID 字段，永远别拿 `_id` 前缀当指纹**。
- **顺带确认**：admin.html 上午的 `in([0,1,3])` 查重改动已随「批量上传→重新载入」重构整块移除（admin 端不再上传，无影响）；线上 md5 查重实际只剩 autoUpload/addImage 两个云函数——**用户已于当日重新部署完成**，status=3 查重口径全量生效。
- **沉淀**：新增 `tools/db_dedup_check.js`——全库 md5/fileID 判重审计，默认只读，`--delete` 才按"bot已发 > status3 > status1 > status0、同级取早"保留一条并走 deleteImages 云函数硬删（删前写 dedup_backup.json）。依赖 `npm i @cloudbase/js-sdk`，本次实测通过（node 24 直跑，注意脚本需 process.exit，js-sdk 有后台定时器不退出）。

## 2026-09-02 修复 admin 全列表「加载失败」：CDN latest SDK 3.9.0 破坏性更新，锁版 2.32.0

- **现象**：admin 所有图片列表 tab（待审核/已通过/转发群组/已拒绝）全显示「加载失败」，但顶部统计数字正常。用户怀疑是当天「批量上传→重新载入」改动删代码导致。
- **定位**（IAB 实测复现）：错误真实信息为 `Invalid order format`——`db.collection().orderBy(字段,'desc')` 被服务端拒绝；不带 orderBy 的 count()（统计）正常，不带 orderBy 的 get() 也正常。根因：`cloudbase-js-sdk` CDN 的 `/latest/` 链接近期切到 **3.9.0**，该版把排序序列化成 `{字段:-1}` 的新协议，老环境服务端不认（已下载 3.9.0 与 2.32.0/3.8.2 的 bundle 对比确认 orderBy 实现不同）。与删上传代码无关（diff 复核：删除行全部在上传功能块内）。
- **修复**（`admin/admin.html`）：
  1. SDK 引用 `/latest/` → **锁定 2.32.0**（npm release-v2 稳定线，保留注释说明为何必须锁版）。
  2. 两个 catch（loadImages/loadBatchImages）的「加载失败」改为带上 `err.message`，下次一眼能看出原因。
- **验证**（IAB 浏览器真实点击/调用）：待审核网格 2 张、已通过 100 张+3 个日期分组、转发群组 47 条（与统计一致）、重新载入按钮刷新列表+统计（验证期间待审核 2→3 实时反映 uploader 新上传）。
- **提醒**：凡是引用 `static.cloudbase.net/cloudbase-js-sdk/latest/` 的页面（包括以后新写的）都会踩同一个坑，一律锁版本号。exe 直出磁盘 admin.html，强刷即生效，无需重打包。

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
- **待办（人工）→ 已完成（当日）**：autoUpload、addImage 两个云函数已在微信开发者工具重新部署，云端生效；admin.html 由本地工具直出（no-store），强刷即生效。已入库的历史重复不追溯，仅拦新增——后经全库审计确认历史本就无重复（见顶部条目）。

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
