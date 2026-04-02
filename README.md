# 木偶鱼PF - 沙雕趣图搬运工

> 微信小程序 | 沙雕趣图随机展示

> 最后更新：2026-03-31

---

## 项目概述

| 项目名称 | 木偶鱼PF |
|----------|------------|
| 项目类型 | 微信小程序 |
| 核心功能 | 随机展示梗图，用户上传，踩/送花/哈哈功能 |
| 设计原则 | 极简、傻瓜化，开源 |
| 当前版本 | v1.0.7 |

---

## 项目结构

```
mouyu/
├── 📱 小程序核心代码
│   ├── pages/              # 页面目录
│   │   ├── admin/          # 管理页面
│   │   ├── index/          # 首页
│   │   └── upload/         # 上传页面
│   ├── cloudfunctions/     # 云函数
│   ├── app.js/json/wxss   # 小程序核心
│   └── project.config.json # 项目配置
│
├── 🛠️ 工具目录（不上传）
│   └── telegram-decrypter/  # Telegram 缓存解密
│
├── 📄 文档
│   ├── README.md           # 本文档
│   ├── API.md             # 云函数接口文档
│   ├── IMPROVEMENTS.md    # 项目改进建议
│   └── REFACTOR_TRIGGER.md # 重构触发追踪
│
└── 🔧 管理工具
    └── admin.html          # Web 管理后台
```

---

## 核心功能

| 功能 | 描述 |
|------|------|
| 随机展示 | 首页下拉刷新换图，已看图片不重复（限制50个seenIds） |
| 哈哈功能 | 😂 按钮，点击后屏幕飞过各种"哈哈"文字，有权重提升效果 |
| 送花功能 | 🌸 按钮，每人每天1次 |
| 踩功能 | 💩 按钮，每人每天3次，踩后自动换图 |
| 上传入口 | 点击右上角+上传图片，每天最多9张 |
| 审核机制 | 图片上传后需管理员审核才展示 |

### 哈哈权重系统

- 用户每点击一次哈哈，有效次数(≤15次)会记录到图片
- laughCount 越高的图片，被优先展示的概率越大
- 算法：每个图片权重 = `laughCount + 1`

### 首次访问规则

- 首次访问：可看到所有已通过图片
- 后续访问：只展示最近3天内上传的图片

---

## 技术方案

| 类别 | 方案 |
|------|------|
| 前端 | 微信小程序原生开发 |
| 后端 | 云开发·云函数（Node.js） |
| 数据库 | 云开发·云数据库 |
| 存储 | 云开发·云存储 |
| 自动上传 | Python + COS SDK + SCF API |

---

## 数据库设计

### images（图片表）

| 字段 | 类型 | 说明 |
|------|------|------|
| _id | ObjectId | 主键 |
| fileID | string | 云存储fileID |
| url | string | 图片CDN地址 |
| md5 | string | 图片MD5值（去重用） |
| uploaderOpenid | string | 上传者openid |
| status | number | 0待审核/1已通过/2已拒绝 |
| dislikeCount | number | 被踩次数 |
| likeCount | number | 被送花次数 |
| laughCount | number | 被哈哈次数（权重） |
| date | string | 上传日期 YYYY-MM-DD |
| yearMonth | string | 年月 YYYY-MM |
| createTime | number | 创建时间戳 |

### 其他表

- `dislike_logs` - 踩记录表
- `like_logs` - 送花记录表
- `users` - 用户表

---

## 云函数列表

| 云函数 | 功能 |
|--------|------|
| getRandomImage | 获取随机图片（加权随机，限制seenIds=50） |
| dislikeImage | 踩图片 |
| likeImage | 送花 |
| laughImage | 记录哈哈次数 |
| addImage | 添加图片（检查MD5去重） |
| admin | 管理员操作（审核、权限验证） |
| getTempUrls | 获取临时URL |
| deleteImages | 批量删除图片 |
| autoCleanup | 自动清理（满2000张删200张，优先删已拒绝） |
| autoUpload | 自动上传工具支持 |

---

## 自动清理规则

- 触发条件：图片总数满 2000 张
- 删除数量：每次删除 200 张
- 删除优先级：先删已拒绝(status=2)，不够再删待审核(status=0)
- 排序方式：按 createTime 倒序

---

## 管理后台 (admin.html)

访问方式：
```bash
python -m http.server 9000
# 访问 http://localhost:9000/admin.html
```

功能：
- 图片审核（通过/拒绝）
- 批量删除
- 数据统计
- 图片预览（左右切换、键盘快捷键）

---

## 自动上传工具 (uploader)

配置 `config.json` 后运行：
```bash
pip install -r requirements.txt
python uploader.py
```

**图片压缩**：PNG/BMP/WebP/TIFF 自动转 JPEG（节省 50-80% 体积）

---

## Telegram 缓存解密 (telegram-decrypter)

---

## 部署步骤

1. **部署云函数**：admin, getTempUrls, deleteImages, autoCleanup, autoUpload, getRandomImage, addImage, dislikeImage, likeImage, laughImage

2. **配置云函数权限**：未登录用户可调用

3. **配置定时触发器**：autoCleanup 设置每天凌晨2点执行

4. **启动本地服务器**访问 Web 管理工具

---

## 代码包状态

| 项目 | 值 |
|------|-----|
| 大小 | ~300KB |
| 状态 | ✅ 正常 |

已排除：tools/, docs/, admin/, *.py, *.md, .venv/

---

## 维护规范

### REFACTOR_TRIGGER.md

用于追踪需要重构的改动，满足条件时触发：

| 任务 | 触发条件 |
|------|---------|
| 配置集中化 | IMAGE_LIMIT/IMAGE_WINDOW_DAYS 被修改超过3次 |
| uploader.py 拆分 | 文件超过 400 行 |

### 更新规则

- 每次功能改动**完成后**，检查是否需要更新 README
- 重构完成后，更新 REFACTOR_TRIGGER.md 记录
- 如果有功能改动但在当前对话中未完成，**不提醒**

---

## 版本历史

### v1.0.7 (2026-03-31)

- 新增首次访问规则（可看所有图，后续只看3天内新图）
- getRandomImage 优化（限制seenIds=50提升性能）
- admin 审核拒绝时自动拉黑MD5
- autoCleanup 改为满2000删200

### v1.0.6 (2026-03-27)

- 隐藏模式特效系统
- 送花解锁隐藏模式
- 飞字气泡三种动态效果
- 舞台射灯效果
- 哈哈按钮权重系统

### v1.0.5 (2026-03-26)

- 哈哈按钮权重系统
- 哈哈飞字效果增强
- 修复图片重复出现的竞态条件

---

## 外部依赖

| 工具 | 用途 |
|------|------|
| telegram-decrypter | Telegram 缓存解密 |

---

## 许可证

MIT 许可证开源
