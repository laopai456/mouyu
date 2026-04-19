const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  const { FromUserName, MsgType, Content, MediaId } = event.xml;

  if (MsgType === 'image') {
    try {
      const fileResp = await cloud.downloadFile({ fileID: MediaId });
      const uploadResp = await cloud.uploadFile({
        cloudPath: `memes/${Date.now()}.jpg`,
        fileContent: fileResp.fileContent,
      });

      await db.collection('images').add({
        data: {
          fileID: uploadResp.fileID,
          url: uploadResp.fileID,
          uploaderOpenid: FromUserName,
          status: 0,
          dislikeCount: 0,
          likeCount: 0,
          laughCount: 0,
          createTime: Date.now(),
        }
      });

      return {
        msg: '图片已收到，等待审核后展示~',
        fromusername: FromUserName,
        msgtype: 'text',
      };
    } catch (err) {
      return {
        msg: '上传失败，请重试',
        fromusername: FromUserName,
        msgtype: 'text',
      };
    }
  }

  return { msg: '', fromusername: FromUserName, msgtype: 'text' };
};
