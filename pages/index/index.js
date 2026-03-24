const app = getApp();

const PRELOAD_COUNT = 3;
const MIN_QUEUE_SIZE = 2;
const ADMIN_TAP_COUNT = 5;
const ADMIN_TAP_INTERVAL = 1000;

Page({
  data: {
    imageUrl: '',
    imageId: '',
    dislikeCount: 0,
    likeCount: 0,
    isLoading: false,
    isRefreshing: false,
    noMoreImages: false,
    hasLikedToday: false,
    canUpload: false,
  },

  imageQueue: [],
  preloading: false,
  seenIds: [],
  adminTapTimes: [],

  onLoad() {
    this.checkLikeStatus();
    this.checkUploadPermission();
    this.initImages();
  },

  checkUploadPermission() {
    wx.cloud.callFunction({
      name: 'admin',
      data: { action: 'checkUpload' },
      success: (res) => {
        if (res.result && res.result.canUpload) {
          this.setData({ canUpload: true });
        }
      },
      fail: (err) => {
        console.error('检查上传权限失败', err);
      }
    });
  },

  checkLikeStatus() {
    const today = new Date().toISOString().split('T')[0];
    const lastLikeDate = wx.getStorageSync('lastLikeDate');
    this.setData({ hasLikedToday: lastLikeDate === today });
  },

  async initImages() {
    this.setData({ isLoading: true });
    try {
      console.log('开始获取图片...');
      const images = await this.fetchImages(PRELOAD_COUNT);
      console.log('获取到的图片:', images);
      if (images && images.length > 0) {
        this.imageQueue = images;
        this.showNextImage();
      } else {
        console.log('没有获取到图片');
        this.setData({ noMoreImages: true });
      }
    } catch (err) {
      console.error('初始化图片失败', err);
      wx.showToast({ title: '加载失败: ' + err.message, icon: 'none', duration: 3000 });
    }
    this.setData({ isLoading: false });
  },

  fetchImages(count) {
    return new Promise((resolve, reject) => {
      console.log('调用云函数 getRandomImage, count:', count, 'seenIds:', this.seenIds.length);
      wx.cloud.callFunction({
        name: 'getRandomImage',
        data: { 
          count,
          seenIds: this.seenIds 
        },
        success: (res) => {
          console.log('云函数返回:', res);
          if (res.result && res.result.success) {
            if (res.result.images) {
              resolve(res.result.images);
            } else if (res.result.image) {
              resolve([res.result.image]);
            } else {
              reject(new Error(res.result?.message || '获取失败'));
            }
          } else {
            if (res.result && res.result.noMore) {
              this.setData({ noMoreImages: true });
              resolve([]);
            } else {
              reject(new Error(res.result?.message || '获取失败'));
            }
          }
        },
        fail: (err) => {
          console.error('云函数调用失败:', err);
          reject(err);
        }
      });
    });
  },

  showNextImage() {
    if (this.imageQueue.length === 0) {
      return false;
    }

    const image = this.imageQueue.shift();
    this.seenIds.push(image._id);
    
    const displayUrl = image.tempUrl || image.url;
    
    this.setData({
      imageUrl: displayUrl,
      imageId: image._id,
      dislikeCount: image.dislikeCount || 0,
      likeCount: image.likeCount || 0,
      noMoreImages: false,
    });

    this.preloadImages();

    return true;
  },

  async preloadImages() {
    if (this.preloading) return;
    if (this.imageQueue.length >= MIN_QUEUE_SIZE) return;

    this.preloading = true;
    try {
      const needCount = PRELOAD_COUNT - this.imageQueue.length;
      if (needCount > 0) {
        const images = await this.fetchImages(needCount);
        if (images && images.length > 0) {
          this.imageQueue.push(...images);
        }
      }
    } catch (err) {
      console.error('预加载失败', err);
    }
    this.preloading = false;
  },

  async onRefresh() {
    if (this.data.isLoading) {
      this.setData({ isRefreshing: false });
      return;
    }

    if (this.data.noMoreImages) {
      this.setData({ isRefreshing: false });
      return;
    }

    if (this.imageQueue.length > 0) {
      this.showNextImage();
      this.setData({ isRefreshing: false });
    } else {
      try {
        const images = await this.fetchImages(1);
        if (images && images.length > 0) {
          this.imageQueue.push(...images);
          this.showNextImage();
        }
      } catch (err) {
        console.error('刷新失败', err);
      }
      this.setData({ isRefreshing: false });
    }
  },

  onLike() {
    if (!this.data.imageId) {
      wx.showToast({ title: '暂无图片', icon: 'none' });
      return;
    }

    if (this.data.hasLikedToday) {
      wx.showToast({ title: '今天已经送过花了', icon: 'none' });
      return;
    }

    wx.showLoading({ title: '提交中...' });
    wx.cloud.callFunction({
      name: 'likeImage',
      data: {
        imageId: this.data.imageId,
      },
      success: (res) => {
        wx.hideLoading();
        if (res.result && res.result.success) {
          const today = new Date().toISOString().split('T')[0];
          wx.setStorageSync('lastLikeDate', today);
          this.setData({ 
            likeCount: this.data.likeCount + 1,
            hasLikedToday: true 
          });
          wx.showToast({ title: '送花成功 🌸', icon: 'none' });
        } else {
          wx.showToast({ title: res.result.msg || '送花失败', icon: 'none' });
        }
      },
      fail: (err) => {
        wx.hideLoading();
        console.error(err);
        wx.showToast({ title: '送花失败', icon: 'none' });
      }
    });
  },

  onDislike() {
    if (!this.data.imageId) {
      wx.showToast({ title: '暂无图片', icon: 'none' });
      return;
    }

    wx.showLoading({ title: '提交中...' });
    wx.cloud.callFunction({
      name: 'dislikeImage',
      data: {
        imageId: this.data.imageId,
      },
      success: (res) => {
        wx.hideLoading();
        if (res.result && res.result.success) {
          wx.showToast({ title: '踩成功 💩', icon: 'none' });
          this.setData({ dislikeCount: this.data.dislikeCount + 1 });
          setTimeout(() => {
            if (this.imageQueue.length > 0) {
              this.showNextImage();
            }
          }, 800);
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

  onTitleTap() {
    const now = Date.now();
    this.adminTapTimes.push(now);
    
    this.adminTapTimes = this.adminTapTimes.filter(t => now - t < ADMIN_TAP_INTERVAL);
    
    if (this.adminTapTimes.length >= ADMIN_TAP_COUNT) {
      this.adminTapTimes = [];
      wx.navigateTo({ url: '/pages/admin/admin' });
    }
  },

  goUpload() {
    wx.navigateTo({ url: '/pages/upload/upload' });
  },

  onImageLoad(e) {
    console.log('图片加载成功', e);
  },

  onImageError(e) {
    console.error('图片加载失败', e);
    console.error('当前图片URL:', this.data.imageUrl);
    wx.showToast({ title: '图片加载失败', icon: 'none' });
  },
});
