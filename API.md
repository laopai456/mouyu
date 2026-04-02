# API 接口文档

> 最后更新：2026-03-31

---

## 云函数列表

| 云函数 | 功能 |
|--------|------|
| getRandomImage | 获取随机图片 |
| addImage | 添加图片 |
| deleteImages | 批量删除图片 |
| likeImage | 送花 |
| dislikeImage | 踩 |
| laughImage | 哈哈 |
| admin | 管理员操作 |
| getTempUrls | 获取临时URL |
| autoCleanup | 自动清理 |
| autoUpload | 自动上传 |

---

## 1. getRandomImage

获取随机图片

**请求参数**：
```javascript
{
  count: number,        // 获取数量，默认1，最大5
  seenIds: string[],    // 已看过的图片ID数组
  isFirstVisit: boolean  // 是否首次访问
}
```

**返回参数**：
```javascript
{
  success: boolean,
  images: [{
    _id: string,
    fileID: string,
    url: string,
    tempUrl: string,      // 临时URL
    md5: string,
    status: number,
    dislikeCount: number,
    likeCount: number,
    laughCount: number,
    createTime: number
  }],
  noMore: boolean,        // 是否没有更多图片
  message: string,        // 提示信息
  windowExpired: boolean   // 3天窗口是否过期
}
```

**示例**：
```javascript
wx.cloud.callFunction({
  name: 'getRandomImage',
  data: { count: 3, seenIds: ['id1', 'id2'], isFirstVisit: false }
})
```

---

## 2. addImage

添加图片

**请求参数**：
```javascript
{
  fileID: string,    // 云存储fileID
  md5: string        // 图片MD5
}
```

**返回参数**：
```javascript
{
  success: boolean,
  msg: string        // 成功或失败原因
}
```

**示例**：
```javascript
wx.cloud.callFunction({
  name: 'addImage',
  data: { fileID: 'cloud://xxx', md5: 'abc123' }
})
```

---

## 3. deleteImages

批量删除图片

**请求参数**：
```javascript
{
  action: 'delete' | 'batchDelete' | 'addToBlacklist' | 'migrateBlacklist',
  id?: string,           // 单个删除时使用
  imageIds?: string[]    // 批量删除时使用
}
```

**返回参数**：
```javascript
{
  success: boolean,
  message: string,
  successCount?: number,
  failCount?: number
}
```

**示例**：
```javascript
wx.cloud.callFunction({
  name: 'deleteImages',
  data: { action: 'batchDelete', imageIds: ['id1', 'id2'] }
})
```

---

## 4. likeImage

送花

**请求参数**：
```javascript
{
  imageId: string   // 图片ID
}
```

**返回参数**：
```javascript
{
  success: boolean,
  message: string,
  likeCount: number  // 当前送花数
}
```

---

## 5. dislikeImage

踩

**请求参数**：
```javascript
{
  imageId: string   // 图片ID
}
```

**返回参数**：
```javascript
{
  success: boolean,
  message: string,
  dislikeCount: number  // 当前踩数
}
```

---

## 6. laughImage

哈哈

**请求参数**：
```javascript
{
  imageId: string   // 图片ID
}
```

**返回参数**：
```javascript
{
  success: boolean,
  message: string,
  laughCount: number  // 当前哈哈数
}
```

---

## 7. admin

管理员操作

**请求参数**：
```javascript
{
  action: 'checkAdmin' | 'review' | 'stats',
  imageId?: string,    // 审核时使用
  status?: number,      // 审核状态 1通过 2拒绝
  adminOpenid?: string // 可选，传递管理员openid
}
```

**返回参数**：
```javascript
{
  success: boolean,
  message?: string,
  isAdmin?: boolean,
  stats?: {
    pending: number,
    passed: number,
    rejected: number
  }
}
```

**示例**：
```javascript
// 审核图片
wx.cloud.callFunction({
  name: 'admin',
  data: { action: 'review', imageId: 'xxx', status: 1 }
})

// 获取统计
wx.cloud.callFunction({
  name: 'admin',
  data: { action: 'stats' }
})
```

---

## 8. getTempUrls

获取临时URL

**请求参数**：
```javascript
{
  fileIDs: string[]   // fileID数组
}
```

**返回参数**：
```javascript
{
  success: boolean,
  urlMap: {
    [fileID: string]: string  // fileID对应的临时URL
  }
}
```

---

## 9. autoCleanup

自动清理（定时触发）

**请求参数**：无

**返回参数**：
```javascript
{
  success: boolean,
  message: string,
  totalCount: number,
  deletedCount: number,
  failedCount: number
}
```

**触发条件**：每天凌晨2点自动执行

---

## 10. autoUpload

自动上传（外部工具调用）

**请求参数**：
```javascript
{
  action: 'getTempFileURL' | 'addImage',
  fileIDs?: string[],
  fileID?: string,
  md5?: string
}
```

**返回参数**：
```javascript
{
  success: boolean,
  message?: string,
  fileList?: object[]
}
```

---

## 数据库集合

### images

| 字段 | 类型 | 说明 |
|------|------|------|
| _id | ObjectId | 主键 |
| fileID | string | 云存储fileID |
| url | string | 图片CDN地址 |
| md5 | string | 图片MD5 |
| uploaderOpenid | string | 上传者openid |
| status | number | 0待审核/1已通过/2已拒绝 |
| dislikeCount | number | 被踩次数 |
| likeCount | number | 被送花次数 |
| laughCount | number | 被哈哈次数 |
| date | string | 上传日期 YYYY-MM-DD |
| yearMonth | string | 年月 YYYY-MM |
| createTime | number | 创建时间戳 |
| reviewTime | number | 审核时间戳 |

### dislike_logs

| 字段 | 类型 | 说明 |
|------|------|------|
| _id | ObjectId | 主键 |
| imageId | string | 图片ID |
| openid | string | 用户openid |
| date | string | 日期 |

### like_logs

| 字段 | 类型 | 说明 |
|------|------|------|
| _id | ObjectId | 主键 |
| imageId | string | 图片ID |
| openid | string | 用户openid |
| date | string | 日期 |

---

## 错误码

| 错误码 | 说明 |
|--------|------|
| OPERATION_FAIL | 操作失败 |
| FUNCTIONS_TIME_LIMIT_EXCEEDED | 云函数超时 |
| DATABASE_COLLECTION_NOT_EXIST | 数据库集合不存在 |
