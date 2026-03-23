const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  try {
    const { fileID, openid } = event;

    await db.collection('images').add({
      data: {
        fileID,
        url: fileID,
        uploaderOpenid: openid || 'unknown',
        status: 1,
        dislikeCount: 0,
        createTime: Date.now(),
      }
    });

    return { success: true };
  } catch (err) {
    return { success: false, msg: err.message };
  }
};
