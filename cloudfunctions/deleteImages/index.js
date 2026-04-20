const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

const DEVELOPER_OPENIDS = [
  'oWatD3bwu0aVaFTPvrrerAU_C2zY'
];

exports.main = async (event, context) => {
  const { action, imageIds, id, md5, adminOpenid } = event;
  const { OPENID } = cloud.getWXContext();
  const requestOpenid = adminOpenid || OPENID;

  if (!DEVELOPER_OPENIDS.includes(requestOpenid)) {
    return { success: false, message: '无权限操作' };
  }

  if (action === 'delete') {
    if (!id) {
      return { success: false, message: '图片 ID 为空' };
    }
    try {
      await db.collection('images').doc(id).remove();
      return { success: true, message: '删除成功' };
    } catch (err) {
      console.error('删除失败', id, err);
      return { success: false, message: '删除失败', error: err };
    }
  }

  if (action === 'batchDelete') {
    if (!imageIds || imageIds.length === 0) {
      return { success: false, message: '图片 ID 列表为空' };
    }

    let successCount = 0;
    let failCount = 0;

    for (const id of imageIds) {
      try {
        await db.collection('images').doc(id).remove();
        successCount++;
      } catch (err) {
        console.error('删除失败', id, err);
        failCount++;
      }
    }

    return {
      success: true,
      successCount,
      failCount
    };
  }

  if (action === 'addToBlacklist') {
    if (!imageIds || imageIds.length === 0) {
      return { success: false, message: '图片 ID 列表为空' };
    }

    let successCount = 0;
    let failCount = 0;
    const now = Date.now();

    for (const id of imageIds) {
      try {
        const imageRes = await db.collection('images').doc(id).get();
        const image = imageRes.data;

        if (!image || !image.md5) {
          failCount++;
          continue;
        }

        const existRes = await db.collection('md5_blacklist')
          .where({ md5: image.md5 })
          .count();

        if (existRes.total === 0) {
          await db.collection('md5_blacklist').add({
            data: {
              md5: image.md5,
              createTime: now,
              sourceId: id
            }
          });
        }

        await db.collection('images').doc(id).remove();
        successCount++;
      } catch (err) {
        console.error('加入黑名单失败', id, err);
        failCount++;
      }
    }

    return {
      success: true,
      successCount,
      failCount,
      message: '已加入黑名单并删除'
    };
  }

  if (action === 'migrateBlacklist') {
    const now = Date.now();
    let processed = 0;
    let added = 0;

    const BATCH_SIZE = 10;

    const res = await db.collection('images')
      .where({ status: 2 })
      .limit(BATCH_SIZE)
      .get();

    for (const image of res.data) {
      if (!image.md5) continue;

      try {
        await db.collection('md5_blacklist').add({
          data: {
            md5: image.md5,
            createTime: now,
            sourceId: image._id
          }
        });
        added++;
      } catch (e) {
      }
      processed++;
    }

    return {
      success: true,
      message: `处理完成，共 ${processed} 条，新增 ${added} 条进黑名单`
    };
  }

  return { success: false, message: 'Unknown action' };
};