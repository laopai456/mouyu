const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const ENV_ID = process.env.ENV_ID || ''; // 控制台配置；缺失时跳过写库，防止写出坏 fileID

exports.main = async (event, context) => {
  const db = cloud.database();
  
  console.log('收到 COS 事件:', JSON.stringify(event));
  
  if (!event.Records || !Array.isArray(event.Records)) {
    console.log('不是 COS 事件格式，跳过');
    return { success: false, message: 'Not a COS event' };
  }
  
  const results = [];
  
  for (const record of event.Records) {
    try {
      const cos = record.cos;
      if (!cos || cos.eventName !== 'cos:ObjectCreated:*') {
        console.log('非文件创建事件，跳过');
        continue;
      }
      
      const bucket = cos.cosBucket?.name || '';
      const key = cos.cosObject?.key || '';
      
      if (!key.startsWith('memes/')) {
        console.log('非 memes 目录文件，跳过:', key);
        continue;
      }
      
      if (!ENV_ID) {
        console.error('缺少 ENV_ID 环境变量，跳过该事件（云开发控制台→云函数→环境变量）');
        results.push({ record, status: 'error', message: 'missing ENV_ID env var' });
        continue;
      }
      
      const fileID = `cloud://${ENV_ID}.${bucket}/${key}`;
      
      const now = new Date();
      const month = now.getMonth() + 1;
      const yearMonth = `${now.getFullYear()}-${String(month).padStart(2, '0')}`;
      const today = now.toISOString().split('T')[0];
      
      const existRes = await db.collection('images')
        .where({ fileID })
        .count();
      
      if (existRes.total > 0) {
        console.log('图片记录已存在，跳过:', fileID);
        results.push({ fileID, status: 'skipped', reason: 'already exists' });
        continue;
      }
      
      await db.collection('images').add({
        data: {
          fileID,
          url: fileID,
          md5: '',
          uploaderOpenid: 'auto-uploader',
          status: 0,
          dislikeCount: 0,
          likeCount: 0,
          laughCount: 0,
          date: today,
          yearMonth,
          month,
          createTime: Date.now(),
        }
      });
      
      console.log('数据库写入成功:', fileID);
      results.push({ fileID, status: 'success' });
      
    } catch (err) {
      console.error('处理记录失败:', err);
      results.push({ record, status: 'error', message: err.message });
    }
  }
  
  return {
    success: true,
    processed: results.length,
    results
  };
};
