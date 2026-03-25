const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  try {
    const now = new Date();
    const threeDaysAgo = new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000);
    const deleteBeforeDate = threeDaysAgo.toISOString().split('T')[0];
    
    console.log('开始清理，删除日期:', deleteBeforeDate, '之前的图片');
    
    const imagesToDelete = await db.collection('images')
      .where({
        createTime: db.command.lt(threeDaysAgo.getTime())
      })
      .get();
    
    if (imagesToDelete.data.length === 0) {
      return {
        success: true,
        message: '没有需要清理的图片',
        deletedCount: 0
      };
    }
    
    let deletedCount = 0;
    let failedCount = 0;
    
    for (const image of imagesToDelete.data) {
      try {
        if (image.fileID) {
          try {
            await cloud.deleteFile({
              fileList: [image.fileID]
            });
          } catch (deleteErr) {
            console.error('删除云存储文件失败:', image.fileID, deleteErr);
          }
        }
        
        await db.collection('images').doc(image._id).remove();
        deletedCount++;
      } catch (err) {
        console.error('删除图片记录失败:', image._id, err);
        failedCount++;
      }
    }
    
    return {
      success: true,
      message: `清理完成`,
      deletedCount,
      failedCount,
      deleteBeforeDate
    };
  } catch (err) {
    console.error('自动清理失败:', err);
    return {
      success: false,
      message: err.message
    };
  }
};
