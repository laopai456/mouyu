const app = getApp();

const PRELOAD_COUNT = 3;
const MIN_QUEUE_SIZE = 2;
const ADMIN_TAP_COUNT = 5;
const ADMIN_TAP_INTERVAL = 1000;

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
    qrcodeUrl: '',
    qrcodeDaysLeft: 0,
  },

  imageQueue: [],
  preloading: false,
  seenIds: [],
  adminTapTimes: [],
  flyingTextId: 0,
  laughCounts: {},
  laughTimer: null,
  userDislikeToday: 0,
  dislikedImages: new Set(),

  onLoad() {
    const savedSeenIds = wx.getStorageSync('seenIds') || [];
    const hasVisited = wx.getStorageSync('hasVisitedBefore') || false;
    this.seenIds = savedSeenIds;
    this.setData({ hasVisitedBefore: hasVisited });

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
    const laughModeUnlocked = wx.getStorageSync('laughModeUnlocked');
    this.setData({
      hasLikedToday: lastLikeDate === today,
      laughMode: laughModeUnlocked === today
    });
  },

  fetchQRCode() {
    const db = wx.cloud.database();
    console.log('开始获取二维码...');
    db.collection('qrcode').limit(1).get({
      success: (res) => {
        console.log('二维码查询结果:', res);
        if (res.data && res.data.length > 0) {
          const item = res.data[0];
          console.log('二维码数据:', item);
          const createTime = item.createTime || item.updateTime;
          const now = Date.now();
          const sevenDays = 7 * 24 * 60 * 60 * 1000;
          
          if (createTime && now - createTime <= sevenDays) {
            const daysLeft = Math.max(0, Math.ceil((sevenDays - (now - createTime)) / (24 * 60 * 60 * 1000)));
            console.log('二维码有效，剩余天数:', daysLeft, 'URL:', item.url);
            
            if (item.url && item.url.startsWith('cloud://')) {
              console.log('调用 getTempFileURL...');
              wx.cloud.getTempFileURL({
                fileList: [item.url],
                success: (tempRes) => {
                  console.log('getTempFileURL 结果:', tempRes);
                  if (tempRes.fileList && tempRes.fileList[0] && tempRes.fileList[0].tempFileURL) {
                    console.log('临时URL:', tempRes.fileList[0].tempFileURL);
                    this.setData({
                      qrcodeUrl: tempRes.fileList[0].tempFileURL,
                      qrcodeDaysLeft: daysLeft
                    });
                  }
                },
                fail: (err) => {
                  console.error('getTempFileURL 失败:', err);
                }
              });
            } else {
              console.log('直接使用URL:', item.url);
              this.setData({
                qrcodeUrl: item.url,
                qrcodeDaysLeft: daysLeft
              });
            }
          } else {
            console.log('二维码已过期');
          }
        } else {
          console.log('没有二维码数据');
        }
      },
      fail: (err) => {
        console.error('查询二维码失败:', err);
      }
    });
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
        this.setData({
          noMoreImages: true,
          noMoreText: NO_MORE_TEXTS[dayOfWeek]
        });
        this.fetchQRCode();
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
    wx.setStorageSync('seenIds', this.seenIds);

    if (!this.data.hasVisitedBefore) {
      wx.setStorageSync('hasVisitedBefore', true);
      this.setData({ hasVisitedBefore: true });
    }

    const displayUrl = image.tempUrl || image.url;

    if (!this.laughCounts[image._id]) {
      this.laughCounts[image._id] = 0;
    }

    const alreadyDisliked = this.dislikedImages.has(image._id);
    const remainingDislikes = alreadyDisliked
      ? Math.max(0, 3 - this.userDislikeToday)
      : 3;

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
    console.log('onLike 被调用', 'imageId:', this.data.imageId, 'hasLikedToday:', this.data.hasLikedToday);

    if (!this.data.imageId) {
      console.log('imageId 为空，直接返回');
      return;
    }

    if (this.data.hasLikedToday) {
      console.log('今天已送过花，直接返回');
      if (this.data.laughMode) {
        this.setData({ laughMode: false });
        wx.setStorageSync('laughModeUnlocked', '');
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
        wx.setStorageSync('lastLikeDate', today);
        wx.setStorageSync('laughModeUnlocked', today);
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
    this.adminTapTimes.push(now);
    
    this.adminTapTimes = this.adminTapTimes.filter(t => now - t < ADMIN_TAP_INTERVAL);
    
    if (this.adminTapTimes.length >= ADMIN_TAP_COUNT) {
      this.adminTapTimes = [];
      wx.navigateTo({ url: '/pages/admin/admin' });
    } else if (this.adminTapTimes.length >= 3) {
      this.setData({ noMoreImages: true, noMoreText: '测试模式' });
      this.fetchQRCode();
    }
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
