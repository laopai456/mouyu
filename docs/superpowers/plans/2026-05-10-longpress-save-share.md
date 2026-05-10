# 长按保存图片 + 转发功能 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在首页图片上长按弹出底部菜单，支持保存到相册和转发给好友。

**架构：** 在 `<image>` 标签添加 `bindlongpress` 事件，弹出自定义底部弹窗（遮罩 + 操作面板）。保存通过 `wx.downloadFile` + `wx.saveImageToPhotosAlbum` 实现，转发通过 `<button open-type="share">` 触发已有的 `onShareAppMessage`。

**技术栈：** 微信小程序原生 API（wx.downloadFile、wx.saveImageToPhotosAlbum、button open-type="share"）

**规格文档：** `c:\Users\w\Documents\GitHub\mouyu\docs\superpowers\specs\2026-05-10-longpress-save-share-design.md`

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `c:\Users\w\Documents\GitHub\mouyu\app.json` | 修改 | 添加相册写入权限声明 |
| `c:\Users\w\Documents\GitHub\mouyu\pages\index\index.wxml` | 修改 | 图片标签添加长按事件 + 弹窗模板 |
| `c:\Users\w\Documents\GitHub\mouyu\pages\index\index.js` | 修改 | 添加弹窗状态 + 3 个交互方法 |
| `c:\Users\w\Documents\GitHub\mouyu\pages\index\index.wxss` | 修改 | 弹窗遮罩 + 操作面板样式 |

---

### 任务 1：app.json 添加相册权限声明

**文件：**
- 修改：`c:\Users\w\Documents\GitHub\mouyu\app.json`（全文 15 行，在第 13 行 `"style": "v2"` 之前插入）

- [ ] **步骤 1：添加 permission 字段**

在 `app.json` 的 `"window"` 对象之后、`"style": "v2"` 之前，插入 `permission` 字段。修改后的完整文件：

```json
{
  "pages": [
    "pages/index/index",
    "pages/upload/upload",
    "pages/admin/admin"
  ],
  "window": {
    "navigationBarBackgroundColor": "#ffffff",
    "navigationBarTextStyle": "black",
    "navigationBarTitleText": "木偶鱼PF",
    "backgroundColor": "#f8f8f8"
  },
  "permission": {
    "scope.writePhotosAlbum": {
      "desc": "需要你的授权保存图片到相册"
    }
  },
  "style": "v2",
  "sitemapLocation": "sitemap.json"
}
```

- [ ] **步骤 2：验证 JSON 格式正确**

运行：`python -c "import json; json.load(open('app.json', encoding='utf-8')); print('JSON valid')"`
预期：输出 `JSON valid`

- [ ] **步骤 3：Commit**

```bash
git add app.json
git commit -m "feat(index): 添加相册写入权限声明"
```

---

### 任务 2：index.wxml 添加长按事件和弹窗模板

**文件：**
- 修改：`c:\Users\w\Documents\GitHub\mouyu\pages\index\index.wxml`（L52-59 图片标签 + L107 页面末尾）

- [ ] **步骤 1：给图片标签添加 bindlongpress 事件**

修改 `index.wxml` 第 52-59 行，在 `<image>` 标签上添加 `bindlongpress="onImageLongPress"`：

```xml
        <image
          class="meme-image"
          src="{{imageUrl}}"
          mode="widthFix"
          binderror="onImageError"
          bindload="onImageLoad"
          bindtap="onRefresh"
          bindlongpress="onImageLongPress"
        />
```

- [ ] **步骤 2：在页面末尾添加弹窗模板**

在 `index.wxml` 第 107 行（`</view>` 关闭 `.container` 之前）插入弹窗结构：

```xml
  <view class="action-sheet-mask" wx:if="{{showActionSheet}}" bindtap="hideActionSheet">
    <view class="action-sheet" catchtap="">
      <view class="action-item" bindtap="saveImageToAlbum">
        <text>保存到相册</text>
      </view>
      <button class="action-item action-share" open-type="share">
        <text>转发给好友</text>
      </button>
      <view class="action-divider"></view>
      <view class="action-item action-cancel" bindtap="hideActionSheet">
        <text>取消</text>
      </view>
    </view>
  </view>
```

注意：弹窗模板必须放在 `.container` 的 `</view>` 之前，与 `.stage-light` 同级。

- [ ] **步骤 3：Commit**

```bash
git add pages/index/index.wxml
git commit -m "feat(index): 添加长按弹窗模板"
```

---

### 任务 3：index.js 添加弹窗逻辑

**文件：**
- 修改：`c:\Users\w\Documents\GitHub\mouyu\pages\index\index.js`（data 字段 L22-45 + 新方法在 onShareAppMessage 之前 L655）

- [ ] **步骤 1：在 data 中添加 showActionSheet 字段**

在 `index.js` 第 38 行 `isDebugMode: false,` 之后添加：

```javascript
    showActionSheet: false,
```

- [ ] **步骤 2：添加 onImageLongPress 方法**

在 `onShareAppMessage` 方法（第 656 行）之前，添加三个方法：

```javascript
  onImageLongPress() {
    if (!this.data.imageUrl) return;
    this.setData({ showActionSheet: true });
  },

  hideActionSheet() {
    this.setData({ showActionSheet: false });
  },

  saveImageToAlbum() {
    this.setData({ showActionSheet: false });
    const imageUrl = this.data.imageUrl;
    if (!imageUrl) {
      wx.showToast({ title: '没有可保存的图片', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '保存中...' });
    wx.downloadFile({
      url: imageUrl,
      success: (res) => {
        if (res.statusCode === 200) {
          wx.saveImageToPhotosAlbum({
            filePath: res.tempFilePath,
            success: () => {
              wx.hideLoading();
              wx.showToast({ title: '已保存到相册', icon: 'success' });
            },
            fail: (err) => {
              wx.hideLoading();
              if (err.errMsg.indexOf('auth deny') !== -1 || err.errMsg.indexOf('authorize') !== -1) {
                wx.showModal({
                  title: '提示',
                  content: '需要你授权保存图片到相册',
                  confirmText: '去授权',
                  success: (modalRes) => {
                    if (modalRes.confirm) {
                      wx.openSetting();
                    }
                  }
                });
              } else {
                wx.showToast({ title: '保存失败', icon: 'none' });
              }
            }
          });
        } else {
          wx.hideLoading();
          wx.showToast({ title: '下载失败', icon: 'none' });
        }
      },
      fail: () => {
        wx.hideLoading();
        wx.showToast({ title: '下载失败', icon: 'none' });
      }
    });
  },
```

- [ ] **步骤 3：Commit**

```bash
git add pages/index/index.js
git commit -m "feat(index): 实现长按保存图片到相册"
```

---

### 任务 4：index.wxss 添加弹窗样式

**文件：**
- 修改：`c:\Users\w\Documents\GitHub\mouyu\pages\index\index.wxss`（在文件末尾追加）

- [ ] **步骤 1：在文件末尾添加弹窗样式**

在 `index.wxss` 第 489 行（文件末尾 `.debug-value.unseen` 样式之后）追加：

```css

.action-sheet-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 1000;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.action-sheet {
  width: 100%;
  background: #fff;
  border-radius: 24rpx 24rpx 0 0;
  padding: 16rpx 0;
  padding-bottom: calc(16rpx + env(safe-area-inset-bottom));
}

.action-item {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100rpx;
  font-size: 32rpx;
  color: #333;
}

.action-share {
  background: transparent;
  border: none;
  padding: 0;
  margin: 0;
  line-height: normal;
  border-radius: 0;
  width: 100%;
}

.action-share::after {
  border: none;
}

.action-divider {
  height: 16rpx;
  background: #f5f5f5;
  margin: 8rpx 0;
}

.action-cancel {
  color: #999;
}
```

- [ ] **步骤 2：Commit**

```bash
git add pages/index/index.wxss
git commit -m "feat(index): 添加长按弹窗样式"
```

---

### 任务 5：验证

- [ ] **步骤 1：在微信开发者工具中编译预览**

确认：
1. 编译无报错
2. 首页图片正常展示，单击仍可切换下一张
3. 长按图片弹出底部菜单（保存到相册 / 转发给好友 / 取消）
4. 点击遮罩或「取消」关闭弹窗
5. 点击「保存到相册」触发下载保存流程（模拟器可能不支持，需真机测试）
6. 点击「转发给好友」触发微信分享面板
7. 弹窗 z-index 正确，不被其他浮动按钮遮挡
8. 底部安全区域适配（iPhone 底部横条区域）
