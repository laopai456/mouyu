# 图片按日期分类管理功能实现计划

## 需求分析

### 当前问题
- 已通过审核的图片没有日期分类
- 所有图片混在一起，不便于管理
- 随着图片数量增加，查找和管理会越来越困难

### 目标功能
1. **按月份自动创建文件夹**：上传时自动创建对应月份的文件夹
2. **自动分类存储**：图片自动存入对应日期的文件夹
3. **按日期显示**：在 Web 管理工具中按日期分组显示图片
4. **便于管理**：可以按日、月、年快速查找和管理图片

## 技术方案

### 方案概述
在数据库中添加日期字段，云存储按月份组织文件夹，前端按日期分组显示。

### 数据结构设计

#### 数据库字段调整
在 `images` 集合中添加/优化以下字段：
```javascript
{
  _id: "xxx",
  fileID: "cloud://xxx",
  url: "cloud://xxx",
  md5: "xxx",
  uploaderOpenid: "xxx",
  status: 1, // 0-待审核, 1-已通过, 2-已拒绝
  
  // 新增/优化字段
  date: "2026-03-25", // 上传日期 YYYY-MM-DD
  yearMonth: "2026-03", // 年月 YYYY-MM，用于快速查询
  year: 2026, // 年份
  month: 3, // 月份
  
  // 已有字段
  likeCount: 0,
  dislikeCount: 0,
  createTime: 1234567890 // 时间戳
}
```

#### 云存储文件夹结构
```
memes/
├── 2026-03/
│   ├── 1774352837297_xxx.jpg
│   ├── 1774352848569_xxx.jpg
│   └── ...
├── 2026-04/
│   ├── 1774452837297_xxx.jpg
│   └── ...
└── ...
```

### 实现步骤

#### 任务 1：修改数据库结构
**目标**：为现有图片添加日期字段

**步骤**：
1. 创建迁移脚本，为现有图片添加日期字段
2. 根据 `createTime` 字段计算 `date`、`yearMonth`、`year`、`month` 字段
3. 批量更新数据库

**代码示例**：
```javascript
// 云函数：migrateImages
const cloud = require('wx-server-sdk');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  const images = await db.collection('images').get();
  
  const updatePromises = images.data.map(async (img) => {
    const date = new Date(img.createTime);
    const year = date.getFullYear();
    const month = date.getMonth() + 1;
    const yearMonth = `${year}-${String(month).padStart(2, '0')}`;
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    
    return db.collection('images').doc(img._id).update({
      data: {
        date: dateStr,
        yearMonth,
        year,
        month
      }
    });
  });
  
  await Promise.all(updatePromises);
  
  return { success: true, count: images.data.length };
};
```

**验收标准**：
- ✅ 所有现有图片都有日期字段
- ✅ 日期字段计算正确

#### 任务 2：修改上传逻辑
**目标**：上传时自动按月份创建文件夹并存储

**修改文件**：
- `cloudfunctions/addImage/index.js`（小程序端上传）
- `admin.html`（Web 端上传）

**代码示例**：
```javascript
// 生成云存储路径
const now = new Date();
const year = now.getFullYear();
const month = String(now.getMonth() + 1).padStart(2, '0');
const yearMonth = `${year}-${month}`;
const cloudPath = `memes/${yearMonth}/${Date.now()}_${Math.random().toString(36).substr(2, 9)}.${ext}`;

// 数据库记录
await db.collection('images').add({
  data: {
    fileID: uploadRes.fileID,
    url: uploadRes.fileID,
    md5,
    uploaderOpenid,
    status: 0,
    date: `${yearMonth}-${String(now.getDate()).padStart(2, '0')}`,
    yearMonth,
    year,
    month,
    createTime: Date.now()
  }
});
```

**验收标准**：
- ✅ 上传图片自动存入对应月份文件夹
- ✅ 数据库记录包含完整的日期字段

#### 任务 3：修改 Web 管理工具显示
**目标**：按日期分组显示图片

**修改文件**：`admin.html`

**实现方案**：
1. 添加日期筛选器（年、月选择）
2. 按日期分组显示图片
3. 添加日期导航（上一月、下一月）

**代码示例**：
```javascript
// 按月份加载图片
async function loadImagesByMonth(yearMonth) {
  const res = await db.collection('images')
    .where({
      status: 1,
      yearMonth: yearMonth
    })
    .orderBy('createTime', 'desc')
    .get();
  
  return res.data;
}

// 获取所有月份列表
async function getMonthList() {
  const res = await db.collection('images')
    .where({ status: 1 })
    .field({ yearMonth: true })
    .get();
  
  const months = [...new Set(res.data.map(item => item.yearMonth))];
  return months.sort().reverse();
}
```

**UI 设计**：
```
┌─────────────────────────────────────┐
│  ← 2026年3月 →                      │
│  待审核: 5 | 已通过: 22 | 已拒绝: 3 │
├─────────────────────────────────────┤
│  [图片] [图片] [图片] [图片]        │
│  [图片] [图片] [图片] [图片]        │
│  [图片] [图片] [图片] [图片]        │
└─────────────────────────────────────┘
```

**验收标准**：
- ✅ 可以按月份筛选图片
- ✅ 图片按日期分组显示
- ✅ 可以快速切换月份

#### 任务 4：优化云函数 getTempUrls
**目标**：支持按月份获取图片

**修改文件**：`cloudfunctions/getTempUrls/index.js`

**代码示例**：
```javascript
exports.main = async (event, context) => {
  const { fileIDs, yearMonth } = event;
  
  // 如果指定了月份，只获取该月份的图片
  let query = db.collection('images').where({ status: 1 });
  if (yearMonth) {
    query = query.where({ yearMonth });
  }
  
  // ... 其余逻辑
};
```

**验收标准**：
- ✅ 支持按月份获取图片
- ✅ 性能优化，减少数据传输

## 数据迁移计划

### 迁移步骤
1. **备份数据库**：在迁移前备份 images 集合
2. **创建迁移云函数**：编写数据迁移脚本
3. **执行迁移**：运行迁移云函数
4. **验证数据**：检查迁移结果
5. **更新代码**：部署新的云函数和前端代码

### 迁移云函数代码
```javascript
// cloudfunctions/migrateImages/index.js
const cloud = require('wx-server-sdk');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();

exports.main = async (event, context) => {
  const { mode = 'add_date_fields' } = event;
  
  if (mode === 'add_date_fields') {
    // 为现有图片添加日期字段
    const images = await db.collection('images').get();
    
    const updatePromises = images.data.map(async (img) => {
      const date = new Date(img.createTime);
      const year = date.getFullYear();
      const month = date.getMonth() + 1;
      const yearMonth = `${year}-${String(month).padStart(2, '0')}`;
      const dateStr = `${yearMonth}-${String(date.getDate()).padStart(2, '0')}`;
      
      return db.collection('images').doc(img._id).update({
        data: {
          date: dateStr,
          yearMonth,
          year,
          month
        }
      });
    });
    
    await Promise.all(updatePromises);
    
    return { success: true, count: images.data.length };
  }
  
  return { success: false, message: 'Unknown mode' };
};
```

## 风险评估

### 潜在风险
1. **数据迁移风险**：大量数据迁移可能导致超时
2. **兼容性问题**：旧代码可能不兼容新的数据结构
3. **性能影响**：按月份查询可能影响性能

### 缓解措施
1. **分批迁移**：将迁移任务分批执行，避免超时
2. **向后兼容**：确保新代码兼容旧数据
3. **索引优化**：为 `yearMonth` 字段创建索引，提升查询性能

## 实施时间表

- 任务 1：修改数据库结构 - 30 分钟
- 任务 2：修改上传逻辑 - 30 分钟
- 任务 3：修改 Web 管理工具显示 - 60 分钟
- 任务 4：优化云函数 - 20 分钟
- 数据迁移 - 30 分钟
- 测试验证 - 30 分钟

**总计**：约 3.5 小时

## 成功标准

- ✅ 图片按月份自动分类存储
- ✅ Web 管理工具支持按月份查看
- ✅ 数据迁移成功，无数据丢失
- ✅ 性能良好，查询速度快
- ✅ 用户体验良好，操作方便

## 后续优化

### 可选功能
1. **按日查看**：支持查看某一天的所有图片
2. **日期范围查询**：支持查询某个日期范围的图片
3. **批量移动**：支持将图片移动到其他月份
4. **统计报表**：按月份统计图片数量、点赞数等

### 性能优化
1. **数据库索引**：为 `yearMonth`、`year`、`month` 字段创建索引
2. **分页加载**：实现无限滚动或分页加载
3. **缓存机制**：缓存月份列表和常用数据

## 回滚计划

如果出现问题，可以：
1. 回滚代码到之前版本
2. 删除新增的日期字段
3. 恢复数据库备份
