const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

const DEVELOPER_OPENIDS = [
  'oWatD3bwu0aVaFTPvrrerAU_C2zY'
];

const CREATOR_OPENIDS = [
  'oWatD3bwu0aVaFTPvrrerAU_C2zY'
];

function isDeveloper(openid) {
  return DEVELOPER_OPENIDS.includes(openid);
}

function isCreator(openid) {
  return CREATOR_OPENIDS.includes(openid);
}

function canUpload(openid) {
  return isCreator(openid) || isDeveloper(openid);
}

exports.main = async (event, context) => {
  try {
    const { fileID, md5 } = event;
    const { OPENID } = cloud.getWXContext();
    const today = new Date().toISOString().split('T')[0];

    if (!canUpload(OPENID)) {
      return { success: false, msg: '无上传权限' };
    }

    if (md5) {
      const existRes = await db.collection('images')
        .where({ md5, status: db.command.in([0, 1]) })
        .count();

      if (existRes.total > 0) {
        return { success: false, msg: '该图片已存在，请勿重复上传' };
      }
    }

    if (!isDeveloper(OPENID)) {
      const countRes = await db.collection('images')
        .where({ uploaderOpenid: OPENID, date: today })
        .count();

      if (countRes.total >= 9) {
        return { success: false, msg: '今天上传次数已达上限（9张）' };
      }
    }

    await db.collection('images').add({
      data: {
        fileID,
        url: fileID,
        md5: md5 || '',
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
