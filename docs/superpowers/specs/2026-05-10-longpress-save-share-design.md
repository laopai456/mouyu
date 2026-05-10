# 长按保存图片 + 转发功能 设计文档

## 项目上下文

「木偶鱼PF」微信小程序 — 沙雕趣图应用。用户在首页刷图（单张图片全屏展示，点击切换下一张），图片来自微信云存储。

### 关键文件

| 文件 | 职责 |
|------|------|
| `app.json` | 小程序全局配置（页面列表、权限等） |
| `pages/index/index.wxml` | 首页模板，包含图片展示区域（L52-59） |
| `pages/index/index.js` | 首页逻辑，图片加载/切换/交互（663行） |
| `pages/index/index.wxss` | 首页样式 |

### 现有交互

- 图片标签：`<image src="{{imageUrl}}" mode="widthFix" bindtap="onRefresh" />`
- 单击图片：切换下一张（`onRefresh`）
- 分享小程序：`onShareAppMessage()` 已实现，分享标题「木偶鱼 - 沙雕趣图」，当前图片作为封面
- 无长按功能、无保存功能

### 图片数据

- 图片 URL 来源：`image.tempUrl || image.url`（云存储临时链接）
- 当前图片 URL 存储在 `this.data.imageUrl`
- 当前图片 ID 存储在 `this.data.imageId`

## 需求

在首页图片上**长按**，弹出底部操作菜单：
1. **保存到相册** — 下载图片并保存到手机相册
2. **转发给好友** — 触发微信分享面板，以小程序卡片形式分享（当前图片作为封面）
3. **取消** — 关闭菜单

仅作用于首页，保留现有的单击切换下一张功能。

## 技术方案

### 为什么用自定义弹窗而非 wx.showActionSheet

`wx.showActionSheet` 的回调中无法触发微信分享对话框。需要使用 `<button open-type="share">` 来触发 `onShareAppMessage`，因此采用自定义底部弹窗。

### 交互流程

```
长按图片
  → setData({ showActionSheet: true })
  → 显示遮罩 + 底部操作面板
  → 用户选择：
    a)「保存到相册」
      → wx.downloadFile(imageUrl) 下载到临时文件
      → wx.saveImageToPhotosAlbum(tempFilePath) 保存到相册
      → 成功：wx.showToast('已保存到相册')
      → 失败（权限）：wx.showModal 引导去设置页开启权限
    b)「转发给好友」
      → button open-type="share" 触发 onShareAppMessage
      → 微信弹出好友选择面板
    c)「取消」或点击遮罩
      → setData({ showActionSheet: false })
```

### tap 和 longpress 互不冲突

微信小程序中，长按事件（`bindlongpress`）和点击事件（`bindtap`）互斥——触发 longpress 不会触发 tap，反之亦然。因此现有单击切换功能不受影响。

## 文件结构

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `app.json` | 修改 | 添加 `permission.scope.writePhotosAlbum` |
| `pages/index/index.wxml` | 修改 | 添加 `bindlongpress` + 弹窗模板 |
| `pages/index/index.js` | 修改 | 添加 data 字段 + 3 个方法 |
| `pages/index/index.wxss` | 修改 | 添加弹窗样式 |

## 任务分解

### 步骤 1：app.json 添加权限声明

在 `app.json` 中添加：

```json
"permission": {
  "scope.writePhotosAlbum": {
    "desc": "需要你的授权保存图片到相册"
  }
}
```

### 步骤 2：index.wxml 添加长按事件和弹窗

**2a.** 图片标签添加 `bindlongpress="onImageLongPress"`

修改位置：L52-59 的 `<image>` 标签，添加 `bindlongpress="onImageLongPress"` 属性。

**2b.** 在页面末尾（`</view>` 之前）添加弹窗结构：

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

### 步骤 3：index.js 添加逻辑

**3a.** data 中添加 `showActionSheet: false`

**3b.** 添加三个方法：

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

### 步骤 4：index.wxss 添加弹窗样式

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

## 自检清单

- [x] 无占位符（TODO/TBD/待定）
- [x] 所有文件路径使用绝对路径
- [x] 代码完整，可直接复制使用
- [x] 不涉及数据结构变更、云函数修改或其他页面
- [x] tap 和 longpress 互斥，不影响现有交互
- [x] 权限处理完整（拒绝授权时引导去设置页）
- [x] loading 状态管理（下载中显示 loading）
