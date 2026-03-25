# 木偶鱼小程序 - 项目文档

## 一、项目概述

| 项目名称 | 木偶鱼PAF |
|----------|------------|
| 项目类型 | 微信小程序 |
| 核心功能 | 随机展示梗图，用户上传，踩/送花功能 |
| 设计原则 | 极简、傻瓜化、开源 |
| 当前版本 | v1.0.4 |

---

## 二、功能需求

### 2.1 核心功能

| 功能 | 描述 |
|------|------|
| 随机展示 | 首页下拉刷新换图，已看图片不重复 |
| 送花功能 | 🌸 按钮，每人每天1次 |
| 踩功能 | 💩 按钮，每人每天3次，踩后自动换图 |
| 上传入口 | 点击右上角+上传图片，每天最多9张 |
| 审核机制 | 图片上传后需管理员审核才展示 |

### 2.2 交互规则

| 功能 | 规则 |
|------|------|
| 送花 | 每人每天1次，全局限制 |
| 踩 | 每人每天3次，不能重复踩同一张 |
| 上传 | 每人每天9张，需审核后展示 |
| 刷图 | 已看过的图片不再显示，刷完显示"上会儿班吧，球球了。" |

---

## 三、技术方案

### 3.1 技术选型

| 类别 | 方案 |
|------|------|
| 前端 | 微信小程序原生开发 |
| 后端 | 云开发·云函数（Node.js） |
| 数据库 | 云开发·云数据库 |
| 存储 | 云开发·云存储 |
| Web SDK | cloudbase-js-sdk |
| 自动上传 | Python + COS SDK + SCF API |

### 3.2 审核流程

```
用户上传图片 → status: 0（待审核）
        │
        ▼
管理员审核 → status: 1（通过）/ 2（拒绝）
        │
        ▼
通过后图片进入展示池
```

---

## 四、数据库设计

### 4.1 images（图片表）

| 字段 | 类型 | 说明 |
|------|------|------|
| _id | ObjectId | 主键 |
| fileID | string | 云存储fileID |
| url | string | 图片CDN地址 |
| md5 | string | 图片MD5值 |
| uploaderOpenid | string | 上传者openid |
| status | number | 0待审核/1已通过/2已拒绝 |
| dislikeCount | number | 被踩次数 |
| likeCount | number | 被送花次数 |
| date | string | 上传日期 YYYY-MM-DD |
| yearMonth | string | 年月 YYYY-MM |
| month | number | 月份 |
| createTime | number | 创建时间戳 |

### 4.2 其他表

- `dislike_logs` - 踩记录表
- `like_logs` - 送花记录表
- `users` - 用户表

---

## 五、云函数列表

| 云函数 | 功能 |
|--------|------|
| getRandomImage | 获取随机图片 |
| dislikeImage | 踩图片 |
| likeImage | 送花 |
| addImage | 添加图片 |
| admin | 管理员操作（审核、权限验证） |
| getTempUrls | 获取临时URL |
| deleteImages | 批量删除图片 |
| autoCleanup | 自动清理过期图片 |
| autoUpload | 自动上传工具支持 |

---

## 六、版本历史

### v1.0.4 (2026-03-25)

**新增功能：**
- 自动监控上传工具（mouyu-uploader）
  - 监控指定文件夹，自动上传新图片
  - MD5去重，避免重复上传
  - 通过SCF API调用云函数写入数据库
  - 支持配置多个监控文件夹
- Web管理后台预览增强
  - 左右箭头切换上一张/下一张
  - 键盘快捷键（左右箭头、ESC）
  - 预览界面直接审核/删除
  - 显示图片计数和互动数据

**修复问题：**
- 修复Web管理后台审核功能无权限问题
- 云函数支持adminOpenid参数传递

**文件变更：**
- 新增 `mouyu-uploader/` 自动上传工具目录
- 修改 `cloudfunctions/admin/index.js` 支持Web端调用
- 修改 `admin.html` 预览功能增强

---

### v1.0.3 (2026-03-25)

**主要更新：**
- 升级 Web SDK 到最新版本，修复数据库访问问题
- 创建云函数 getTempUrls 获取临时 URL
- 创建云函数 deleteImages 支持批量删除
- 创建云函数 autoCleanup 自动清理过期图片
- 添加图片预览模态框
- 修复 iPhone SE 3 图片加载问题
- 实现角色权限控制（开发者/共创者/普通用户）
- 增加重复图片检测功能（MD5）
- 按月份自动分类存储图片
- 自动清理 3 天前的图片

---

### v1.0.2
- 基础功能实现
- 小程序端图片上传和展示
- 点赞/踩功能

### v1.0.1
- 项目初始化
- 基础架构搭建

### v1.0.0
- 项目创建

---

## 七、自动上传工具

### 7.1 目录结构

```
mouyu-uploader/
├── config.json          # 配置文件
├── uploader.py          # 主程序
├── requirements.txt     # 依赖包
├── logs/               # 日志目录
│   └── upload.log      # 上传日志
└── cache/              # 缓存目录
    └── md5_cache.json  # MD5 缓存
```

### 7.2 配置文件

```json
{
  "env_id": "cloudbase-8gfl3w4b18e46282",
  "developer_openid": "oWatD3bwu0aVaFTPvrrerAU_C2zY",
  "watch_folders": [
    {
      "path": "C:\\Users\\w\\Documents\\Tencent Files\\xxx\\Pic\\2026-03\\Ori",
      "enabled": true,
      "description": "QQ 图片缓存"
    }
  ],
  "file_types": ["jpg", "jpeg", "png", "gif", "webp", "bmp"],
  "upload_delay": 2,
  "max_retry": 3,
  "cos": {
    "secret_id": "AKIDxxx",
    "secret_key": "xxx",
    "bucket": "636c-cloudbase-xxx-1414730090",
    "region": "ap-shanghai"
  }
}
```

### 7.3 使用方法

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python uploader.py
```

### 7.4 工作流程

```
启动脚本 → 加载配置 → 初始化监控
    │
    ▼
检测新文件 → 判断图片类型 → 计算MD5
    │              │              │
    │              ▼              ▼
    │         忽略非图片     检查是否重复
    │                               │
    │                               ▼
    │                          上传到COS
    │                               │
    │                               ▼
    │                          调用云函数写入数据库
    │                               │
    │                               ▼
    │                          记录日志
    │
    ▼
继续监控
```

---

## 八、Web 管理后台

### 8.1 功能

- 批量上传图片（无数量限制）
- 图片审核（通过/拒绝）
- 批量删除图片
- 数据统计（待审核/已通过/已拒绝）
- 图片预览（左右切换、键盘快捷键）
- 预览界面直接操作

### 8.2 使用方法

```bash
# 启动本地服务器
python -m http.server 9000

# 访问
http://localhost:9000/admin.html
```

### 8.3 快捷键

| 快捷键 | 功能 |
|--------|------|
| ← | 上一张图片 |
| → | 下一张图片 |
| ESC | 关闭预览 |

---

## 九、云开发配置

### 9.1 权限设置

- 开启「未登录用户访问云资源权限」
- 开启「允许匿名登入」
- 数据库权限：images 集合设置为「所有用户可读，创建者可写」
- 存储权限：设置为「所有用户可读，创建者可写」

### 9.2 云函数权限

```json
// getTempUrls
{"*": {"invoke": true}}

// deleteImages
{"*": {"invoke": true}}

// autoCleanup 定时触发器
0 0 2 * * * *
```

---

## 十、管理员配置

在 `cloudfunctions/admin/index.js` 中配置：

```javascript
const DEVELOPER_OPENIDS = ['oWatD3bwu0aVaFTPvrrerAU_C2zY'];
const CREATOR_OPENIDS = ['共创者的openid'];
```

获取 openid 方法：
```javascript
wx.cloud.callFunction({
  name: 'admin',
  data: { action: 'checkAdmin' }
}).then(res => console.log(res.result.openid))
```

---

## 十一、部署步骤

1. 部署云函数：
   - admin
   - getTempUrls
   - deleteImages
   - autoCleanup
   - autoUpload

2. 配置云函数权限

3. 配置定时触发器（autoCleanup）

4. 配置自动上传工具（config.json）

5. 启动本地服务器访问 Web 管理工具
