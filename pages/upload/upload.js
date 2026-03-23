const app = getApp();

Page({
  data: {
    images: [],
    uploading: false,
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

  async uploadImages() {
    if (this.data.uploading) return;
    if (this.data.images.length === 0) {
      wx.showToast({ title: '请先选择图片', icon: 'none' });
      return;
    }

    this.setData({ uploading: true });
    wx.showLoading({ title: '上传中...' });

    let uploaded = 0;
    let failed = 0;

    for (const path of this.data.images) {
      try {
        const uploadRes = await new Promise((resolve, reject) => {
          wx.cloud.uploadFile({
            cloudPath: `memes/${Date.now()}_${Math.random().toString(36).substr(2, 9)}.jpg`,
            filePath: path,
            success: resolve,
            fail: reject
          });
        });

        const addRes = await new Promise((resolve, reject) => {
          wx.cloud.callFunction({
            name: 'addImage',
            data: { fileID: uploadRes.fileID },
            success: resolve,
            fail: reject
          });
        });

        if (!addRes.result?.success) {
          failed++;
          if (addRes.result?.msg) {
            wx.hideLoading();
            wx.showToast({ title: addRes.result.msg, icon: 'none', duration: 2000 });
            this.setData({ uploading: false });
            return;
          }
        }
        uploaded++;
      } catch (err) {
        failed++;
        console.error('上传失败', err);
      }
    }

    wx.hideLoading();
    
    if (failed === 0) {
      wx.showModal({
        title: '上传成功',
        content: '图片已提交，审核通过后将展示',
        showCancel: false,
        success: () => {
          this.setData({ images: [] });
          wx.navigateBack();
        }
      });
    } else if (uploaded > 0) {
      wx.showToast({ title: `${uploaded}张成功，${failed}张失败`, icon: 'none' });
    } else {
      wx.showToast({ title: '上传失败', icon: 'none' });
    }
    
    this.setData({ uploading: false });
  },
});
