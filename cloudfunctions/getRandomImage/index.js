const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();
const _ = db.command;

const IMAGE_WINDOW_DAYS = 7;
// 云函数端单次 get 上限 1000；超出由分页循环兜底
const BATCH_SIZE = 1000;
// 客户端只消费 _id（seenIds/点赞）和 url/tempUrl（显示），
// 只拉轻字段既快一个数量级，也避免把 md5/来源等整文档字段发给前端
const LIGHT_FIELDS = { _id: true, url: true };

async function fetchPool(where) {
  let all = [];
  let skip = 0;
  while (true) {
    const res = await db.collection('images')
      .where(where)
      .orderBy('createTime', 'desc')
      .skip(skip)
      .limit(BATCH_SIZE)
      .field(LIGHT_FIELDS)
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
      const result = await db.collection('images')
        .where({ status: 0 })
        .limit(BATCH_SIZE)
        .field(LIGHT_FIELDS)
        .get();
      allImages = result.data;
      console.log('DEBUG: debug mode, fetched', allImages.length, 'pending images');
    } else if (isFirstVisit) {
      // 首访：不做窗口过滤，整个过审池都可发
      allImages = await fetchPool({ status: 1 });
      console.log('DEBUG: first visit, full pool', allImages.length, 'approved images');
    } else {
      // 7 天窗口直接下推到 DB 查询（窗口内通常远小于全表）；
      // 窗口为空则回退到整个过审池（与旧版 JS 过滤语义一致，
      // 含 10 条缺 reviewTime 的老图：窗口查询天然排除、全量池天然包含）
      const windowStart = Date.now() - IMAGE_WINDOW_DAYS * 24 * 60 * 60 * 1000;
      const windowImages = await fetchPool({ status: 1, reviewTime: _.gte(windowStart) });
      console.log('DEBUG: window query got', windowImages.length, 'images in last', IMAGE_WINDOW_DAYS, 'days');
      if (windowImages.length > 0) {
        allImages = windowImages;
      } else {
        allImages = await fetchPool({ status: 1 });
        console.log('DEBUG: window empty, fallback to full pool', allImages.length, 'approved images');
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
