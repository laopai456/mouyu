const app = getApp();

const PRELOAD_COUNT = 3;
const MIN_QUEUE_SIZE = 2;
const MAX_SEEN_IDS = 500;
const ADMIN_TAP_COUNT = 5;
const ADMIN_TAP_INTERVAL = 1000;
const NO_MORE_TAP_COUNT = 3;
const NO_MORE_TAP_INTERVAL = 1000;

const NO_MORE_TEXTS = [
  '上会儿班吧，球球了。',
  '天气好，天气不好，天气刚刚好。',
  '电量耗尽，请充电后再刷~',
  '没了，已被掏空。',
  '图图跑了，可能是饿的。',
  '什么都没了，真的。',
  '精神状态：已离线'
];

Page({
  data: {
    imageUrl: '',
    imageId: '',
    dislikeCount: 0,
    likeCount: 0,
    isLoading: false,
    isRefreshing: false,
    noMoreImages: false,
    noMoreText: '',
    hasLikedToday: false,
    canUpload: false,
    flyingTexts: [],
    laughCount: 0,
    laughMode: false,
    stageLight: false,
    hasVisitedBefore: false,
    contactInfo: '',
    adminContact: '',
    submitContact: '',
    isDebugMode: false,
    debugStats: {
      pending: 0,
      approved: 0,
      unseen: 0
    },
  },

  imageQueue: [],
  preloading: false,
  seenIds: [],
  adminTapTimes: [],
  noMoreTapTimes: [],
  flyingTextId: 0,
  laughCounts: {},
  laughTimer: null,
  userDislikeToday: 0,
  dislikedImages: new Set(),

  onLoad() {
    const savedSeenIds = wx.getStorageSync('seenIds') || [];
    const hasVisited = wx.getStorageSync('hasVisitedBefore') || false;
    this.seenIds = savedSeenIds.length > MAX_SEEN_IDS
      ? savedSeenIds.slice(savedSeenIds.length - MAX_SEEN_IDS)
      : savedSeenIds;
    this.setData({ hasVisitedBefore: hasVisited });

    try {
      const accountInfo = wx.getAccountInfoSync();
      const envVersion = accountInfo.miniProgram.envVersion || 'release';
      const isDebugMode = envVersion !== 'release';
      this.setData({ isDebugMode });
      if (isDebugMode) {
        this.fetchDebugStats();
      }
    } catch (e) {
      console.log('获取小程序版本失败', e);
    }

    this.checkLikeStatus();
    this.checkUploadPermission();
    this.initImages();
  },

  fetchDebugStats() {
    wx.cloud.callFunction({
      name: 'admin',
      data: { action: 'getStats' },
      success: (res) => {
        if (res.result && res.result.success) {
          const stats = res.result.stats;
          const unseen = Math.max(0, stats.approved - this.seenIds.length);
          this.setData({
            debugStats: {
              pending: stats.pending,
              approved: stats.approved,
              unseen: unseen
            }
          });
        }
      },
      fail: (err) => {
        console.error('获取统计数据失败', err);
      }
    });
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
    const laughModeUnlocked = wx.getStorageSync('laughModeUnlocked');
    this.setData({
      hasLikedToday: lastLikeDate === today,
      laughMode: laughModeUnlocked === today
    });
  },

  fetchContact() {
    const db = wx.cloud.database();
    db.collection('qrcode').limit(1).get({
      success: (res) => {
        if (res.data && res.data.length > 0) {
          const item = res.data[0];
          this.setData({
            contactInfo: item.contact || '',
            adminContact: item.adminContact || '',
            submitContact: item.submitContact || ''
          });
        }
      }
    });
  },

  copyAdminContact() {
    if (this.data.adminContact) {
      wx.setClipboardData({
        data: this.data.adminContact,
        success: () => {
          wx.showToast({ title: '已复制', icon: 'success' });
        }
      });
    }
  },

  copySubmitContact() {
    if (this.data.submitContact) {
      wx.setClipboardData({
        data: this.data.submitContact,
        success: () => {
          wx.showToast({ title: '已复制', icon: 'success' });
        }
      });
    }
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
        const dayOfWeek = new Date().getDay();
        this._noMoreTimestamp = Date.now();
        this.setData({
          noMoreImages: true,
          noMoreText: NO_MORE_TEXTS[dayOfWeek]
        });
        this.fetchContact();
      }
    } catch (err) {
      console.error('初始化图片失败', err);
      wx.showToast({ title: '加载失败: ' + err.message, icon: 'none', duration: 3000 });
    }
    this.setData({ isLoading: false });
  },

  fetchImages(count) {
    return new Promise((resolve, reject) => {
      const isFirstVisit = !this.data.hasVisitedBefore;
      console.log('调用云函数 getRandomImage, count:', count, 'seenIds:', this.seenIds.length, 'isFirstVisit:', isFirstVisit);
      wx.cloud.callFunction({
        name: 'getRandomImage',
        data: {
          count,
          seenIds: this.seenIds,
          isFirstVisit
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
              const dayOfWeek = new Date().getDay();
              this._noMoreTimestamp = Date.now();
              this.setData({ noMoreImages: true, noMoreText: NO_MORE_TEXTS[dayOfWeek] });
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
    if (this.seenIds.length > MAX_SEEN_IDS) {
      this.seenIds = this.seenIds.slice(this.seenIds.length - MAX_SEEN_IDS);
    }
    try { wx.setStorageSync('seenIds', this.seenIds); } catch (e) { console.warn('seenIds写入失败', e); }

    if (this.data.isDebugMode && this.data.debugStats.unseen > 0) {
      this.setData({
        'debugStats.unseen': this.data.debugStats.unseen - 1
      });
    }

    if (!this.data.hasVisitedBefore) {
      try { wx.setStorageSync('hasVisitedBefore', true); } catch (e) { console.warn('hasVisitedBefore写入失败', e); }
      this.setData({ hasVisitedBefore: true });
    }

    const displayUrl = image.tempUrl || image.url;

    if (!this.laughCounts[image._id]) {
      this.laughCounts[image._id] = 0;
    }

    const alreadyDisliked = this.dislikedImages.has(image._id);
    const remainingDislikes = alreadyDisliked
      ? 0
      : Math.max(0, 3 - this.userDislikeToday);

    this.setData({
      imageUrl: displayUrl,
      imageId: image._id,
      dislikeCount: remainingDislikes,
      likeCount: image.likeCount || 0,
      noMoreImages: false,
      laughCount: this.laughCounts[image._id],
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
          const existingIds = new Set([...this.seenIds, ...this.imageQueue.map(img => img._id)]);
          const newImages = images.filter(img => !existingIds.has(img._id));
          if (newImages.length > 0) {
            this.imageQueue.push(...newImages);
          }
        }
      }
    } catch (err) {
      console.error('预加载失败', err);
    }
    this.preloading = false;
  },

  onScrollToUpper() {
    const now = Date.now();
    if (this.lastScrollToUpperTime && now - this.lastScrollToUpperTime < 1000) {
      return;
    }
    this.lastScrollToUpperTime = now;

    if (!this.data.isLoading && !this.data.noMoreImages) {
      this.onRefresh();
    }
  },

  async onRefresh() {
    if (this.data.isLoading) {
      this.setData({ isRefreshing: false });
      return;
    }

    if (this.data.noMoreImages) {
      if (this._noMoreTimestamp && Date.now() - this._noMoreTimestamp < 5 * 60 * 1000) {
        this.setData({ isRefreshing: false });
        return;
      }
      this.setData({ noMoreImages: false });
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
    console.log('onLike 被调用', 'imageId:', this.data.imageId, 'hasLikedToday:', this.data.hasLikedToday);

    if (!this.data.imageId) {
      console.log('imageId 为空，直接返回');
      return;
    }

    if (this.data.hasLikedToday) {
      console.log('今天已送过花，直接返回');
      if (this.data.laughMode) {
        this.setData({ laughMode: false });
        try { wx.setStorageSync('laughModeUnlocked', ''); } catch (e) { console.warn('laughModeUnlocked写入失败', e); }
      }
      return;
    }

    wx.cloud.callFunction({
      name: 'likeImage',
      data: {
        imageId: this.data.imageId,
      },
      success: (res) => {
        console.log('送花结果:', res);
        if (res.result && res.result.success === false) {
          console.log('送花失败:', res.result.msg);
          return;
        }
        const today = new Date().toISOString().split('T')[0];
        try { wx.setStorageSync('lastLikeDate', today); } catch (e) { console.warn('lastLikeDate写入失败', e); }
        try { wx.setStorageSync('laughModeUnlocked', today); } catch (e) { console.warn('laughModeUnlocked写入失败', e); }
        this.setData({
          likeCount: this.data.likeCount + 1,
          hasLikedToday: true,
          laughMode: true
        });
      },
      fail: (err) => {
        console.error('送花失败', err);
      }
    });
  },

  onDislike() {
    if (!this.data.imageId) {
      return;
    }

    if (this.userDislikeToday >= 3) {
      return;
    }

    if (this.dislikedImages.has(this.data.imageId)) {
      return;
    }

    this.showFlyingPoop();
    this.userDislikeToday++;
    this.dislikedImages.add(this.data.imageId);

    this.setData({ dislikeCount: 3 - this.userDislikeToday });

    wx.cloud.callFunction({
      name: 'dislikeImage',
      data: {
        imageId: this.data.imageId,
      },
      success: (res) => {
        if (res.result && res.result.success) {
          setTimeout(() => {
            if (this.imageQueue.length > 0) {
              this.showNextImage();
            }
          }, 800);
        }
      }
    });
  },

  showFlyingPoop() {
    const screenWidth = wx.getSystemInfoSync().windowWidth;
    const screenHeight = wx.getSystemInfoSync().windowHeight;
    const emojis = ['💩', '噗', '呕', '🤮', '呸'];
    const poop = emojis[Math.floor(Math.random() * emojis.length)];
    const id = ++this.flyingTextId;
    const startX = screenWidth * 0.3 + Math.random() * (screenWidth * 0.4);
    const startY = screenHeight * 0.5 + Math.random() * (screenHeight * 0.2);
    const fontSize = 80 + Math.floor(Math.random() * 40);
    const rotation = -30 + Math.random() * 60;
    const duration = 1200 + Math.random() * 600;

    const flyingText = {
      id,
      text: poop,
      style: `left: ${startX}px; top: ${startY}px; font-size: ${fontSize}rpx; --rotation: ${rotation}deg; animation-duration: ${duration}ms;`,
      effect: 'poop'
    };

    const flyingTexts = [...this.data.flyingTexts, flyingText];
    this.setData({ flyingTexts });

    setTimeout(() => {
      this.setData({
        flyingTexts: this.data.flyingTexts.filter(t => t.id !== id)
      });
    }, duration + 100);
  },

  onTitleTap() {
    const now = Date.now();

    if (this.data.isDebugMode) {
      this.noMoreTapTimes.push(now);
      this.noMoreTapTimes = this.noMoreTapTimes.filter(t => now - t < NO_MORE_TAP_INTERVAL);

      if (this.noMoreTapTimes.length >= NO_MORE_TAP_COUNT) {
        this.noMoreTapTimes = [];
        this.showNoMorePage();
        return;
      }
    }

    this.adminTapTimes.push(now);
    this.adminTapTimes = this.adminTapTimes.filter(t => now - t < ADMIN_TAP_INTERVAL);

    if (this.adminTapTimes.length >= ADMIN_TAP_COUNT) {
      this.adminTapTimes = [];
      wx.navigateTo({ url: '/pages/admin/admin' });
    }
  },

  showNoMorePage() {
    const dayOfWeek = new Date().getDay();
    this.setData({
      noMoreImages: true,
      noMoreText: NO_MORE_TEXTS[dayOfWeek]
    });
    this.fetchContact();
    wx.showToast({ title: '开发版预览', icon: 'none' });
  },

  onLaugh() {
    const screenWidth = wx.getSystemInfoSync().windowWidth;
    const screenHeight = wx.getSystemInfoSync().windowHeight;

    const texts = [
      '哈哈', '哈哈哈', '哈哈哈哈', '笑死', '笑死我了', '笑出猪叫',
      '233', '哈哈哈哈哈哈', '笑到肚子疼', '噗', '呵呵',
      '绷不住', '蚌埠住', '笑不活了', '太魔性了', '哈哈嗝',
      '笑到头掉', '救命', '救命😂', '救命，笑死', '我也会笑',
      '这也太准了', '确实', '绝了', '太准了', '上号上号',
      'dddd', '懂的都懂', '家人们谁懂', '破防了', 'yyds',
      '我和我的小伙伴们都惊呆了', '整个人都不好了', '何弃疗', '喜大普奔',
      '十动然拒', '说闘覺餘', '也是蠻拼的', '瀑布汗', '腫麼辦',
      '有木有', '傷不起', '給跪了', '香菇藍瘦', '藍瘦香菇',
      '崩潰', '醉了', '醉了醉了', '吃藥了', '你腫麼這麼傻',
      '笑到打嗝', '笑到抽筋', '笑出眼泪', '笑死咯🤣', '俺也一样',
      '禁止套娃', '芜湖起飞', '绝绝子', '集美', '爷青回', '泪目',
      '燃起来了', '笑哭😭', '捂脸😂', '笑到起飞🤪', '笑死啦🤣',
      '我笑了我', '真的笑死', '救命啊😂', '绷不住啦🤣', '笑出腹肌'
    ];
    const text = texts[Math.floor(Math.random() * texts.length)];

    const id = ++this.flyingTextId;
    const rand = Math.random();
    let startX;
    const textLen = text.replace(/[^\x00-\xff]/g, 'aa').length / 2;

    if (textLen > 5) {
      startX = Math.random() * (screenWidth * 0.5);
    } else if (textLen > 2) {
      if (rand < 0.6) {
        startX = Math.random() * (screenWidth * 0.55);
      } else {
        startX = screenWidth * 0.4 + Math.random() * (screenWidth * 0.25);
      }
    } else {
      if (rand < 0.5) {
        startX = Math.random() * (screenWidth * 0.45);
      } else if (rand < 0.75) {
        startX = Math.random() * (screenWidth * 0.6);
      } else {
        startX = screenWidth * 0.75 + Math.random() * (screenWidth * 0.2);
      }
    }
    const startY = screenHeight * 0.45 + Math.random() * (screenHeight * 0.35);

    const colors = [
      { bg: '#ff6b6b', shadow: 'rgba(255,107,107,0.6)' },
      { bg: '#ffd93d', shadow: 'rgba(255,217,61,0.6)' },
      { bg: '#6bcb77', shadow: 'rgba(107,203,119,0.6)' },
      { bg: '#4d96ff', shadow: 'rgba(77,150,255,0.6)' },
      { bg: '#9b59b6', shadow: 'rgba(155,89,182,0.6)' },
      { bg: '#ff9ff3', shadow: 'rgba(255,159,243,0.6)' },
      { bg: '#54a0ff', shadow: 'rgba(84,160,255,0.6)' },
      { bg: '#5f27cd', shadow: 'rgba(95,39,205,0.6)' },
    ];
    const colorScheme = colors[Math.floor(Math.random() * colors.length)];

    const fontSize = 36 + Math.floor(Math.random() * 24);
    const duration = 1800 + Math.random() * 800;

    const flyingText = {
      id,
      text,
      style: `left: ${startX}px; top: ${startY}px; font-size: ${fontSize}rpx; animation-duration: ${duration}ms;`
    };

    if (this.data.laughMode) {
      const effects = ['gradient', 'neon', 'glitch'];
      const effect = effects[Math.floor(Math.random() * effects.length)];
      flyingText.effect = effect;

      if (!this.data.stageLight) {
        this.setData({ stageLight: true });
      }
    } else {
      flyingText.style += ` color: #fff; background: ${colorScheme.bg}; box-shadow: 0 4rpx 20rpx ${colorScheme.shadow};`;
    }

    const flyingTexts = [...this.data.flyingTexts, flyingText];
    this.setData({ flyingTexts });

    if (this.laughTimer) {
      clearTimeout(this.laughTimer);
    }
    this.laughTimer = setTimeout(() => {
      this.setData({ stageLight: false });
    }, 3000);

    if (this.data.laughCount < 15 && this.data.imageId) {
      this.laughCounts[this.data.imageId] = (this.laughCounts[this.data.imageId] || 0) + 1;
      this.setData({ laughCount: this.laughCounts[this.data.imageId] });

      wx.cloud.callFunction({
        name: 'laughImage',
        data: {
          imageId: this.data.imageId,
          laughCount: this.laughCounts[this.data.imageId]
        },
        fail: (err) => {
          console.error('记录哈哈失败', err);
        }
      });
    }

    setTimeout(() => {
      this.setData({
        flyingTexts: this.data.flyingTexts.filter(t => t.id !== id)
      });
    }, duration + 100);
  },

  goUpload() {
    wx.navigateTo({ url: '/pages/upload/upload' });
  },

  onDelete() {
    if (!this.data.imageId) return;

    wx.showModal({
      title: '删除图片',
      content: '确定删除这张图片吗？',
      success: (res) => {
        if (res.confirm) {
          wx.cloud.callFunction({
            name: 'deleteImages',
            data: {
              action: 'delete',
              id: this.data.imageId
            },
            success: (res) => {
              if (res.result && res.result.success) {
                wx.showToast({ title: '已删除', icon: 'success' });
                if (this.imageQueue.length > 0) {
                  this.showNextImage();
                } else {
                  this.onRefresh();
                }
              } else {
                wx.showToast({ title: '删除失败', icon: 'none' });
              }
            },
            fail: () => {
              wx.showToast({ title: '删除失败', icon: 'none' });
            }
          });
        }
      }
    });
  },

  onImageLoad(e) {
    console.log('图片加载成功', e);
  },

  onImageError(e) {
    console.error('图片加载失败', e);
    console.error('当前图片URL:', this.data.imageUrl);

    if (this.imageQueue.length > 0) {
      this.showNextImage();
    } else {
      wx.showToast({ title: '图片加载失败', icon: 'none' });
    }
  },

  onShareAppMessage() {
    return {
      title: '木偶鱼 - 沙雕趣图',
      path: '/pages/index/index',
      imageUrl: this.data.imageUrl || ''
    }
  }
});
