const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  try {
    const { imageId } = event;
    const { OPENID } = cloud.getWXContext();
    const today = new Date().toISOString().split('T')[0];

    const logRes = await db.collection('like_logs')
      .where({ openid: OPENID, date: today })
      .count();

    if (logRes.total >= 3) {
      return { success: false, msg: '今天送花次数用完了' };
    }

    await db.collection('like_logs').add({
      data: { openid: OPENID, imageId, date: today }
    });

    await db.collection('images').doc(imageId).update({
      data: { likeCount: db.command.inc(1) }
    });

    return { success: true };
  } catch (err) {
    return { success: false, msg: err.message };
  }
};
