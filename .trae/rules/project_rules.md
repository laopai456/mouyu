# 项目开发规范

## 图片审核状态规则

### 状态定义
```javascript
const IMAGE_STATUS = {
  PENDING: 0,   // 待审核
  APPROVED: 1,  // 已通过
  REJECTED: 2   // 已拒绝
};
```

### 核心原则

**所有公开的图片查询接口，必须默认过滤审核状态，只返回 `status: 1`（已通过）的图片。**

### 查询分类

#### 1. 公开查询（普通用户可访问）
- **必须** 使用 `createPublicImageQuery()` 封装函数
- **必须** 默认只查询 `status: 1` 的图片
- **例外**：开发版/体验版可以查询 `status: 0` 用于测试

#### 2. 管理查询（仅管理员可访问）
- 需要先校验管理员权限
- 可以查询所有状态的图片

#### 3. 上传查重（检查图片是否已存在）
- 需要查询 `status: in([0, 1, 2])` 所有状态
- 这是合理的业务需求，不是漏洞

### 代码评审 Checklist

新增或修改图片查询接口时，必须检查：

- [ ] 是否是公开查询接口？
- [ ] 如果是公开查询，是否使用了统一的 `createPublicImageQuery()` 封装？
- [ ] 是否正确处理了 `envVersion` 可能为 `undefined` 的情况？
- [ ] 是否有管理员权限校验（如果是管理接口）？

### 上线回归测试

每次上线前，必须执行以下测试用例：

1. **正式版用户**：只能看到已审核通过的图片
2. **开发版/体验版**：可以看到待审核图片（用于测试）
3. **管理员后台**：可以正确显示待审核/已通过/已拒绝的图片

### 历史问题

**2026-04-09 事故**：
- 问题：`getRandomImage` 云函数中 `wxContext.envVersion` 可能为 `undefined`，导致 `undefined !== 'release'` 为 `true`，正式版用户看到了待审核图片
- 修复：使用 `(wxContext.envVersion || 'release') !== 'release'` 防御性编程
- 改进：创建 `createPublicImageQuery()` 统一封装，避免类似问题

## 云函数开发规范

### 环境版本判断

```javascript
// 正确写法
const envVersion = wxContext.envVersion || 'release';
const isDebugMode = envVersion !== 'release';

// 错误写法（envVersion 可能为 undefined）
const isDebugMode = wxContext.envVersion !== 'release';
```

### 权限校验

所有管理类接口必须在入口处校验权限：

```javascript
const DEVELOPER_OPENIDS = ['xxx'];

function isDeveloper(openid) {
  return DEVELOPER_OPENIDS.includes(openid);
}

exports.main = async (event, context) => {
  const { OPENID } = cloud.getWXContext();
  
  if (!isDeveloper(OPENID)) {
    return { success: false, msg: '无权限操作', noPermission: true };
  }
  
  // 业务逻辑...
};
```
