const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  try {
    const count = await db.collection('images').where({ status: 1 }).count();
    if (count.total === 0) {
      return { success: false, message: '暂无图片' };
    }

    const randomIndex = Math.floor(Math.random() * count.total);
    const result = await db.collection('images')
      .where({ status: 1 })
      .skip(randomIndex)
      .limit(1)
      .get();

    if (result.data.length > 0) {
      return { success: true, image: result.data[0] };
    }

    return { success: false, message: '获取失败' };
  } catch (err) {
    return { success: false, message: err.message };
  }
};
