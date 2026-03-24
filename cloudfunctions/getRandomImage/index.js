const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();
const _ = db.command;

exports.main = async (event, context) => {
  try {
    const count = event.count || 1;
    const maxCount = 5;
    const requestCount = Math.min(count, maxCount);
    const seenIds = event.seenIds || [];

    let query = db.collection('images').where({ status: 1 });
    
    if (seenIds.length > 0) {
      query = db.collection('images').where({
        status: 1,
        _id: _.nin(seenIds)
      });
    }

    const totalResult = await query.count();
    if (totalResult.total === 0) {
      return { success: false, message: '暂无图片', noMore: true };
    }

    const images = [];
    const usedIndexes = new Set();

    const fetchCount = Math.min(requestCount, totalResult.total);

    for (let i = 0; i < fetchCount; i++) {
      let randomIndex;
      let attempts = 0;
      const maxAttempts = 20;

      do {
        randomIndex = Math.floor(Math.random() * totalResult.total);
        attempts++;
      } while (usedIndexes.has(randomIndex) && attempts < maxAttempts);

      if (usedIndexes.has(randomIndex)) {
        continue;
      }
      usedIndexes.add(randomIndex);

      const result = await query
        .skip(randomIndex)
        .limit(1)
        .get();

      if (result.data.length > 0) {
        images.push(result.data[0]);
      }
    }

    if (images.length > 0) {
      const fileIDs = images.map(img => img.url).filter(url => url);
      
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
          
          images.forEach(img => {
            if (urlMap[img.url]) {
              img.tempUrl = urlMap[img.url];
            }
          });
        } catch (err) {
          console.error('获取临时链接失败', err);
        }
      }
      
      return { success: true, images: images };
    }

    return { success: false, message: '获取失败', noMore: true };
  } catch (err) {
    return { success: false, message: err.message };
  }
};
