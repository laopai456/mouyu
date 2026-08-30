# CLAUDE.md / AGENTS.md — 木偶鱼PF

> 开始任何任务前，先读 `~/.agents/global-guidelines.md`（跨项目通用规则）。本文件冲突时优先。

## 一句话
微信小程序「木偶鱼PF」：沙雕趣图随机展示 + 用户上传 + 踩/送花/哈哈互动。原生小程序前端 + 微信云开发（云函数/云数据库/云存储）。功能/部署细节看 `README.md`，开发规范/踩坑复盘看 `.trae/rules/project_rules.md`。

## 技术栈
- 前端：微信小程序原生（`app.js/json/wxss` + `pages/`）
- 后端：微信云开发（Node.js 云函数 `cloudfunctions/`，云数据库，云存储）
- 自动化工具：Python（`tools/`：telegram-decrypter / uploader / tdl_downloader）

## 启动命令
- 小程序：微信开发者工具打开项目根目录
- 管理后台：`python -m http.server 9000` → 访问 `http://localhost:9000/admin.html`
- 自动上传：`pip install -r tools/uploader/requirements.txt && python tools/uploader/uploader.py`

## 关键约定（改云函数/数据时必看）
- **图片状态机**：status ∈ {0:待审核, 1:已通过, 2:已拒绝}。getRandomImage 只返 status=1，时间窗口按 `reviewTime` 判断（首次访问可看全部，后续只看 7 天内 reviewTime）。
- **哈哈权重**：`laughCount` 越高展示概率越大（权重 = laughCount + 1，上限 15 次有效）。
- **云数据库 where() 链式 bug**：多条件 where 可能丢条件 → 改用内存过滤（先 where status，再 filter reviewTime）。
- **autoCleanup**：满 2000 张删 200 张，优先删 status=2，不够再删 status=0，按 createTime 倒序。
- **代码包排除**：`tools/ docs/ admin/ .trae/ *.py *.md .venv/` 不进小程序包（~300KB）。

## 字段（images 表关键字段）
`_id, fileID, status, dislikeCount, likeCount, laughCount, date(YYYY-MM-DD), yearMonth(YYYY-MM), createTime, reviewTime, md5`

## 字体版权（防侵权）
- ✅ 可用：`-apple-system`、`PingFang SC`（苹果开源）、`HarmonyOS Sans`（华为开源）
- ❌ 禁用：微软雅黑（方正版权）、方正系列（需授权）
- 加新字体前必须确认"免费商用"并保留授权证明。

## Git 规范
- commit：`type(scope): 中文描述`
- 本地 commit 后立即 push

## 工程纪律（自包含，不依赖全局文件，CC/ZCode 通用）
1. **非平凡改动前先 Plan**：涉及多文件/多函数/不确定影响范围的改动，先 plan 梳理再动手；小修可直接改。
2. **日志带固定关键词**：关键事件/状态切换/异常用固定短关键词打日志并分级（INFO/WARN/ERROR），便于 grep。

## 上下文经济（省 token，1M 上下文越长每轮越贵）
- 大文件分段读（超 200 行用 offset/limit），不重复读已读文件。
- 命令输出用 grep/findstr 过滤，不贴大段内容进对话，用 `文件:行号` 引用。
- 大范围排查委派 Explore agent，只把结论带回。
- 回答简洁，结论先行，不复述需求。

## 工作日志（WORKLOG.md，跨对话续上下文的命脉）
每次会话开始先读 `WORKLOG.md` 顶部最新条目了解上次进度。

**何时写（判定标准，按优先级）：**
1. **验证通过即写**（AI 主动）：改动落地 + 验证通过（测试/编译/核对）= 完成。验证没过的**绝不**写进 WORKLOG 当完成项。
2. **阶段切换即写**（AI 提醒）：长任务告一段落要进下一阶段，先写一条并问是否继续。
3. **用户归档即写**（用户触发）：用户说"归档/结束/换任务"，立刻写。

格式（顶部追加，最新在前，只追加不覆盖）：`## YYYY-MM-DD 标题` + 做了什么/改动文件/验证/下一步。新对话续接靠它，不靠对话历史。
