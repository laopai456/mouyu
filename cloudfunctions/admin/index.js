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

function getUserRole(openid) {
  if (isDeveloper(openid)) return 'developer';
  if (isCreator(openid)) return 'creator';
  return 'user';
}

exports.main = async (event, context) => {
  const { action, imageId, status, openid: targetOpenid, role } = event;
  const { OPENID } = cloud.getWXContext();

  try {
    if (action === 'checkAdmin') {
      return { isAdmin: isDeveloper(OPENID), openid: OPENID };
    }

    if (action === 'checkUpload') {
      return { canUpload: canUpload(OPENID), openid: OPENID, role: getUserRole(OPENID) };
    }

    if (!isDeveloper(OPENID)) {
      return { success: false, msg: '无权限操作', noPermission: true };
    }

    if (action === 'getPending') {
      const res = await db.collection('images')
        .where({ status: 0 })
        .orderBy('createTime', 'desc')
        .get();
      return { success: true, list: res.data };
    }

    if (action === 'getPendingCount') {
      const res = await db.collection('images')
        .where({ status: 0 })
        .count();
      return { success: true, count: res.total };
    }

    if (action === 'getList') {
      const s = status !== undefined ? status : 0;
      const res = await db.collection('images')
        .where({ status: s })
        .orderBy('createTime', 'desc')
        .limit(50)
        .get();
      return { success: true, list: res.data };
    }

    if (action === 'review') {
      await db.collection('images').doc(imageId).update({
        data: {
          status,
          reviewTime: Date.now(),
        }
      });
      return { success: true };
    }

    if (action === 'setRole') {
      const userRes = await db.collection('users')
        .where({ openid: targetOpenid })
        .count();

      if (userRes.total > 0) {
        await db.collection('users')
          .where({ openid: targetOpenid })
          .update({ data: { role } });
      } else {
        await db.collection('users').add({
          data: { openid: targetOpenid, role, createTime: Date.now() }
        });
      }
      return { success: true };
    }

    return { success: false, msg: '未知操作' };
  } catch (err) {
    return { success: false, msg: err.message };
  }
};
