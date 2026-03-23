const app = getApp();

Page({
  data: {
    images: [],
    uploading: false,
  },

  onLoad() {
    this.getUserInfo();
  },

  getUserInfo() {
    wx.getUserProfile({
      desc: '用于记录上传者',
      success: (res) => {
        this.setData({ userInfo: res.userInfo });
      }
    });
  },

  chooseImage() {
    wx.chooseMedia({
      count: 9,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        const tempFiles = res.tempFiles.map(f => f.tempFilePath);
        this.setData({
          images: this.data.images.concat(tempFiles).slice(0, 9)
        });
      }
    });
  },

  removeImage(e) {
    const index = e.currentTarget.dataset.index;
    this.data.images.splice(index, 1);
    this.setData({ images: this.data.images });
  },

  uploadImages() {
    if (this.data.uploading) return;
    if (this.data.images.length === 0) {
      wx.showToast({ title: '请先选择图片', icon: 'none' });
      return;
    }

    this.setData({ uploading: true });
    wx.showLoading({ title: '上传中...' });

    let uploaded = 0;
    const total = this.data.images.length;

    this.data.images.forEach((path, index) => {
      wx.cloud.uploadFile({
        cloudPath: `memes/${Date.now()}_${index}.jpg`,
        filePath: path,
        success: (res) => {
          wx.cloud.callFunction({
            name: 'addImage',
            data: {
              fileID: res.fileID,
              openid: this.data.userInfo?.openId || 'test'
            },
            success: (r) => {
              uploaded++;
              if (uploaded === total) {
                wx.hideLoading();
                wx.showToast({ title: '上传成功', icon: 'success' });
                this.setData({ images: [], uploading: false });
              }
            },
            fail: (err) => {
              uploaded++;
              console.error('添加记录失败', err);
              if (uploaded === total) {
                wx.hideLoading();
                wx.showToast({ title: '部分上传失败', icon: 'none' });
                this.setData({ uploading: false });
              }
            }
          });
        },
        fail: (err) => {
          uploaded++;
          console.error('上传失败', err);
          if (uploaded === total) {
            wx.hideLoading();
            wx.showToast({ title: '上传失败', icon: 'none' });
            this.setData({ uploading: false });
          }
        }
      });
    });
  },
});
