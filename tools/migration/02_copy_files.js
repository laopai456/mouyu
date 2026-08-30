// 02_copy_files.js — COS 服务端桶到桶拷贝（断点续跑：copied_keys.txt 已有的跳过）
// 用法: node 02_copy_files.js [--dry-run]
// 依赖: staging/keys.txt（01 的产物）
const fs = require('fs');
const path = require('path');
const COS = require('cos-nodejs-sdk-v5');

const cfg = require('./config.json');
const DRY = process.argv.includes('--dry-run');
const staging = path.resolve(__dirname, cfg.stagingDir);
const checkpointFile = path.join(staging, 'copied_keys.txt');

function log(level, msg) { console.log(`${level} [copy] ${msg}`); }

function copyOne(cos, key) {
  return new Promise((resolve, reject) => {
    cos.putObjectCopy({
      Bucket: cfg.target.bucket,
      Region: cfg.target.region,
      Key: key,
      CopySource: encodeURIComponent(`${cfg.source.bucket}/${key}`),
    }, (err, data) => (err || data.statusCode >= 300 ? reject(new Error(`${key}: ${err || data.statusCode}`)) : resolve(key)));
  });
}

(async () => {
  const keysFile = path.join(staging, 'keys.txt');
  if (!fs.existsSync(keysFile)) { log('ERROR', '缺少 staging/keys.txt，先跑 01_export.js'); process.exit(1); }
  const keys = fs.readFileSync(keysFile, 'utf8').split('\n').map(s => s.trim()).filter(Boolean);
  const copied = fs.existsSync(checkpointFile)
    ? new Set(fs.readFileSync(checkpointFile, 'utf8').split('\n').map(s => s.trim()).filter(Boolean))
    : new Set();
  const todo = keys.filter(k => !copied.has(k));
  log('INFO', `对象 ${keys.length} 个，已完成 ${copied.size}，本次待拷 ${todo.length}${DRY ? '（dry-run）' : ''}`);
  if (DRY) return;

  const cos = new COS({ SecretId: cfg.secretId, SecretKey: cfg.secretKey });
  const cpStream = fs.createWriteStream(checkpointFile, { flags: 'a' });
  let ok = 0, fail = 0;
  const CONCURRENCY = 5;
  let idx = 0;
  async function worker() {
    while (idx < todo.length) {
      const key = todo[idx++];
      try { await copyOne(cos, key); cpStream.write(key + '\n'); ok++; }
      catch (e) { fail++; log('ERROR', `拷贝失败 ${e.message}（重跑本脚本即重试）`); }
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  cpStream.end();
  log('INFO', `完成: 成功 ${ok} 失败 ${fail}（失败项直接重跑本脚本，已成功的自动跳过）`);
})().catch(e => { log('ERROR', e.stack || e); process.exit(1); });
