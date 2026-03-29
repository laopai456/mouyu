const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();
const _ = db.command;

const IMAGE_WINDOW_DAYS = 3;
const MAX_SEEN_IDS = 50;

exports.main = async (event, context) => {
  try {
    const count = event.count || 1;
    const maxCount = 5;
    const requestCount = Math.min(count, maxCount);
    let seenIds = event.seenIds || [];
    const isFirstVisit = event.isFirstVisit === true;

    if (seenIds.length > MAX_SEEN_IDS) {
      seenIds = seenIds.slice(-MAX_SEEN_IDS);
    }

    let query = db.collection('images').where({ status: 1 });

    if (!isFirstVisit) {
      const now = Date.now();
      const windowMs = IMAGE_WINDOW_DAYS * 24 * 60 * 60 * 1000;
      const windowStart = new Date(now - windowMs);
      query = db.collection('images').where({
        status: 1,
        createTime: _.gte(windowStart.getTime())
      });
    }

    if (seenIds.length > 0) {
      query = query.where({
        _id: _.nin(seenIds)
      });
    }

    const totalResult = await query.count();

    if (totalResult.total === 0) {
      if (!isFirstVisit) {
        const allResult = await db.collection('images').where({ status: 1 }).count();
        if (allResult.total > 0) {
          return { success: false, message: '最近' + IMAGE_WINDOW_DAYS + '天没有新图片', noMore: true, windowExpired: true };
        }
      }
      return { success: false, message: '暂无图片', noMore: true };
    }

    const sampleSize = Math.min(requestCount * 3, 15);
    const result = await query.limit(sampleSize).get();

    if (result.data.length === 0) {
      return { success: false, message: '暂无新图片', noMore: true };
    }

    const shuffled = result.data.sort(() => Math.random() - 0.5);
    const selected = shuffled.slice(0, requestCount);

    const fileIDs = selected.map(img => img.url).filter(url => url);

    if (fileIDs.length > 0) {
      try {
        const tempUrlResult = await cloud.getTempFileURL({
          fileList: fileIDs
        });

        const urlMap = {};
        if (tempUrlResult.fileList) {
          tempUrlResult.fileList.forEach(item => {
            if (item.tempFileURL) {
              urlMap[item.fileID] = item.tempFileURL;
            }
          });
        }

        selected.forEach(img => {
          if (urlMap[img.url]) {
            img.tempUrl = urlMap[img.url];
          }
        });
      } catch (err) {
        console.error('获取临时链接失败', err);
      }
    }

    return { success: true, images: selected };
  } catch (err) {
    return { success: false, message: err.message };
  }
};