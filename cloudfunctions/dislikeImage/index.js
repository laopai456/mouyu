const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  try {
    const { imageId } = event;
    const { OPENID } = cloud.getWXContext();
    const openid = OPENID;
    const today = new Date().toISOString().split('T')[0];

    const logRes = await db.collection('dislike_logs')
      .where({ openid, date: today })
      .count();

    if (logRes.total >= 3) {
      return { success: false, msg: '今天踩的次数用完了' };
    }

    const existRes = await db.collection('dislike_logs')
      .where({ openid, imageId, date: today })
      .count();

    if (existRes.total > 0) {
      return { success: false, msg: '这张图已经踩过了' };
    }

    await db.collection('dislike_logs').add({
      data: { openid, imageId, date: today }
    });

    await db.collection('images').doc(imageId).update({
      data: { dislikeCount: db.command.inc(1) }
    });

    return { success: true };
  } catch (err) {
    return { success: false, msg: err.message };
  }
};
