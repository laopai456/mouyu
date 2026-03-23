const app = getApp();

Page({
  data: {
    imageUrl: '',
    imageId: '',
    dislikeCount: 0,
    userInfo: null,
  },

  onLoad() {
    this.getUserInfo();
    this.loadRandomImage();
  },

  getUserInfo() {
    wx.getUserProfile({
      desc: '用于记录踩的数据',
      success: (res) => {
        this.setData({ userInfo: res.userInfo });
      },
      fail: () => {
        wx.showToast({ title: '需要授权才能踩', icon: 'none' });
      }
    });
  },

  loadRandomImage() {
    wx.showLoading({ title: '加载中...' });
    wx.cloud.callFunction({
      name: 'getRandomImage',
      success: (res) => {
        wx.hideLoading();
        if (res.result && res.result.image) {
          this.setData({
            imageUrl: res.result.image.url,
            imageId: res.result.image._id,
            dislikeCount: res.result.image.dislikeCount || 0,
          });
        } else {
          this.setData({ imageUrl: '', imageId: '' });
        }
      },
      fail: (err) => {
        wx.hideLoading();
        console.error(err);
        wx.showToast({ title: '加载失败', icon: 'none' });
      }
    });
  },

  onSwipe() {
    this.loadRandomImage();
  },

  onDislike() {
    if (!this.data.userInfo) {
      this.getUserInfo();
      return;
    }

    if (!this.data.imageId) {
      wx.showToast({ title: '暂无图片', icon: 'none' });
      return;
    }

    wx.showLoading({ title: '提交中...' });
    wx.cloud.callFunction({
      name: 'dislikeImage',
      data: {
        imageId: this.data.imageId,
        openid: this.data.userInfo.openId,
      },
      success: (res) => {
        wx.hideLoading();
        if (res.result && res.result.success) {
          wx.showToast({ title: '踩成功 💩', icon: 'none' });
          this.setData({ dislikeCount: this.data.dislikeCount + 1 });
          setTimeout(() => this.loadRandomImage(), 800);
        } else {
          wx.showToast({ title: res.result.msg || '踩失败', icon: 'none' });
        }
      },
      fail: (err) => {
        wx.hideLoading();
        console.error(err);
        wx.showToast({ title: '踩失败', icon: 'none' });
      }
    });
  },

  goUpload() {
    wx.navigateTo({ url: '/pages/upload/upload' });
  },
});
