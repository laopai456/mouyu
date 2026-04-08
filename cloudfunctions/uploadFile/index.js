const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

exports.main = async (event, context) => {
  const { cloudPath, fileContent } = event;

  if (!cloudPath || !fileContent) {
    return { success: false, message: '参数缺失' };
  }

  try {
    const buffer = Buffer.from(fileContent, 'base64');

    const result = await cloud.uploadFile({
      cloudPath,
      fileContent: buffer
    });

    return {
      success: true,
      fileID: result.fileID
    };
  } catch (err) {
    console.error('上传失败', err);
    return {
      success: false,
      message: err.message
    };
  }
};
