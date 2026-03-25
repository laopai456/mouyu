const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  const { action, imageIds, id } = event;

  // 支持单个删除
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

  // 支持批量删除
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
  
  return { success: false, message: 'Unknown action' };
};
