// 全库 md5 判重审计（images 集合）：按 md5 / fileID 两种口径找重复，默认只读报告。
//
// 背景：2026-09-02 曾把 doc `_id` 前 8 位误当 md5 前缀判出"同图重复入库"——实际那是
// TCB 自动 id 的批次前缀（同批入库共享），内容 md5 全唯一，虚惊。此脚本按真 md5 字段审计。
// 注意：`_id[:8]` 不是 md5；判重只能信 md5 / fileID 字段。
//
// 用法：
//   npm i @cloudbase/js-sdk   （本目录或任意有 node_modules 的地方）
//   node db_dedup_check.js            → 只读审计，打印重复组
//   node db_dedup_check.js --delete   → 每组同图保留一条，其余走 deleteImages 云函数硬删
//                                       （删前把整条文档写进 dedup_backup.json，可手工恢复）
// 保留优先级：bot 已发过（qqbot data/mouyu_state.json 的 forwarded）> status3 > status1 > status0，
// 同级取更早入库；status=2（拒绝）按设计允许重传，不参与判重与删除。
const cloudbase = require('@cloudbase/js-sdk');
const fs = require('fs');

const ENV_ID = 'MOYU_ENV_ID_PLACEHOLDER';
const ADMIN_OPENID = 'ADMIN_OPENID_1_PLACEHOLDER'; // deleteImages 云函数白名单开发者
const STATE_FILE = 'C:/Users/w/Documents/GitHub/qqbot/data/mouyu_state.json';
const DO_DELETE = process.argv.includes('--delete');

async function main() {
  const app = cloudbase.init({ env: ENV_ID, region: 'ap-shanghai' });
  await app.auth().signInAnonymously();
  const coll = app.database().collection('images');

  // orderBy('_id') 保证 skip 翻页稳定；client SDK 单页上限 100
  const docs = [];
  for (let skip = 0; ; skip += 100) {
    const res = await coll
      .field({ md5: true, status: true, fileID: true, createTime: true })
      .orderBy('_id', 'asc').skip(skip).limit(100).get();
    docs.push(...res.data);
    if (res.data.length < 100) break;
  }
  console.log(`images 共 ${docs.length} 条，空 md5 ${docs.filter(d => !d.md5).length} 条`);

  const sentIds = new Set();
  try {
    const st = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    for (const k of st.forwarded || []) sentIds.add(k.includes(':') ? k.slice(k.indexOf(':') + 1) : k);
  } catch { /* qqbot 状态文件不在也能跑，只是丢失"已发优先" */ }

  const groups = new Map();
  for (const d of docs) {
    if (!d.md5 || d.status === 2) continue;
    if (!groups.has(d.md5)) groups.set(d.md5, []);
    groups.get(d.md5).push(d);
  }
  const dups = [...groups.values()].filter(a => a.length > 1);
  const fileIDDups = Object.values(
    docs.filter(d => d.fileID).reduce((m, d) => ((m[d.fileID] ||= []).push(d), m), {})
  ).filter(a => a.length > 1);

  console.log(`md5 重复组（非拒绝口径）：${dups.length}；fileID 重复组：${fileIDDups.length}`);
  if (!dups.length && !fileIDDups.length) { console.log('库内无重复，无需清理。'); process.exit(0); }

  const rank = d => [
    sentIds.has(d._id) ? 0 : 1,
    d.status === 3 ? 0 : d.status === 1 ? 1 : 2,
    d.createTime || 0,
  ];
  const lt = (a, b) => JSON.stringify(a) < JSON.stringify(b) ? -1 : 1;
  const plan = dups
    .map(g => { const s = g.slice().sort((a, b) => lt(rank(a), rank(b))); return { keep: s[0], drop: s.slice(1) }; })
    .filter(p => p.drop.length);

  for (const p of plan) {
    console.log(`md5 ${p.keep.md5.slice(0, 12)}… 保留 ${p.keep._id}[s${p.keep.status}${sentIds.has(p.keep._id) ? '/已发' : ''}]` +
      `，删除 ${p.drop.map(d => `${d._id}[s${d.status}]`).join(' ')}`);
  }
  fs.writeFileSync(__dirname + '/dedup_backup.json', JSON.stringify({ deleted: plan.flatMap(p => p.drop) }, null, 2));

  if (!DO_DELETE) { console.log('干跑模式未删除；加 --delete 执行（备份已写 dedup_backup.json）。'); process.exit(0); }
  const ids = plan.flatMap(p => p.drop.map(d => d._id));
  let ok = 0, fail = 0;
  for (let i = 0; i < ids.length; i += 20) {
    const res = await app.callFunction({
      name: 'deleteImages',
      data: { action: 'batchDelete', imageIds: ids.slice(i, i + 20), adminOpenid: ADMIN_OPENID },
    });
    const r = res.result || {};
    ok += r.successCount || 0; fail += r.failCount || 0;
    if (!r.success) { console.error('批次失败:', JSON.stringify(r)); break; }
  }
  console.log(`删除完成：成功 ${ok}，失败 ${fail}（备份 dedup_backup.json）`);
  process.exit(0);
}
main().catch(e => { console.error('FATAL', e && (e.message || e)); process.exit(1); });
