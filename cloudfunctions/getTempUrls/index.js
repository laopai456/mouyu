const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

exports.main = async (event, context) => {
  const { fileIDs } = event;

  if (!fileIDs || fileIDs.length === 0) {
    return { success: false, message: '文件 ID 列表为空' };
  }

  try {
    const result = await cloud.getTempFileURL({
      fileList: fileIDs
    });

    const urlMap = {};
    const failedFiles = [];
    if (result.fileList) {
      result.fileList.forEach(item => {
        if (item.tempFileURL) {
          urlMap[item.fileID] = item.tempFileURL;
        } else {
          failedFiles.push(item.fileID);
          console.error('获取文件临时URL失败:', item.fileID, item.errMsg);
        }
      });
    }

    return {
      success: true,
      urlMap,
      failedFiles: failedFiles.length > 0 ? failedFiles : undefined
    };
  } catch (err) {
    console.error('获取临时 URL 失败', err);
    return {
      success: false,
      message: err.message
    };
  }
};
