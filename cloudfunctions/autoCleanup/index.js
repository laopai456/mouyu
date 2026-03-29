const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

const IMAGE_LIMIT = 2000;
const DELETE_COUNT = 200;

exports.main = async (event, context) => {
  try {
    const countRes = await db.collection('images').count();
    const totalCount = countRes.total;

    console.log(`当前图片总数: ${totalCount}`);

    if (totalCount < IMAGE_LIMIT) {
      return {
        success: true,
        message: `图片总数 ${totalCount} 未达到 ${IMAGE_LIMIT} 张，无需清理`,
        totalCount,
        deletedCount: 0
      };
    }

    console.log(`图片总数已达 ${IMAGE_LIMIT} 张，开始清理...`);

    let deletedCount = 0;
    let failedCount = 0;
    const imagesToDelete = [];

    const rejectedImages = await db.collection('images')
      .where({ status: 2 })
      .orderBy('createTime', 'desc')
      .limit(DELETE_COUNT)
      .get();

    if (rejectedImages.data.length > 0) {
      imagesToDelete.push(...rejectedImages.data);
      console.log(`找到已拒绝图片 ${rejectedImages.data.length} 张`);
    }

    const remainingCount = DELETE_COUNT - imagesToDelete.length;
    if (remainingCount > 0) {
      const pendingImages = await db.collection('images')
        .where({ status: 0 })
        .orderBy('createTime', 'desc')
        .limit(remainingCount)
        .get();

      if (pendingImages.data.length > 0) {
        imagesToDelete.push(...pendingImages.data);
        console.log(`从待审核补充 ${pendingImages.data.length} 张`);
      }
    }

    console.log(`本次共清理 ${imagesToDelete.length} 张图片`);

    for (const image of imagesToDelete) {
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
      totalCount,
      deletedCount,
      failedCount,
      deletedFromRejected: rejectedImages.data.length,
      deletedFromPending: imagesToDelete.length - rejectedImages.data.length
    };
  } catch (err) {
    console.error('自动清理失败:', err);
    return {
      success: false,
      message: err.message
    };
  }
};