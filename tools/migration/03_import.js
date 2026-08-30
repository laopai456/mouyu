// 03_import.js — 导入目标环境：集合加前缀 + fileID 改写 + 保留 _id（幂等可重跑）
// 用法: node 03_import.js [--dry-run]
// 依赖: staging/collections/*.json + staging/file_map.json（01 的产物）
const fs = require('fs');
const path = require('path');
const CloudBase = require('@cloudbase/node-sdk');

const cfg = require('./config.json');
const DRY = process.argv.includes('--dry-run');
const staging = path.resolve(__dirname, cfg.stagingDir);

function log(level, msg) { console.log(`${level} [import] ${msg}`); }

(async () => {
  const fileMap = JSON.parse(fs.readFileSync(path.join(staging, 'file_map.json'), 'utf8'));
  const app = CloudBase.init({
    env: cfg.target.envId,
    secretId: cfg.secretId,
    secretKey: cfg.secretKey,
  });
  const db = app.database();

  for (const name of cfg.collections) {
    const file = path.join(staging, 'collections', `${name}.json`);
    if (!fs.existsSync(file)) { log('WARN', `${name} 无导出文件，跳过`); continue; }
    const docs = JSON.parse(fs.readFileSync(file, 'utf8'));
    const targetName = cfg.collectionPrefix + name;

    // fileID 改写：全文档字符串替换（覆盖 fileID/url/嵌套字段）
    const FROM = fileMap._prefixRule.from, TO = fileMap._prefixRule.to;
    const rewritten = docs.map(d => JSON.parse(JSON.stringify(d).split(FROM).join(TO)));

    if (DRY) {
      const nRewrite = rewritten.filter(d => JSON.stringify(d).includes(TO)).length;
      log('INFO', `[dry-run] ${name} → ${targetName}: ${docs.length} 条，含新 fileID ${nRewrite} 条`);
      continue;
    }

    let inserted = 0, skipped = 0, failed = 0;
    for (const doc of rewritten) {
      try {
        const exist = await db.collection(targetName).doc(doc._id).get().catch(() => null);
        if (exist && exist.data && (exist.data.length !== undefined ? exist.data.length : exist.data)) {
          skipped++; continue; // 幂等：已导入过
        }
        await db.collection(targetName).add({ data: doc });
        inserted++;
      } catch (e) {
        failed++; log('ERROR', `${targetName}/${doc._id} 导入失败: ${e.message}`);
      }
    }
    log('INFO', `${name} → ${targetName}: 新增 ${inserted} 跳过 ${skipped} 失败 ${failed}`);
  }
  if (!DRY) log('INFO', '完成后跑 04_verify.js 对账');
})().catch(e => { log('ERROR', e.stack || e); process.exit(1); });
