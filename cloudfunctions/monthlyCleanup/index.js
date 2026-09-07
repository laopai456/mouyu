const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();
const _ = db.command;

const BATCH_SIZE = 100;
// 保留当前月与上个月；每月3号跑时正好删掉「上上个月」及更早（累积式，漏跑下月自动补上）
const KEEP_MONTHS = 2;
// 云函数上限 60s，提前收尾返回，剩余部分留给下次触发/手动再跑
const SOFT_DEADLINE_MS = 50 * 1000;

// 白名单读环境变量 ADMIN_OPENIDS（逗号分隔；缺省空名单=拒绝手动调用，fail-safe）。
// 定时触发不走白名单；DevTools 控制台手动测试时 OPENID 为空，需在测试事件里带 adminOpenid。
const ADMIN_OPENIDS = (process.env.ADMIN_OPENIDS || '').split(',').map(s => s.trim()).filter(Boolean);

// 以北京时间（UTC+8）算 KEEP_MONTHS 个月前的月份，返回 'YYYY-MM'
function cutoffYearMonth(now = Date.now()) {
  const bj = new Date(now + 8 * 60 * 60 * 1000);
  const d = new Date(Date.UTC(bj.getUTCFullYear(), bj.getUTCMonth() - KEEP_MONTHS, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

exports.main = async (event = {}) => {
  const started = Date.now();

  const isTimer = event.Type === 'Timer' || event.TriggerName === 'monthlyCleanupTrigger';
  if (!isTimer) {
    const { OPENID } = cloud.getWXContext();
    const requestOpenid = event.adminOpenid || OPENID;
    if (!ADMIN_OPENIDS.includes(requestOpenid)) {
      console.log('[MONTHLY_CLEAN][WARN] unauthorized invoke, openid:', requestOpenid || '(empty)');
      return { success: false, message: '无权限操作' };
    }
  }

  const cutoff = cutoffYearMonth();
  console.log('[MONTHLY_CLEAN][INFO] start, cutoff <=', cutoff, 'dryRun:', !!event.dryRun);

  try {
    // 只下推单条件 yearMonth（避开多条件 where 丢条件的坑），status 内存过滤
    const candidateWhere = { yearMonth: _.lte(cutoff) };

    if (event.dryRun) {
      const countRes = await db.collection('images').where(candidateWhere).count();
      return {
        success: true,
        dryRun: true,
        cutoffYearMonth: cutoff,
        candidateCount: countRes.total,
        message: `dryRun：${cutoff} 及更早共 ${countRes.total} 张候选（含转发群组，实际执行会豁免 status=3）`
      };
    }

    let scanned = 0;
    let skippedForward = 0;
    let deletedCount = 0;
    let failedCount = 0;
    let storageFailed = 0;
    let timedOut = false;
    const failedIds = new Set();
    const deadline = started + SOFT_DEADLINE_MS;

    while (true) {
      if (Date.now() > deadline) {
        timedOut = true;
        console.log('[MONTHLY_CLEAN][WARN] soft deadline reached, leftover waits for next run');
        break;
      }

      const batch = await db.collection('images')
        .where(candidateWhere)
        .limit(BATCH_SIZE)
        .get();

      if (batch.data.length === 0) break;

      // 转发群组素材豁免（status=3 是 qqbot 滴灌池，与 autoCleanup 同款豁免）
      const targets = batch.data.filter(img => img.status !== 3);
      skippedForward += batch.data.length - targets.length;

      // 整批都是上轮删失败残留时会原地打转，直接收工
      if (targets.length > 0 && targets.every(img => failedIds.has(img._id))) {
        timedOut = false;
        console.log('[MONTHLY_CLEAN][WARN] only failed docs left, stop to avoid spin');
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
            console.log('[MONTHLY_CLEAN][WARN] storage delete fail count:', bad.length);
          }
        } catch (err) {
          storageFailed += fileIds.length;
          console.error('[MONTHLY_CLEAN][ERROR] deleteFile batch fail:', err);
        }
      }

      for (const img of targets) {
        try {
          await db.collection('images').doc(img._id).remove();
          deletedCount++;
        } catch (err) {
          failedCount++;
          failedIds.add(img._id);
          console.error('[MONTHLY_CLEAN][ERROR] remove doc fail:', img._id, err);
        }
      }

      scanned += batch.data.length;
      if (batch.data.length < BATCH_SIZE) break;
    }

    const summary = {
      success: true,
      cutoffYearMonth: cutoff,
      scanned,
      deletedCount,
      failedCount,
      storageFailed,
      skippedForward,
      timedOut,
      elapsedMs: Date.now() - started
    };
    console.log('[MONTHLY_CLEAN][INFO] done', JSON.stringify(summary));
    return summary;
  } catch (err) {
    console.error('[MONTHLY_CLEAN][ERROR] fatal:', err);
    return {
      success: false,
      cutoffYearMonth: cutoff,
      message: err.message
    };
  }
};
