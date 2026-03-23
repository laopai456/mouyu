const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  try {
    const { fileID } = event;
    const { OPENID } = cloud.getWXContext();
    const today = new Date().toISOString().split('T')[0];

    const countRes = await db.collection('images')
      .where({ uploaderOpenid: OPENID, date: today })
      .count();

    if (countRes.total >= 9) {
      return { success: false, msg: '今天上传次数已达上限（9张）' };
    }

    await db.collection('images').add({
      data: {
        fileID,
        url: fileID,
        uploaderOpenid: OPENID,
        status: 0,
        dislikeCount: 0,
        likeCount: 0,
        date: today,
        createTime: Date.now(),
      }
    });

    return { success: true, msg: '上传成功，等待审核后展示' };
  } catch (err) {
    return { success: false, msg: err.message };
  }
};
