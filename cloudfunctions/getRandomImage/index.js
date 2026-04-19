const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();
const _ = db.command;

const IMAGE_WINDOW_DAYS = 7;
const BATCH_SIZE = 100;

async function fetchAllApproved() {
  let all = [];
  let skip = 0;
  while (true) {
    const res = await db.collection('images')
      .where({ status: 1 })
      .orderBy('createTime', 'desc')
      .skip(skip)
      .limit(BATCH_SIZE)
      .get();
    all = all.concat(res.data);
    if (res.data.length < BATCH_SIZE) break;
    skip += BATCH_SIZE;
  }
  return all;
}

exports.main = async (event, context) => {
  try {
    const count = event.count || 1;
    const maxCount = 5;
    const requestCount = Math.min(count, maxCount);
    const seenIds = event.seenIds || [];
    const isFirstVisit = event.isFirstVisit === true;

    const wxContext = cloud.getWXContext();
    const envVersion = wxContext.envVersion || 'release';
    const isDebugMode = envVersion !== 'release';

    console.log('DEBUG: envVersion=', wxContext.envVersion, 'isDebugMode=', isDebugMode, 'isFirstVisit=', isFirstVisit);

    let allImages = [];

    if (isDebugMode) {
      const result = await db.collection('images').where({ status: 0 }).limit(BATCH_SIZE).get();
      allImages = result.data;
      console.log('DEBUG: debug mode, fetched', allImages.length, 'pending images');
    } else {
      allImages = await fetchAllApproved();
      console.log('DEBUG: fetched total', allImages.length, 'approved images');

      if (!isFirstVisit) {
        const now = Date.now();
        const windowMs = IMAGE_WINDOW_DAYS * 24 * 60 * 60 * 1000;
        const windowStart = now - windowMs;

        const windowImages = allImages.filter(img => img.reviewTime && img.reviewTime >= windowStart);
        console.log('DEBUG: window filter', windowImages.length, 'images in last', IMAGE_WINDOW_DAYS, 'days');

        if (windowImages.length > 0) {
          allImages = windowImages;
        }
      }
    }

    if (allImages.length === 0) {
      if (!isFirstVisit && !isDebugMode) {
        const allResult = await db.collection('images').where({ status: 1 }).count();
        if (allResult.total > 0) {
          return { success: false, message: '最近' + IMAGE_WINDOW_DAYS + '天没有新图片', noMore: true, windowExpired: true };
        }
      }
      return { success: false, message: '暂无图片', noMore: true };
    }

    const shuffled = allImages.sort(() => Math.random() - 0.5);
    const newImages = shuffled.filter(img => !seenIds.includes(img._id));
    const selected = newImages.slice(0, requestCount);

    console.log('DEBUG: selected', selected.length, 'images from', allImages.length, 'candidates');

    if (selected.length === 0 && !isFirstVisit && !isDebugMode) {
      return { success: false, message: '最近' + IMAGE_WINDOW_DAYS + '天没有新图片了', noMore: true };
    }

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
