const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  try {
    const { imageId, laughCount } = event;

    if (!imageId) {
      return { success: false, msg: '参数错误' };
    }

    if (typeof laughCount !== 'number' || laughCount < 0 || laughCount > 15) {
      return { success: false, msg: '计数不合法' };
    }

    await db.collection('images').doc(imageId).update({
      data: { laughCount: laughCount }
    });

    return { success: true };
  } catch (err) {
    return { success: false, msg: err.message };
  }
};
