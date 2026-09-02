const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

// 白名单读环境变量（云开发控制台→云函数→配置→环境变量，逗号分隔；未配置=空名单=拒绝管理操作）
const DEVELOPER_OPENIDS = (process.env.ADMIN_OPENIDS || '').split(',').map(s => s.trim()).filter(Boolean);

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

  if (action === 'listMonths') {
    try {
      const BATCH_SIZE = 100;
      const monthMap = {};
      let skip = 0;
      let hasMore = true;

      while (hasMore) {
        const res = await db.collection('images')
          .field({ yearMonth: true, status: true })
          .skip(skip)
          .limit(BATCH_SIZE)
          .get();

        if (res.data.length === 0) {
          hasMore = false;
          break;
        }

        for (const item of res.data) {
          const ym = item.yearMonth;
          if (!ym) continue;
          if (!monthMap[ym]) {
            monthMap[ym] = { total: 0, pending: 0, passed: 0, rejected: 0 };
          }
          monthMap[ym].total++;
          if (item.status === 0) monthMap[ym].pending++;
          else if (item.status === 1) monthMap[ym].passed++;
          else if (item.status === 2) monthMap[ym].rejected++;
        }

        skip += BATCH_SIZE;
        if (res.data.length < BATCH_SIZE) hasMore = false;
      }

      const months = Object.entries(monthMap)
        .map(([yearMonth, stats]) => ({ yearMonth, ...stats }))
        .sort((a, b) => b.yearMonth.localeCompare(a.yearMonth));

      return { success: true, months };
    } catch (err) {
      console.error('listMonths 失败', err);
      return { success: false, message: '查询月份失败', error: err };
    }
  }

  if (action === 'deleteByMonth') {
    const { yearMonth } = event;
    if (!yearMonth) {
      return { success: false, message: '缺少 yearMonth 参数' };
    }

    const BATCH_SIZE = 100;
    let totalDeleted = 0;
    let hasMore = true;

    while (hasMore) {
      const res = await db.collection('images')
        .where({ yearMonth })
        .limit(BATCH_SIZE)
        .get();

      if (res.data.length === 0) {
        hasMore = false;
        break;
      }

      for (const item of res.data) {
        try {
          await db.collection('images').doc(item._id).remove();
          totalDeleted++;
        } catch (err) {
          console.error('删除失败', item._id, err);
        }
      }

      if (res.data.length < BATCH_SIZE) {
        hasMore = false;
      }
    }

    return {
      success: true,
      yearMonth,
      totalDeleted,
      message: `已删除 ${yearMonth} 月份的 ${totalDeleted} 张图片`
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