// 04_verify.js — 迁移对账：两环境集合计数对比 + 新 fileID 抽样临时链接 + 旧前缀残留扫描
// 用法: node 04_verify.js
const fs = require('fs');
const path = require('path');
const CloudBase = require('@cloudbase/node-sdk');

const cfg = require('./config.json');
const staging = path.resolve(__dirname, cfg.stagingDir);

function log(level, msg) { console.log(`${level} [verify] ${msg}`); }

(async () => {
  const mk = env => CloudBase.init({ env, secretId: cfg.secretId, secretKey: cfg.secretKey });
  const src = mk(cfg.source.envId), dst = mk(cfg.target.envId);
  const SRC_PREFIX = `cloud://${cfg.source.envId}.${cfg.source.bucket}/`;

  console.log('==== 集合计数对账（源 / 目标）====');
  for (const name of cfg.collections) {
    const targetName = cfg.collectionPrefix + name;
    const [a, b] = await Promise.all([
      src.database().collection(name).count(),
      dst.database().collection(targetName).count(),
    ]);
    const mark = a.total === b.total ? 'OK ' : 'MISMATCH';
    console.log(`${mark} ${name}: ${a.total} / ${targetName}: ${b.total}`);
  }

  console.log('==== images 状态分布对比 ====');
  for (const st of [0, 1, 2, 3]) {
    const [a, b] = await Promise.all([
      src.database().collection('images').where({ status: st }).count(),
      dst.database().collection(cfg.collectionPrefix + 'images').where({ status: st }).count(),
    ]);
    const mark = a.total === b.total ? 'OK ' : 'MISMATCH';
    console.log(`${mark} status=${st}: 源 ${a.total} / 目标 ${b.total}`);
  }

  console.log('==== 抽样 10 个新 fileID 临时链接 ====');
  const sample = await dst.database().collection(cfg.collectionPrefix + 'images').limit(10).get();
  const fileIDs = sample.data.map(d => d.fileID).filter(Boolean);
  const r = await dst.getTempFileURL({ fileList: fileIDs });
  let okUrl = 0;
  for (const f of r.fileList || []) {
    const good = f.code === 'SUCCESS' || (f.tempFileURL && f.status === 0);
    if (good) okUrl++;
    else log('WARN', `临时链接失败: ${f.fileID} code=${f.code} ${f.codeDesc || ''}`);
  }
  console.log(`${okUrl}/${fileIDs.length} 可访问${okUrl === fileIDs.length ? ' OK' : ' 有失败项，检查桶拷贝(02)'}`);

  console.log('==== 旧前缀残留扫描（目标 images 全量）====');
  let skip = 0, residual = 0, total = 0;
  while (true) {
    const res = await dst.database().collection(cfg.collectionPrefix + 'images').skip(skip).limit(1000).get();
    total += res.data.length;
    for (const d of res.data) if (JSON.stringify(d).includes(SRC_PREFIX)) { residual++; log('ERROR', `残留旧 fileID: ${d._id}`); }
    if (res.data.length < 1000) break;
    skip += 1000;
  }
  console.log(`扫描 ${total} 条，残留 ${residual} 条${residual === 0 ? ' OK' : ' 需重跑 03 或手工修'}`);
})().catch(e => { log('ERROR', e.stack || e); process.exit(1); });
