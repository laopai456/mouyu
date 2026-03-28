# 木偶鱼PAF - 沙雕趣图搬运工

> 微信小程序 | 沙雕趣图随机展示

> 最后更新：2026-03-28

---

## 一、项目概述

| 项目名称 | 木偶鱼PAF |
|----------|------------|
| 项目类型 | 微信小程序 |
| 核心功能 | 随机展示梗图，用户上传，踩/送花/哈哈功能 |
| 设计原则 | 极简、傻瓜化，开源 |
| 当前版本 | v1.0.6 |

---

## 二、项目结构

```
mouyu/
│
├── 📱 小程序核心代码                    # ⭐ 必须保留，上传审核用
│   ├── pages/                         # 页面目录
│   │   ├── admin/                     # 管理页面
│   │   ├── index/                     # 首页
│   │   └── upload/                    # 上传页面
│   ├── cloudfunctions/                # 云函数
│   ├── app.js/json/wxss               # 小程序核心
│   ├── project.config.json            # 项目配置 ⚠️
│   └── sitemap.json                   # 站点地图
│
├── 🛠️ 工具目录                         # 开发工具，不上传
│   ├── uploader/                      # 图片上传工具
│   │   ├── config.example.json        # 配置示例
│   │   ├── uploader.py                # 主程序
│   │   ├── requirements.txt          # 依赖包
│   │   └── 启动.bat                   # Windows 启动脚本
│   ├── tdl_downloader/                # Telegram 图片下载器
│   │   ├── tdl_downloader.py          # 主程序
│   │   ├── converted_model.tflite     # 梗图检测模型
│   │   ├── cache/                     # MD5缓存
│   │   └── requirements.txt           # 依赖包
│   └── telegram-decrypter/            # Telegram 缓存解密工具
│       ├── main.py                    # 主程序
│       ├── setup.py                   # 安装脚本
│       └── README.md                  # 工具说明
│
├── 📄 文档目录                          # 文档，不上传
│   └── README.md                      # 本文档
│
├── 🔧 管理工具                          # 管理工具，不上传
│   └── admin.html
│
└── 📄 配置文件
    ├── .gitignore                     # ⚠️ 已更新
    └── project.private.config.json     # 私有配置
```

---

## 三、功能需求

### 3.1 核心功能

| 功能 | 描述 |
|------|------|
| 随机展示 | 首页下拉刷新换图，已看图片不重复 |
| 哈哈功能 | 😂 按钮，点击后屏幕飞过各种"哈哈"文字，有权重提升效果 |
| 送花功能 | 🌸 按钮，每人每天1次 |
| 踩功能 | 💩 按钮，每人每天3次，踩后自动换图 |
| 上传入口 | 点击右上角+上传图片，每天最多9张 |
| 审核机制 | 图片上传后需管理员审核才展示 |

### 3.2 哈哈权重系统

- 用户每点击一次哈哈按钮，有效次数(≤15次)会记录到图片
- laughCount 越高的图片，被优先展示的概率越大
- 超过15次点击视为无效，不计入权重
- 算法：每个图片权重 = `laughCount + 1`（保证新图片也有展示机会）

### 3.3 交互规则

| 功能 | 规则 |
|------|------|
| 哈哈 | 有效次数≤15次，记录权重 |
| 送花 | 每人每天1次，全局限制 |
| 踩 | 每人每天3次，不能重复踩同一张 |
| 上传 | 每人每天9张，需审核后展示 |
| 刷图 | 已看过的图片不再显示，刷完显示"上会儿班吧，球球了。" |

---

## 四、技术方案

### 4.1 技术选型

| 类别 | 方案 |
|------|------|
| 前端 | 微信小程序原生开发 |
| 后端 | 云开发·云函数（Node.js） |
| 数据库 | 云开发·云数据库 |
| 存储 | 云开发·云存储 |
| Web SDK | cloudbase-js-sdk |
| 自动上传 | Python + COS SDK + SCF API |

### 4.2 审核流程

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

## 五、数据库设计

### 5.1 images（图片表）

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
| laughCount | number | 被哈哈次数（权重） |
| date | string | 上传日期 YYYY-MM-DD |
| yearMonth | string | 年月 YYYY-MM |
| month | number | 月份 |
| createTime | number | 创建时间戳 |

### 5.2 其他表

- `dislike_logs` - 踩记录表
- `like_logs` - 送花记录表
- `users` - 用户表

---

## 六、云函数列表

| 云函数 | 功能 |
|--------|------|
| getRandomImage | 获取随机图片（加权随机算法） |
| dislikeImage | 踩图片 |
| likeImage | 送花 |
| laughImage | 记录哈哈次数 |
| addImage | 添加图片 |
| admin | 管理员操作（审核、权限验证） |
| getTempUrls | 获取临时URL |
| deleteImages | 批量删除图片 |
| autoCleanup | 自动清理过期图片 |
| autoUpload | 自动上传工具支持 |

---

## 七、项目重组说明

### 7.1 已完成的重组工作

| 项目 | 状态 | 说明 |
|------|------|------|
| 项目结构 | ✅ 完成 | 结构清晰，文件分类明确 |
| 配置更新 | ✅ 完成 | ignore 配置正确 |
| 安全隔离 | ✅ 完成 | 工具和代码分离 |
| 代码包 | ✅ 合理 | 294KB，无关文件已排除 |

### 7.2 配置更新

**project.config.json** 已添加 ignore 规则：
```json
{
  "packOptions": {
    "ignore": [
      { "type": "folder", "value": "tools" },
      { "type": "folder", "value": "docs" },
      { "type": "folder", "value": "admin" },
      { "type": "suffix", "value": ".py" },
      { "type": "suffix", "value": ".bat" },
      { "type": "suffix", "value": ".md" }
    ]
  }
}
```

**效果**：上传小程序时，只会包含 pages/、cloudfunctions/、app.js/json/wxss 等必要文件，工具和文档会被忽略。

### 7.3 代码包分析

- **总大小**：294KB
- **文件数**：47 个
- **无依赖代码文件数**：30 个（262KB）

✅ 代码包大小合理，无关文件已排除。

---

## 八、自动上传工具

### 8.1 目录结构

```
tools/uploader/
├── config.example.json     # 配置示例
├── uploader.py             # 主程序
├── requirements.txt        # 依赖包
└── 启动.bat               # Windows 启动脚本
```

### 8.2 配置文件

```json
{
  "env_id": "cloudbase-8gfl3w4b18e46282",
  "developer_openid": "oWatD3bwu0aVaFTPvrrerAU_C2zY",
  "watch_folders": [
    {
      "path": "C:\\Users\\xxx\\Documents\\Tencent Files\\xxx\\Pic\\2026-03\\Ori",
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

### 8.3 使用方法

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python uploader.py
```

---

## 九、TDL 图片下载器

> 从 Telegram 频道批量下载梗图

### 9.1 功能

- 批量下载指定 Telegram 频道图片
- TFLite 模型智能过滤非梗图（准确率 92%）
- MD5 去重，避免重复下载
- 文件大小过滤（<30KB 自动删除）
- 多频道配置，自定义下载数量
- 缓存管理，支持增量下载

### 9.2 依赖

- Python 3.12+
- TensorFlow 2.21+
- tdl (Telegram Downloader)

### 9.3 安装和使用

```bash
# 安装依赖
pip install -r requirements.txt

# 配置频道和代理（编辑 tdl_downloader.py）
CHANNELS = {
    "woshadiao": 100,      # 频道名: 下载数量
    "shadiao_refuse": 150,
}
PROXY = "socks5://127.0.0.1:7897"

# 运行
python tdl_downloader.py
```

### 9.4 过滤逻辑

1. 文件大小 < 30KB → 删除（表情包）
2. TFLite 模型判断非梗图 → 删除
3. MD5 重复 → 删除

---

## 十、 Telegram Decrypter 工具

> Telegram Desktop 缓存数据解密工具

### 9.1 功能

- 解密 Telegram Desktop 的本地数据文件 (tdata)
- 查看用户 ID、DC ID 和验证密钥
- 读取应用程序设置
- 支持加密和非加密数据
- 支持 JSON 格式输出

### 9.2 依赖

- Python 3.8+
- tgcrypto 库

### 9.3 安装和使用

```bash
# 安装
pip install .

# 运行
python main.py <tdata_path> [--passcode <password>] [--show_settings] [--json]
```

**参数说明：**
- `<tdata_path>`: Telegram `tdata/` 目录路径
- `--passcode`, `-p`: (可选) 如果 tdata/ 加密，需要输入密码
- `--show_settings`: 显示解码后的设置
- `--json`, `-j`: JSON 格式输出

**示例：**
```sh
# 标准输出账户信息
python main.py /path/to/tdata/

# JSON格式输出
python main.py /path/to/tdata/ --json

# 显示设置
python main.py /path/to/tdata/ --show_settings

# 读取加密目录
python main.py /path/to/tdata/ --passcode 'password'
```

---

## 十、Web 管理后台

### 10.1 功能

- 批量上传图片（无数量限制）
- 图片审核（通过/拒绝）
- 批量删除图片
- 数据统计（待审核/已通过/已拒绝）
- 图片预览（左右切换、键盘快捷键）
- 预览界面直接操作

### 10.2 使用方法

```bash
# 启动本地服务器
python -m http.server 9000

# 访问
http://localhost:9000/admin.html
```

### 10.3 快捷键

| 快捷键 | 功能 |
|--------|------|
| ← | 上一张图片 |
| → | 下一张图片 |
| ESC | 关闭预览 |

---

## 十一、云开发配置

### 11.1 权限设置

- 开启「未登录用户访问云资源权限」
- 开启「允许匿名登入」
- 数据库权限：images 集合设置为「所有用户可读，创建者可写」
- 存储权限：设置为「所有用户可读，创建者可写」

### 11.2 云函数权限

```json
// getTempUrls
{"*": {"invoke": true}}

// deleteImages
{"*": {"invoke": true}}

// autoCleanup 定时触发器
0 0 2 * * * *
```

---

## 十二、管理员配置

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

## 十三、版本历史

### v1.0.6 (2026-03-27)

**新增功能：**
- 隐藏模式特效系统
  - 送花解锁隐藏模式（全天候生效，次日重置）
  - 飞字气泡三种动态效果：彩虹渐变、霓虹发光、故障艺术
  - 舞台射灯效果（4个彩色光柱左右摇摆）
  - 舞台暗色背景衬托
- 送花/踩按钮静默处理（无Toast无加载圈）
- 踩次数显示优化（3次/天，显示剩余次数）

**新增云函数：**
- `laughImage` - 记录哈哈点击次数到数据库

**修改云函数：**
- `dislikeImage` - 踩降低权重（laughCount -0.5）
- `likeImage` - 送花次数改为3次/天

**交互优化：**
- 哈哈按钮样式优化（橙色渐变+圆角）
- 哈哈飞字位置优化（长文本不超过5字避免截断）
- 踩飞字emoji效果（💩噗呕🤮呸随机飞出）
- 飞字层级优化（效果在舞台灯光上层）

**文件变更：**
- 新增 `cloudfunctions/laughImage/` 云函数
- 修改 `pages/index/index.js`（笑哭效果、隐藏模式、踩次数）
- 修改 `pages/index/index.wxml`（舞台灯光结构）
- 修改 `pages/index/index.wxss`（动态效果样式）
- 修改 `cloudfunctions/likeImage/index.js`（送花次数3次）
- 修改 `cloudfunctions/dislikeImage/index.js`（权重调整）

---

### v1.0.5 (2026-03-26)

**新增功能：**
- 哈哈按钮权重系统
  - 点击哈哈按钮记录到图片 laughCount 字段
  - 超过15次点击视为无效
  - 加权随机算法优先展示高 laughCount 图片
- 哈哈飞字效果增强
  - 多彩气泡背景（8种颜色）
  - 弹跳缩放动画
  - 50+文案库（含10年前经典梗）
  - 均衡的左/中/右位置分布

**修复问题：**
- 修复图片重复出现的竞态条件
- 云函数随机数范围问题

**文件变更：**
- 新增 `cloudfunctions/laughImage/` 云函数
- 修改 `pages/index/` 首页（哈哈按钮+飞字效果）
- 修改 `cloudfunctions/getRandomImage/` 云函数（加权随机）

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

## 十四、部署步骤

1. **部署云函数：**
   - admin
   - getTempUrls
   - deleteImages
   - autoCleanup
   - autoUpload
   - laughImage（新增）

2. **配置云函数权限**

3. **配置定时触发器（autoCleanup）**

4. **配置自动上传工具（config.json）**

5. **启动本地服务器访问 Web 管理工具**

---

## 十五、上传前必读

### 15.1 代码包状态

- **大小**：294KB
- **文件数**：47 个
- **状态**：✅ 正常

### 15.2 已排除的文件

- ❌ `tools/` - 工具目录
- ❌ `docs/` - 文档目录
- ❌ `admin/` - 管理工具
- ❌ `*.py` - Python 文件
- ❌ `*.md` - Markdown 文件

### 15.3 敏感信息

- ❌ 不要上传 `project.private.config.json`
- ❌ 不要上传 `tools/uploader/config.json`
- ❌ 不要上传任何包含密钥的文件

### 15.4 检查清单

- [ ] 查看"代码依赖分析"确认包内容
- [ ] 使用"预览"功能测试
- [ ] 确认没有包含敏感文件

---

## 十六、安全声明

本项目中的 Telegram Decrypter 工具仅供教育和研究使用。请始终尊重隐私和法律准则。

---

## 十八、外部依赖

### 18.1 工具

| 工具 | 用途 | 地址 |
|------|------|------|
| tdl | Telegram 频道媒体下载 | https://github.com/iyear/tdl |
| telegram-decrypter | Telegram 缓存解密 | https://github.com/torinak/telegram-decrypter |

### 18.2 Python 库

| 库 | 用途 | 工具 |
|------|------|------|
| tensorflow | TFLite 模型推理 | tdl_downloader |
| numpy | 数值计算 | tdl_downloader |
| pillow | 图片处理 | tdl_downloader |
| tgcrypto | Telegram 加密解密 | telegram-decrypter |
| cos-python-sdk-v5 | 腾讯云 COS 上传 | uploader |
| requests | HTTP 请求 | uploader |

### 18.3 模型

| 模型 | 用途 | 来源 |
|------|------|------|
| converted_model.tflite | 梗图/非梗图二分类 | https://github.com/skothari07/Meme-Detection-Android-App-using-Tensorflow-Lite |

---

## 十九、许可证

本项目基于 MIT 许可证开源。
