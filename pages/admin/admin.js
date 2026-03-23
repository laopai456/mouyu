Page({
  data: {
    currentTab: 0,
    images: [],
    pendingCount: 0,
    isAdmin: false,
    loading: true,
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
      
      if (!isAdmin) {
        wx.showToast({ title: '无权限访问', icon: 'none' });
        setTimeout(() => wx.navigateBack(), 1500);
      } else {
        this.setData({ isAdmin: true, loading: false });
        this.loadImages();
      }
    } catch (err) {
      console.error(err);
      wx.showToast({ title: '验证失败', icon: 'none' });
      setTimeout(() => wx.navigateBack(), 1500);
    }
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

      this.setData({ images });
    } catch (err) {
      console.error(err);
      wx.showToast({ title: '加载失败', icon: 'none' });
    }
  },

  formatTime(timestamp) {
    const date = new Date(timestamp);
    return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
  },

  previewImage(e) {
    wx.previewImage({ urls: [e.currentTarget.dataset.url] });
  },

  async approve(e) {
    if (!this.data.isAdmin) {
      wx.showToast({ title: '无权限', icon: 'none' });
      return;
    }
    
    const imageId = e.currentTarget.dataset.id;
    try {
      await wx.cloud.callFunction({
        name: 'admin',
        data: { action: 'review', imageId, status: 1 }
      });
      wx.showToast({ title: '已通过', icon: 'success' });
      this.loadImages();
    } catch (err) {
      wx.showToast({ title: '操作失败', icon: 'none' });
    }
  },

  async reject(e) {
    if (!this.data.isAdmin) {
      wx.showToast({ title: '无权限', icon: 'none' });
      return;
    }
    
    const imageId = e.currentTarget.dataset.id;
    try {
      await wx.cloud.callFunction({
        name: 'admin',
        data: { action: 'review', imageId, status: 2 }
      });
      wx.showToast({ title: '已拒绝', icon: 'success' });
      this.loadImages();
    } catch (err) {
      wx.showToast({ title: '操作失败', icon: 'none' });
    }
  },
});
