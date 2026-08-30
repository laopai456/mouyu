// 01_export.js — 导出源环境全部集合并生成 fileID 映射（只读，可重复跑）
// 用法: node 01_export.js [--dry-run]
// 产物: staging/collections/<name>.json  staging/file_map.json  staging/keys.txt
const fs = require('fs');
const path = require('path');
const CloudBase = require('@cloudbase/node-sdk');

const cfg = require('./config.json');
const DRY = process.argv.includes('--dry-run');
const staging = path.resolve(__dirname, cfg.stagingDir);
const colDir = path.join(staging, 'collections');

const SRC_PREFIX = `cloud://${cfg.source.envId}.${cfg.source.bucket}/`;
const DST_PREFIX = `cloud://${cfg.target.envId}.${cfg.target.bucket}/`;
const FILE_ID_RE = /cloud:\/\/[0-9a-zA-Z-]+\.[0-9a-zA-Z-]+\/[^\s"'`,\\]+/g;

function log(level, msg) { console.log(`${level} [export] ${msg}`); }

(async () => {
  const app = CloudBase.init({
    env: cfg.source.envId,
    secretId: cfg.secretId,
    secretKey: cfg.secretKey,
  });
  const db = app.database();

  fs.mkdirSync(colDir, { recursive: true });
  const summary = {};
  const keySet = new Set();
  const fileMap = { _prefixRule: { from: SRC_PREFIX, to: DST_PREFIX }, files: {} };

  for (const name of cfg.collections) {
    let all = [], skip = 0;
    while (true) {
      const r = await db.collection(name).skip(skip).limit(1000).get();
      all.push(...r.data);
      if (r.data.length < 1000) break;
      skip += 1000;
    }
    summary[name] = all.length;

    // 扫描文档中所有 cloud:// fileID（覆盖 fileID/url 及任意嵌套字段）
    for (const doc of all) {
      const m = JSON.stringify(doc).match(FILE_ID_RE) || [];
      for (const fid of m) {
        if (fid.startsWith(SRC_PREFIX)) {
          const key = fid.slice(SRC_PREFIX.length);
          keySet.add(key);
          fileMap.files[fid] = DST_PREFIX + key;
        } else {
          log('WARN', `${name}/${doc._id} 存在非源前缀 fileID，跳过映射: ${fid}`);
        }
      }
    }

    if (!DRY) {
      fs.writeFileSync(path.join(colDir, `${name}.json`), JSON.stringify(all, null, 1), 'utf8');
    }
    log('INFO', `${name}: ${all.length} 条${DRY ? '（dry-run 不落盘）' : ' 已导出'}`);
  }

  if (!DRY) {
    fs.writeFileSync(path.join(staging, 'file_map.json'), JSON.stringify(fileMap, null, 1), 'utf8');
    fs.writeFileSync(path.join(staging, 'keys.txt'), [...keySet].sort().join('\n'), 'utf8');
  }
  log('INFO', `fileID 映射 ${Object.keys(fileMap.files).length} 条，待拷贝对象 ${keySet.size} 个`);
  log('INFO', '抄录到方案 §7 对账表: ' + JSON.stringify(summary));
})().catch(e => { log('ERROR', e.stack || e); process.exit(1); });
