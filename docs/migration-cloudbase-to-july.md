# 木偶鱼PF 云开发数据迁移方案：mouyu 环境 → july 环境

> **状态：预案，未执行。** 写于 2026-08-30，同日增补「轻量模式」。触发条件见 §0。执行时从 §1 开始按序操作。
> 本文档 + `tools/migration/` 脚本配套使用，脚本均可 `--dry-run`。

---

## ★ 轻量模式（2026-08-30 追加：原图不保留，只要代码和逻辑能跑）

用户已确认：**旧图可以丢弃**，迁移目标是「代码 + 原本能跑的逻辑」在新环境继续运行。相对完整模式大幅简化：

| 完整模式做的事 | 轻量模式 |
|---|---|
| §2 导出全部集合（01_export） | **跳过**（无数据要搬） |
| §3 桶到桶拷贝（02_copy） | **跳过**（旧图不要） |
| §4 导入 + fileID 改写（03_import） | **跳过**；改为在 july 环境建空集合 `mouyu_images`（首次写入自动建，无需手工） |
| fileID 全量改写 | **跳过**（没有旧 fileID） |
| §5 部署云函数/触发器/共享/匿名登录 | **照做**（这是"逻辑能跑"的全部本体） |
| §6 客户端切换 | **照做** |
| §7 对账 | 简化为功能验证：上传→触发→审核→随机图→转发 全链路打一遍 |

轻量模式仍值得带过去的 3 个小集合（可选，数据量极小，控制台手动导出/手抄即可）：
- `qrcode` → `mouyu_qrcode`：联系设置/二维码配置（admin「联系设置」tab + 小程序首页直读，见 `pages/index/index.js:140`）
- `md5_blacklist` → `mouyu_md5_blacklist`：拒绝图黑名单（防止重新上传时旧烂图再进池）
- `users` → `mouyu_users`：就几条 openid/role 记录（admin 权限）

**图池重建（可选福利）**：`C:\Users\w\Downloads\tdl` 本地还存着历史下载的原图。清掉 `tools/uploader/cache/md5_cache.json` 后跑一次上传，即可把本地图全量重灌进新环境（autoCleanup 会自己按 2000 张阈值滚动清理）。

轻量模式的困难点与完整模式相同，见 §0 前置确认与 §10 风险——**唯一硬门槛仍是"两小程序同主体"**（只影响小程序端；qqbot/admin 不走环境共享，见 §0 追注）。

---

## 0. 触发条件与前置确认

### 什么时候执行本方案

- mouyu 的云开发环境（套餐）临近到期且不打算续费，需要把数据与服务迁到 july 的环境继续运行。

### 迁移拓扑（事实速查，2026-08-30 核对）

| 项 | mouyu（源） | july（目标） |
|---|---|---|
| 小程序 | 木偶鱼PF `touristappid` | 西瓜太浪hd `JULY_APPID_PLACEHOLDER` |
| 云环境 ID | `MOYU_ENV_ID_PLACEHOLDER` | `JULY_ENV_ID_PLACEHOLDER` |
| 存储桶（=云存储） | `636c-MOYU_ENV_ID_PLACEHOLDER-1414730090`（ap-shanghai） | 到 july 云开发控制台「云存储→概览」查默认桶名（形如 `JULY_ENV_ID_PLACEHOLDER-13xxxxxxxx`），执行前填进 `tools/migration/config.json` |
| 已有集合 | images / users / like_logs / dislike_logs / md5_blacklist / qrcode | movies / config / **users（与 mouyu 冲突）** |
| 云函数 | addImage admin autoCleanup autoUpload cosUploadHandler deleteImages dislikeImage getRandomImage getTempUrls laughImage likeImage uploadFile（共13） | crawler dataService dbAdmin douban imageCache movieService refreshScheduler refreshService searchService userService（共10，与 mouyu 无重名） |
| 静态托管 | admin.html（tcloudbaseapp.com） | 迁移后 admin 主路径走本地工具（localhost:9000），托管可选 |

### 前置确认清单（全部打勾才能开工）

1. **两个小程序同一主体**（同一微信号注册）。云开发「环境共享」仅支持同主体。确认方式：微信公众平台→账号信息，两个 appid 的主体一致。
   **追注（2026-08-30）**：环境共享只影响**小程序端**。qqbot（HTTP gateway 直连）和 admin（web SDK 匿名登录）不经过小程序端链路，**不同主体也能迁**——那种情况下小程序展示功能退役，转发群组 + 审核上传链路照常存活。
2. july 环境套餐**未到期**且容量/调用配额足够（mouyu 数据量级：images <1000 条、桶内对象 <1000 个，量很小）。
3. 腾讯云密钥（`tools/uploader/config.json` 里那对 SecretId/Key）具备权限：COS（两桶读写）、TCB（云开发数据库 admin 读写）。若密钥权限不足 → 用 §9 Plan B（控制台手动导）。
4. 旧环境到期日已知，且距执行日 **≥7 天**（留验证+回滚窗口）。
5. Node.js ≥16 可用（跑迁移脚本）。

### 迁移总原则

- **只增不删**：导出只读、桶拷贝只增、导入写新集合。旧环境在观察期内不动一根毛 → 回滚 = 把各端 env 指回去即可。
- **集合加前缀**：mouyu 的 6 个集合迁入 july 环境时统一改名为 `mouyu_images` / `mouyu_users` / `mouyu_like_logs` / `mouyu_dislike_logs` / `mouyu_md5_blacklist` / `mouyu_qrcode`（users 必须避开冲突；其余统一前缀防未来撞名）。
- **fileID 全量改写**：fileID 格式 `cloud://<envId>.<bucket>/<key>`，env 和桶都变 → images 的 `fileID` 和 `url` 两个字段都要改写。

---

## 1. Phase 0 准备（10 分钟）

```bash
cd C:/Users/w/Documents/GitHub/mouyu/tools/migration
npm install @cloudbase/node-sdk cos-nodejs-sdk-v5
copy config.example.json config.json   # 填 target.bucket / secretId / secretKey
node 01_export.js --dry-run            # 干跑确认配置
```

`config.json` 关键字段：

```jsonc
{
  "source":   { "envId": "MOYU_ENV_ID_PLACEHOLDER", "bucket": "636c-MOYU_ENV_ID_PLACEHOLDER-1414730090", "region": "ap-shanghai" },
  "target":   { "envId": "JULY_ENV_ID_PLACEHOLDER", "bucket": "<去july控制台查>", "region": "<july环境地域,查到后填>" },
  "secretId": "<同 tools/uploader/config.json>",
  "secretKey": "<同上>",
  "collectionPrefix": "mouyu_",
  "collections": ["images", "users", "like_logs", "dislike_logs", "md5_blacklist", "qrcode"],
  "stagingDir": "./staging"
}
```

> staging 目录会产出：`collections/<name>.json`（全量文档）、`file_map.json`（新旧 fileID 映射）、`copied_keys.txt`（桶拷贝断点）。**迁移结束后 staging 整目录打包归档**，这是回滚与审计的唯一本地凭证。

## 2. Phase 1 导出源环境数据（脚本 01）

```bash
node 01_export.js
```

做三件事（全部只读）：

1. 逐集合分页拉全量（1000/页）→ `staging/collections/<name>.json`；
2. 扫描所有文档中的 `cloud://<source.envId>.<source.bucket>/...`，生成 `staging/file_map.json`（旧 fileID → 新 fileID）和 `staging/keys.txt`（待拷贝的对象 key 列表，来自 images.fileID / images.url / qrcode 里的 fileID）；
3. 打印每个集合的文档数 → 抄进 §7 验证表。

## 3. Phase 2 存储桶服务端拷贝（脚本 02）

```bash
node 02_copy_files.js            # 断点续跑：copied_keys.txt 里已有的 key 跳过
```

- COS 服务端 `copyObject`：源桶 → 目标桶，**key 原样保留**（`memes/...` 路径不变），不经过本地上传下载，~千张图秒级；
- 目标桶若还没有 `memes/` 目录不用手建，key 自带前缀；
- 完成后打印 成功/跳过/失败 计数，失败的可直接重跑（幂等）。

## 4. Phase 3 导入目标环境数据库（脚本 03）

```bash
node 03_import.js --dry-run      # 先看将要写入多少条、集合名映射
node 03_import.js                # 实际写入：保留原 _id，逐条 add；已存在的 _id 跳过（幂等可重跑）
```

- 集合名加 `mouyu_` 前缀写入；若目标集合不存在会自动创建；
- 写入前对每个文档做 fileID 字符串替换（按 `file_map.json` 前缀规则：`cloud://旧env.旧桶/` → `cloud://新env.新桶/`），images 的 `fileID`、`url` 都被覆盖；
- **_id 原样保留** → qqbot 的 `mouyu_state.json`（记录已推送 doc id）迁移后依然有效，不会重推。

## 5. Phase 4 部署云函数 + 触发器 + 共享配置

### 5.1 改代码（集合名 + fileID 模板 + env 硬编码）

| 文件 | 改什么 |
|---|---|
| `cloudfunctions/` 全部 13 个函数 | `collection('images')` → `collection('mouyu_images')`；`users`→`mouyu_users`（admin）；`md5_blacklist`→`mouyu_md5_blacklist`（admin）；`like_logs`/`dislike_logs` 同理（likeImage/dislikeImage）。全局搜索 `collection(` 逐个改 |
| `cloudfunctions/cosUploadHandler/index.js` | `cloud://MOYU_ENV_ID_PLACEHOLDER.${bucket}` → `cloud://JULY_ENV_ID_PLACEHOLDER.${bucket}`（该函数用 `DYNAMIC_CURRENT_ENV`，改死目标 envId 模板） |
| `admin/admin.html` | `ENV_ID` 改 `JULY_ENV_ID_PLACEHOLDER`；`collection('images')`→`mouyu_images`、`collection('qrcode')`→`mouyu_qrcode`（getPendingCount 等 where 不变） |
| `qqbot/plugins/mouyu_forward.py` | L77 `/collections/images/documents` → `/collections/mouyu_images/documents`；文件头注释同步 |
| `pages/index/index.js` | L140 `db.collection('qrcode')` → `db.collection('mouyu_qrcode')`（小程序端唯一直连 DB 处） |
| `tools/uploader/config.json` | `cos.bucket` 改目标桶名，`env_id` 改目标 env |
| `tools/gui.py` + `tools/tdl_downloader/tdl_downloader_v2.py` | `ADMIN_URL` 若保留托管回退，改 july 托管地址；本地 admin 优先不受影响 |
| `.github/workflows/daily-job.yml` | 已停用；若重启需同步 env/桶（scripts/*.js 引用已失效，本方案不处理） |

### 5.2 部署（微信开发者工具，打开 mouyu 项目）

1. 云函数目录 13 个函数右键「上传并部署：云端安装依赖」→ **部署时选择 july 环境**（工具右上角环境切换）；
2. **定时触发器**：`autoCleanup` / `autoUpload` 若配置过定时触发器（旧环境的配置不随代码迁移），到 july 环境「云函数→触发器」按原 cron 重建。原配置在旧环境控制台抄；
3. **COS 触发器**：COS 控制台 → 目标桶 → 事件通知 → 函数处理，新增：事件 `cos:ObjectCreated:*`、前缀 `memes/`、函数选 `cosUploadHandler`（命名空间=云函数所在地域）；
4. **环境共享**：july 云开发控制台 → 环境→共享/成员管理 → 把 mouyu 的 appid `touristappid` 加为共享成员（同主体才可见）；
5. **匿名登录**：july 环境→登录授权→启用「匿名登录」（qqbot 的 gateway 匿名登录和 admin.html 网页 SDK 都依赖它）；
6. （可选）july 环境→静态托管：上传 `admin/admin.html`，得新托管地址替换工具里的回退 URL。

## 6. Phase 5 客户端切换（顺序执行，每步验完再下一步）

| 顺序 | 端 | 动作 | 立即验证 |
|---|---|---|---|
| 1 | qqbot | `.env.prod` 的 `MOYU_ENV_ID=JULY_ENV_ID_PLACEHOLDER`，重启机器人（工具🤖按钮或 start.bat） | 机器人日志无 401/404；测试群里手动触发一次转发，图能出来 |
| 2 | admin（本地） | 打开本地 admin.html（工具🔍按钮），openid 登录 | 统计数字与 §7 对账表一致；宫格加载出图；勾一张→转发群组 tab 能看到 |
| 3 | 小程序 | `app.js` env 改 `JULY_ENV_ID_PLACEHOLDER` → 开发者工具真机预览验证 → 上传发版 | 首页能刷出图、踩/送花/哈哈生效、时间窗正常（首次可看全部） |
| 4 | uploader | `tools/uploader/config.json` 改桶后跑一次小批量上传 | COS 桶出现新对象 + `mouyu_images` 自动多一条 status=0（cosUploadHandler 触发器通）→ admin 里审核它 |
| 5 | 观察期 | 保持双环境并存 ≥3~7 天，盯 qqbot 日志 + 小程序反馈 | 无异常后进入 §8 收尾 |

> 顺序理由：先迁不可逆依赖最少的 qqbot（HTTP 直连，改 env 即切）；小程序发版最慢回滚（要再发一版），放最后。

## 7. 验证对账表（Phase 1 时抄下源数字，逐项对比）

| 指标 | 源（抄这里） | 目标（04_verify.js 输出） | 结论 |
|---|---|---|---|
| images 文档数 | ____ | ____ | 一致 |
| users / like_logs / dislike_logs / md5_blacklist / qrcode 文档数 | ____ | ____ | 一致 |
| status=1 / status=3 计数 | ____ | ____ | 一致 |
| 抽样 10 个新 fileID getTempURL 可打开 | — | ____ | 全通 |
| 桶对象数（memes/ 前缀） | ____ | ____ | ≥源 |
| fileID 残留旧前缀的文档数 | — | 0 | 必须 0 |

```bash
node 04_verify.js     # 自动出上表大部分数字
```

## 8. 收尾（观察期过后）

1. `staging/` 打包到网盘/移动硬盘（迁移审计凭证，保留至少半年）；
2. 旧环境**不要手动删数据**，让其自然到期释放（到期前若想再保险，控制台导出一份最终 JSON 归档）；
3. 旧环境静态托管里的 admin.html 停更（已是旧版）；
4. WORKLOG 记录迁移完成日期与新 env ID。

## 9. 回滚与降级

### 回滚（仅观察期内、旧环境未销毁时有效）

所有写操作只发生在 july 环境，旧环境零改动 → 回滚 = 逐端把 env 指回 `MOYU_ENV_ID_PLACEHOLDER`（qqbot .env.prod、admin.html ENV_ID、小程序 app.js 再发一版、uploader config）。july 环境里的 `mouyu_*` 集合与桶对象可留可删（不碍事）。

### Plan B：密钥权限不足 / 脚本跑不通时

- 数据库：旧环境云开发控制台→数据库→逐集合「导出」JSON（控制台原生支持），放到 `staging/collections/<name>.json`，从 Phase 3 继续（03_import 只依赖 staging 文件）；
- 存储：控制台→云存储→`memes/` 目录批量下载到本地，再用 COS 控制台/工具上传到目标桶同 key（量小可接受）；
- 唯一做不到的：_id 保留。控制台导出含 _id，导入 july 控制台支持导入时保留 _id ✓。

## 10. 已知风险与坑（执行前重读）

1. **users 集合冲突**是必须加前缀的根因；若未来想合并用户体系，另做映射表方案，勿在本次迁移里做。
2. **fileID 是双字段**（fileID + url 都存 cloud://），03_import 做的是全文档字符串替换，覆盖两者；漏改 url 的话 admin 缩略图会挂（getTempUrls 按 fileID 转换，但部分代码直接读 url）。
3. **getRandomImage 时间窗**：按 reviewTime 判 7 天窗口。迁移不改时间字段 → 迁移当天小程序「非首次访问」用户看到的图不变，无感知。
4. **autoCleanup 的 2000 张阈值**：操作的是 `mouyu_images`（改名后自动隔离），不会误删 july 的 movies。
5. **COS 触发器有秒级延迟**：uploader 传完立刻刷新 admin 可能晚 1~2 秒出现，属正常。
6. **qqbot 匿名登录**：july 环境若忘开匿名登录授权，轮询会 401，机器人日志会出现鉴权失败——Phase 4.5 别漏。
7. **环境共享的调用计费**归属 july 环境（套餐内），mouyu 小程序不再有自己的环境账单。
8. **md5 去重**：uploader 的本地 md5_cache 不受迁移影响；`mouyu_md5_blacklist`（拒绝图片黑名单）随集合迁走，admin 的「拒绝→进黑名单」逻辑在 admin 云函数里，随 5.1 改名自动生效。
9. 若 july 环境与源桶**不同地域**：copyObject 支持跨地域，仅拷贝稍慢；region 字段在 config.json 里分别填对即可。

---

*核对快照：mouyu @ 340ee8a / july @ d19100c / qqbot @ cc9be4a（2026-08-30）。执行时以当日代码为准重新 grep 集合名与 env 引用。*
