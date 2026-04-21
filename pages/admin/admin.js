Page({
  data: {
    currentTab: 0,
    images: [],
    currentImage: null,
    currentIndex: 0,
    pendingCount: 0,
    isAdmin: false,
    loading: true,
    openid: '',
  },

  onLoad() {
    this.checkAdmin();
  },

  onShow() {
    if (this.data.isAdmin) {
      this.loadImages();
    }
  },

  async checkAdmin() {
    try {
      const res = await wx.cloud.callFunction({ 
        name: 'admin', 
        data: { action: 'checkAdmin' } 
      });
      
      const isAdmin = res.result?.isAdmin || false;
      const openid = res.result?.openid || '';
      
      this.setData({ 
        isAdmin, 
        openid,
        loading: false 
      });
      
      if (isAdmin) {
        this.loadImages();
      }
    } catch (err) {
      console.error(err);
      this.setData({ loading: false });
    }
  },

  copyOpenid() {
    wx.setClipboardData({
      data: this.data.openid,
      success: () => {
        wx.showToast({ title: '已复制', icon: 'success' });
      }
    });
  },

  switchTab(e) {
    const tab = parseInt(e.currentTarget.dataset.tab);
    this.setData({ currentTab: tab });
    this.loadImages();
  },

  async loadImages() {
    if (!this.data.isAdmin) return;
    
    const statusMap = [0, 1, 2];
    const status = statusMap[this.data.currentTab];

    try {
      if (status === 0) {
        const countRes = await wx.cloud.callFunction({ 
          name: 'admin', 
          data: { action: 'getPendingCount' } 
        });
        this.setData({ pendingCount: countRes.result?.count || 0 });
      }

      const res = await wx.cloud.callFunction({
        name: 'admin',
        data: { action: 'getList', status }
      });

      const images = (res.result?.list || []).map(item => ({
        ...item,
        createTimeStr: this.formatTime(item.createTime)
      }));

      const updateData = { images };
      if (status === 0 && images.length > 0) {
        updateData.currentIndex = 0;
        updateData.currentImage = images[0];
      } else if (status === 0) {
        updateData.currentImage = null;
        updateData.currentIndex = 0;
      }
      this.setData(updateData);
    } catch (err) {
      console.error(err);
      wx.showToast({ title: '加载失败', icon: 'none' });
    }
  },

  formatTime(timestamp) {
    const date = new Date(timestamp);
    return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
  },

  previewCurrentImage() {
    if (!this.data.currentImage) return;
    wx.previewImage({ urls: [this.data.currentImage.url] });
  },

  previewImage(e) {
    wx.previewImage({ urls: [e.currentTarget.dataset.url] });
  },

  async approve() {
    if (!this.data.isAdmin) {
      wx.showToast({ title: '无权限', icon: 'none' });
      return;
    }
    if (!this.data.currentImage) return;

    const imageId = this.data.currentImage._id;
    try {
      await wx.cloud.callFunction({
        name: 'admin',
        data: { action: 'review', imageId, status: 1 }
      });
      wx.showToast({ title: '已通过', icon: 'success' });

      const { images, currentIndex, pendingCount } = this.data;
      const newImages = images.filter((_, i) => i !== currentIndex);
      const newPendingCount = Math.max(0, pendingCount - 1);

      if (newImages.length > 0) {
        const nextIndex = Math.min(currentIndex, newImages.length - 1);
        this.setData({
          images: newImages,
          currentIndex: nextIndex,
          currentImage: newImages[nextIndex],
          pendingCount: newPendingCount,
        });
      } else {
        this.setData({
          images: [],
          currentImage: null,
          currentIndex: 0,
          pendingCount: newPendingCount,
        });
      }
    } catch (err) {
      wx.showToast({ title: '操作失败', icon: 'none' });
    }
  },

  async reject() {
    if (!this.data.isAdmin) {
      wx.showToast({ title: '无权限', icon: 'none' });
      return;
    }
    if (!this.data.currentImage) return;

    const imageId = this.data.currentImage._id;
    try {
      await wx.cloud.callFunction({
        name: 'admin',
        data: { action: 'review', imageId, status: 2 }
      });
      wx.showToast({ title: '已拒绝', icon: 'success' });

      const { images, currentIndex, pendingCount } = this.data;
      const newImages = images.filter((_, i) => i !== currentIndex);
      const newPendingCount = Math.max(0, pendingCount - 1);

      if (newImages.length > 0) {
        const nextIndex = Math.min(currentIndex, newImages.length - 1);
        this.setData({
          images: newImages,
          currentIndex: nextIndex,
          currentImage: newImages[nextIndex],
          pendingCount: newPendingCount,
        });
      } else {
        this.setData({
          images: [],
          currentImage: null,
          currentIndex: 0,
          pendingCount: newPendingCount,
        });
      }
    } catch (err) {
      wx.showToast({ title: '操作失败', icon: 'none' });
    }
  },
});
