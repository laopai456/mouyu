const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  const { action, imageId, status, openid, role } = event;

  try {
    if (action === 'getPending') {
      const res = await db.collection('images')
        .where({ status: 0 })
        .orderBy('createTime', 'desc')
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
        .where({ openid })
        .count();

      if (userRes.total > 0) {
        await db.collection('users')
          .where({ openid })
          .update({ data: { role } });
      } else {
        await db.collection('users').add({
          data: { openid, role, createTime: Date.now() }
        });
      }
      return { success: true };
    }

    return { success: false, msg: '未知操作' };
  } catch (err) {
    return { success: false, msg: err.message };
  }
};
