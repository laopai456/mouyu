// 复制为同目录 config.local.js 并填入真实值（config.local.js 已被 .gitignore 排除，不会提交）
window.CLOUD_CONFIG = {
  envId: '你的云开发环境ID',
  adminOpenids: ['你的微信openid'],  // deleteImages/admin 云函数白名单里的 openid
};
