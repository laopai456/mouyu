const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

const BATCH_SIZE = 100;
// 保留当前周与上周；每周一跑时正好删掉「上上周」及更早（累积式，漏跑下周一自动补上）
const KEEP_MS = 7 * 24 * 60 * 60 * 1000;
// 云函数上限 60s，提前收尾返回，剩余部分留给下次触发/手动再跑
const SOFT_DEADLINE_MS = 50 * 1000;

// 白名单读环境变量 ADMIN_OPENIDS（逗号分隔；缺省空名单=拒绝，fail-safe）。
// 只约束「真删」：定时触发与 dryRun（只统计不删）不走白名单，部署后即可直接测试；
// DevTools 控制台手动真删时 OPENID 为空，需在测试事件里带 adminOpenid，且云端已配 ADMIN_OPENIDS。
const ADMIN_OPENIDS = (process.env.ADMIN_OPENIDS || '').split(',').map(s => s.trim()).filter(Boolean);

// 上周周一 00:00（北京时间）对应的 UTC 毫秒戳，返回 { ts, date }
function cutoff(now = Date.now()) {
  const bj = new Date(now + 8 * 60 * 60 * 1000); // 偏移成北京时间钟面，再用 UTC 方法读
  const daysSinceMonday = (bj.getUTCDay() + 6) % 7; // 周一=0 ... 周日=6
  const thisMondayBjWall = Date.UTC(bj.getUTCFullYear(), bj.getUTCMonth(), bj.getUTCDate()) - daysSinceMonday * 86400000;
  const ts = thisMondayBjWall - KEEP_MS - 8 * 60 * 60 * 1000; // 减7天得上周周一，再减回8h偏移成真实UTC毫秒
  const d = new Date(ts + 8 * 60 * 60 * 1000);
  const date = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
  return { ts, date };
}

exports.main = async (event = {}) => {
  const started = Date.now();

  const isTimer = event.Type === 'Timer' || event.TriggerName === 'weeklyGroupCleanupTrigger';
  // dryRun 只读统计不删数据，免白名单，方便部署后直接验证
  if (!isTimer && !event.dryRun) {
    const { OPENID } = cloud.getWXContext();
    const requestOpenid = event.adminOpenid || OPENID;
    if (!ADMIN_OPENIDS.includes(requestOpenid)) {
      console.log('[WEEKLY_GROUP_CLEAN][WARN] unauthorized invoke, openid:', requestOpenid || '(empty)');
      return { success: false, message: '无权限操作' };
    }
  }

  const cutoffInfo = cutoff();
  console.log('[WEEKLY_GROUP_CLEAN][INFO] start, createTime <', cutoffInfo.date, 'dryRun:', !!event.dryRun);

  try {
    // 只下推单条件 status=3（避开多条件 where 丢条件的坑），createTime 内存过滤
    const candidateWhere = { status: 3 };

    if (event.dryRun) {
      let poolCount = 0;
      let candidateCount = 0;
      while (true) {
        const batch = await db.collection('images')
          .where(candidateWhere)
          .skip(poolCount)
          .limit(BATCH_SIZE)
          .get();
        if (batch.data.length === 0) break;
        poolCount += batch.data.length;
        candidateCount += batch.data.filter(img => (img.createTime || 0) < cutoffInfo.ts).length;
        if (batch.data.length < BATCH_SIZE) break;
      }
      return {
        success: true,
        dryRun: true,
        cutoffDate: cutoffInfo.date,
        poolCount,
        candidateCount,
        message: `dryRun：转发群组池共 ${poolCount} 张，其中 ${candidateCount} 张 createTime 早于 ${cutoffInfo.date}（上上周及更早，将被删除）`
      };
    }

    let scanned = 0;
    let deletedCount = 0;
    let failedCount = 0;
    let storageFailed = 0;
    let timedOut = false;
    const failedIds = new Set();
    const deadline = started + SOFT_DEADLINE_MS;

    while (true) {
      if (Date.now() > deadline) {
        timedOut = true;
        console.log('[WEEKLY_GROUP_CLEAN][WARN] soft deadline reached, leftover waits for next run');
        break;
      }

      // createTime 升序：最老的排最前，删完即前进；新图（保留窗口内）沉底自然终止
      const batch = await db.collection('images')
        .where(candidateWhere)
        .orderBy('createTime', 'asc')
        .limit(BATCH_SIZE)
        .get();

      if (batch.data.length === 0) break;

      const targets = batch.data.filter(img => (img.createTime || 0) < cutoffInfo.ts);
      // 首批全是保留窗口内的图 = 清理已完成
      if (targets.length === 0) break;

      // 整批都是上轮删失败残留时会原地打转，直接收工
      if (targets.every(img => failedIds.has(img._id))) {
        timedOut = false;
        console.log('[WEEKLY_GROUP_CLEAN][WARN] only failed docs left, stop to avoid spin');
        break;
      }

      // 存储文件批量删（deleteFile 单次上限 100 个 fileID）
      const fileIds = targets.map(img => img.fileID).filter(Boolean);
      if (fileIds.length > 0) {
        try {
          const delRes = await cloud.deleteFile({ fileList: fileIds });
          const bad = (delRes.fileList || []).filter(f => f.status !== 0);
          storageFailed += bad.length;
          if (bad.length > 0) {
            console.log('[WEEKLY_GROUP_CLEAN][WARN] storage delete fail count:', bad.length);
          }
        } catch (err) {
          storageFailed += fileIds.length;
          console.error('[WEEKLY_GROUP_CLEAN][ERROR] deleteFile batch fail:', err);
        }
      }

      for (const img of targets) {
        try {
          await db.collection('images').doc(img._id).remove();
          deletedCount++;
        } catch (err) {
          failedCount++;
          failedIds.add(img._id);
          console.error('[WEEKLY_GROUP_CLEAN][ERROR] remove doc fail:', img._id, err);
        }
      }

      scanned += targets.length;
    }

    const summary = {
      success: true,
      cutoffDate: cutoffInfo.date,
      scanned,
      deletedCount,
      failedCount,
      storageFailed,
      timedOut,
      elapsedMs: Date.now() - started
    };
    console.log('[WEEKLY_GROUP_CLEAN][INFO] done', JSON.stringify(summary));
    return summary;
  } catch (err) {
    console.error('[WEEKLY_GROUP_CLEAN][ERROR] fatal:', err);
    return {
      success: false,
      cutoffDate: cutoffInfo.date,
      message: err.message
    };
  }
};
