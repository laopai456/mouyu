const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

exports.main = async (event, context) => {
  const { action } = event;

  if (action === 'getTempFileURL') {
    const { fileIDs } = event;
    try {
      const result = await cloud.getTempFileURL({ fileList: fileIDs });
      return {
        success: true,
        fileList: result.fileList
      };
    } catch (err) {
      return { success: false, message: err.message };
    }
  }

  if (action === 'checkMd5') {
    // 上传前查重：uploader 在传 COS 前调用，避免重复图先落 COS 再被触发器写成重复待审记录
    const { md5 } = event;
    if (!md5) return { success: true, exists: false, blacklisted: false };

    const db = cloud.database();
    try {
      // status: 0待审 1过审 2拒绝 3转发群组——与 addImage 查重口径一致
      const [existRes, blacklistRes] = await Promise.all([
        db.collection('images').where({ md5, status: db.command.in([0, 1, 2, 3]) }).count(),
        db.collection('md5_blacklist').where({ md5 }).count()
      ]);
      return {
        success: true,
        exists: existRes.total > 0,
        blacklisted: blacklistRes.total > 0
      };
    } catch (err) {
      return { success: false, message: err.message };
    }
  }

  if (action === 'addImage') {
    const { fileID, md5 } = event;
    const db = cloud.database();

    try {
      const now = new Date();
      const month = now.getMonth() + 1;
      const yearMonth = `${now.getFullYear()}-${String(month).padStart(2, '0')}`;
      const today = now.toISOString().split('T')[0];

      if (md5) {
        // status: 0待审 1过审 2拒绝 3转发群组——3 也算重复，防止勾转后同图再入库
        const [existRes, blacklistRes] = await Promise.all([
          db.collection('images').where({ md5, status: db.command.in([0, 1, 2, 3]) }).count(),
          db.collection('md5_blacklist').where({ md5 }).count()
        ]);

        if (existRes.total > 0) {
          return { success: false, msg: '该图片已存在，请勿重复上传' };
        }
        if (blacklistRes.total > 0) {
          return { success: false, msg: '该图片已被永久拒绝，无法上传' };
        }
      }

      await db.collection('images').add({
        data: {
          fileID,
          url: fileID,
          md5: md5 || '',
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

      return { success: true, msg: '上传成功，等待审核' };
    } catch (err) {
      return { success: false, msg: err.message };
    }
  }

  return { success: false, message: 'Unknown action' };
};