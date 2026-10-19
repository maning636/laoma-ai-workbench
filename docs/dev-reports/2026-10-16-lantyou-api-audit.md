# 澜途AI（lantyou.com）API审计报告

> 日期:2026-10-16
> 方法:共享浏览器CDP + fetch/XHR拦截器（已登录用户ma184610138，50积分）
> 目的:提取澜途AI的API设计、积分制、AI模型、智能体、图片类型等实现细节，为Prism-Fusion的5模块复刻提供参考

---

## 一、技术栈确认

| 层面 | 技术 | 开源项目 |
|---|---|---|
| 前端模板 | soybean-admin（Vue3后台模板） | ✅ 开源 |
| UI组件 | Naive UI | ✅ 开源 |
| 构建 | Vite + Rolldown | ✅ 开源 |
| 状态 | Pinia | ✅ 开源 |
| i18n | vue-i18n | ✅ 开源 |
| API域名 | api.lantyou.com（独立于前端lantyou.com） | — |
| 响应格式 | `{code: 200, data: ..., msg: "成功"}` | — |

---

## 二、积分制完整设计（M3核心参考）

### 2.1 积分账户结构（credit ledger：预扣+实扣）

**API**: `GET /points/account`

```json
{
  "code": 200,
  "data": {
    "primaryAccountId": 442,
    "availablePoints": 50.00,    // 可用积分
    "frozenPoints": 0.00,        // 冻结积分（生成前预扣）
    "totalPoints": 50.00,        // 总积分
    "totalConsumed": 0.00        // 已消耗积分
  }
}
```

**设计要点**：
- **双账户**：available（可用） + frozen（冻结）
- **预扣机制**：生成前先冻结积分 → 生成成功实扣（frozen→consumed） → 失败回滚（frozen→available）
- 这就是标准的credit ledger设计

### 2.2 充值选项

**API**: `GET /points/recharge/options`

```json
{
  "enabled": true,
  "pointsPerYuan": 10,            // 1元 = 10积分（1积分 = ¥0.10）
  "bonusThreshold": 1000,         // 满1000积分有赠送
  "bonusRate": 0.5,               // 赠送50%
  "minPoints": 1,
  "maxPoints": 10000,
  "presets": [
    {"points": 100, "bonusPoints": 0, "enabled": true},     // ¥10，无赠送
    {"points": 500, "bonusPoints": 0, "enabled": true},     // ¥50，无赠送
    {"points": 1000, "bonusPoints": 0, "enabled": true},    // ¥100，无赠送
    {"points": 3000, "bonusPoints": 1000, "enabled": true}, // ¥300，赠1000（到账4000）
    {"points": 5000, "bonusPoints": 2000, "enabled": true}  // ¥500，赠2000（到账7000）
  ],
  "defaultPoints": 3000,          // 默认选中3000档
  "customEnabled": true           // 支持自定义积分数量
}
```

**定价总结**：
- 1积分 = ¥0.10
- 5档预设 + 自定义（1-10000）
- 满1000积分赠50%（3000档赠1000，5000档赠2000）
- 支付方式：支付宝

### 2.3 AI能力价目表（按能力定价）

**API**: `GET /system/config/ai-point-pricing`

```json
{
  "pricingVersion": "2026-08-v2-1dszba6",
  "aiTitle": 0.10,                    // AI标题 ¥0.01/次
  "aiCategory": 0.20,                 // AI分类 ¥0.02/次
  "aiAttributes": 1.00,               // AI属性 ¥0.10/次
  "aiVariants": 1.00,                 // AI变体 ¥0.10/次
  "aiAttributesVariants": 1.50,       // ¥0.15/次
  "aiProductInfoCap": 1.50,
  "lowQualityBatch": 0.20,
  "imageProcess": 1.00,               // 图片处理 ¥0.10/次
  "aiImageGeneration": 1.50,          // AI生图 ¥0.15/张
  "apparelSkcClassification": 1.00,
  "productFissionAnalysis": 0.50,     // 裂变分析 ¥0.05/次
  "productFissionImage": 1.50,        // 裂变图 ¥0.15/张
  "productCollection": 0.00,          // 商品采集免费
  "aiImageGeneration2k": 1.50         // 2K生图 ¥0.15/张
}
```

### 2.4 积分历史记录

**API**: `GET /points/history?current=1&size=20&useFunction=`

**记录分类**：
- 积分充值
- AI设计中心
- 采集上架
- 商品裂变

**字段**：记录类型 / 积分明细 / 积分变动 / 积分余额 / 状态 / 记录时间 / 操作

---

## 三、AI生图模型（M1核心参考）

### 3.1 模型能力

**API**: `GET /ai-design/capabilities`

```json
{
  "models": [
    {
      "modelKey": "qwen3.7-plus",
      "version": 4,
      "displayName": "Qwen 3.7 Plus",
      "capabilities": ["PRODUCT_ANALYSIS"],
      "supportedAspectRatios": ["SOURCE"],
      "maxReferenceImages": 10,
      "maxInputAssets": 80,
      "maxOutputCount": 1,
      "supportedInputMediaTypes": ["IMAGE"],
      "defaultForScenes": ["PRODUCT_ANALYSIS"]
    },
    {
      "modelKey": "gpt-image-1",
      "version": 2,
      "displayName": "GPT Image 1",
      "capabilities": ["PRODUCT_ANALYSIS", "IMAGE_EDIT", "IMAGE_GENERATE"],
      "supportedAspectRatios": ["1:1", "3:4", "4:3", "1:2", "2:1", "16:9", "9:16", "CUSTOM"],
      "maxReferenceImages": 10,
      "maxInputAssets": 10,
      "maxOutputCount": 4
    }
  ]
}
```

### 3.2 关键发现：澜途不用ComfyUI

**澜途用的是商业API**：
- `gpt-image-1`（OpenAI文生图）—— 支持生成/编辑/分析
- `qwen3.7-plus`（通义千问3.7 Plus）—— 商品分析

**没有用**：ComfyUI / Stable Diffusion / Flux / DALL-E

**模型路由**：通过 `modelKey` 字段路由不同模型

### 3.3 裂变设置中的模型配置

**API**: `GET /goods/collection/fission-settings`

```json
{
  "configurations": [{
    "analysisModelKey": "qwen3.7-plus",    // 分析用通义千问
    "imageModelKey": "gpt-image-2",        // 生图用GPT image 2
    "carouselImageModel": "gpt-image-2",   // 轮播图用GPT image 2
    "carouselAspectRatio": "1:1",
    "carouselImageCount": 5,
    "detailAspectRatio": "3:4",
    "detailImageCount": 5,
    "detailMode": "CAROUSEL",
    "modelType": "WESTERN",
    "aiTitleEnabled": true,
    "aiTitleMode": "REWRITE"
  }]
}
```

---

## 四、智能体管理（M2核心参考）

### 4.1 智能体列表+配额

**API**: `GET /system/ai-agents` → `data: []`（当前无智能体）

**API**: `GET /system/ai-agents/quota`

```json
{
  "limit": 2,          // 每用户最多2个智能体（付费墙！）
  "used": 0,
  "canCreate": true
}
```

### 4.2 智能体创建表单（训练素材）

**UI**: "AI AGENT STUDIO - 为不同设计场景配置专属提示词，让图片生成保持稳定、一致的视觉方向"

**训练素材字段**：
1. **商品名称***（必填）
2. **优秀轮播图***（必填，第一张作卡片封面，"作为智能体门面的正面范例"）
3. **优秀详情图**（选填，"展示优秀案例的完整细节，供智能体学习"）
4. **额外设计原则 & 要求**（选填，12000字符内）
   - 示例：
     - 主色控制在两种以内，遵循品牌VI
     - 轮播图文案不超过12字
     - 详情页首屏必须出现利益点

**机制**："AI将根据训练素材自动生成标题、简介和设计规范"

### 4.3 智能体模式总结

```
用户上传优秀样图（轮播图+详情图）
+ 填商品名称 + 设计原则文字
→ AI自动分析素材 → 生成标题/简介/设计规范（风格prompt）
→ 存为可复用智能体
→ 后续生图时选这个智能体 → 自动套用风格
```

**这就是风格训练的核心**：不是真的"训练模型"，而是**AI分析样图 → 提取风格特征 → 生成prompt模板 → 存为智能体**。

---

## 五、AI图片设计（M1+M5参考）

### 5.1 21种图片类型

**轮播图类型（10种）**：
1. 主图（产品主图，列表展示首张）
2. 场景图（真实环境使用效果）
3. 细节图（材质/工艺/功能特写）
4. 复刻同款风格产品图（需目标图+参考图）
5. 商品换色图（需原图+颜色参考图）
6. 白底图（纯白背景，平台规范）
7. 卖点图（突出一个核心卖点）
8. 服饰穿戴图（自然穿戴效果）
9. 精修图（需参考图，精细化修图）
10. 产品爆炸图（需参考图，分层展示结构）

**详情图类型（11种）**：
1. 首屏主视觉（视觉冲击力强）
2. 核心卖点图
3. 使用场景图
4. 多角度图
5. 场景氛围图
6. 商品细节图
7. 尺寸/容量/尺码图
8. 效果对比图
9. 详细规格/参数表
10. 商品成分图
11. 使用建议图

### 5.2 图片设计页面字段

- 上传原图（最多7张，JPG/PNG/WebP）
- 生图目标语言（英语）
- 目标销售区域（美国）
- 模特（欧美模特）
- 商品名称（选填）
- 商品卖点及要求（必填，可AI填写）
- 选择图片类型（21种 + 自定义）
- 选择Agent（选填）
- 宽高比（1:1 / 3:4 / 4:3 / 16:9 / 9:16 / 自定义）
- 生成张数
- 预计消耗积分（动态计算）

### 5.3 自定义图片类型

**API**: `GET /ai-design/custom-image-types` → `data: []`

---

## 六、完整路由表

```
/home                          首页
/ai-design                     AI内容创作
/ai-design/image               AI图片设计
/ai-design/agents              智能体管理
/ai-design/records             生成记录
/ai-design/workflow-records    工作流记录
/ai-design/skills              技能库
/ai-design/infinite-canvas     无限画布
/product-collect               商品采集
/collection                    采集
/prepublish                    预发布
/goods                         商品
/size-charts                   尺码表
/product-templates             模板管理
/publish-records               发布记录
/products                      在线产品/产品库
/operation                     自动化运营
/operation/template            运营模板
/operation/workflow            运营工作台
/operation/image-confirmation  图片待确认
/points                        积分购买
/manage                        系统管理
/manage/mall                   店铺管理
/manage/user                   用户管理
/manage/role                   角色管理
/iframe-page/:url              iframe页面
/login/:module                 登录/注册/重置密码/绑定微信
```

---

## 七、API端点清单

| API | 方法 | 说明 |
|---|---|---|
| `/points/account` | GET | 积分账户 |
| `/points/history` | GET | 积分历史 |
| `/points/recharge/options` | GET | 充值选项 |
| `/system/config/ai-point-pricing` | GET | AI积分定价 |
| `/system/ai-agents` | GET | 智能体列表 |
| `/system/ai-agents/quota` | GET | 智能体配额 |
| `/system/ai-agents/options` | GET | 智能体选项 |
| `/ai-design/capabilities` | GET | AI模型能力 |
| `/ai-design/custom-image-types` | GET | 自定义图片类型 |
| `/goods/collection/settings` | GET | 采集设置 |
| `/goods/collection/settings-groups` | GET | 采集设置分组 |
| `/goods/collection/fission-settings` | GET | 裂变设置 |
| `/mall/boundCounts` | GET | 店铺绑定计数 |

---

## 八、对Prism-Fusion复刻的启示

### 8.1 M1 文生图

**澜途方案**：调商业API（gpt-image-1 + qwen3.7-plus）
**我们的选择**：
- 方案A：照澜途，调商业API（gpt-image/通义千问）—— 快，但要付API费
- 方案B：自部署ComfyUI —— 免费，但要GPU+运维
- 方案C：两者都支持（modelKey路由）—— 灵活，但工作量大

**建议**：方案C。`modelKey`路由设计参考澜途，支持商业API + ComfyUI双后端。

### 8.2 M2 智能体

**澜途方案**：AI分析样图 → 生成风格prompt → 存为智能体（不是真训练）
**我们的复刻**：
- 用户上传优秀内容样例（文案/图片）
- AI分析 → 提取风格特征 → 生成prompt模板
- 存为"风格Profile"
- 后续AI调用自动套用
- 配额限制（付费墙）

### 8.3 M3 积分制

**澜途方案**：credit ledger（available/frozen/consumed）+ 充值选项 + 价目表
**我们的复刻**：**直接照搬设计**
- 积分账户：availablePoints / frozenPoints / totalConsumed
- 充值：5档预设 + 自定义 + 赠送规则
- 价目表：按AI能力定价
- 支付：微信/支付宝（我们已有）

### 8.4 M4 工作流

**澜途方案**：首页场景引导（AI生图/Temu上架/Temu运营）
**我们的复刻**：首页加场景引导（AI写稿发布/AI生图发布/视频流水线）

### 8.5 M5 图片编辑器

**澜途方案**：无限画布（infinite-canvas）
**我们的复刻**：用unlayer/react-image-editor（MIT）+ tldraw（无限画布）

### 8.6 定价参考

| 澜途 | 定价 |
|---|---|
| 1积分 | ¥0.10 |
| AI生图 | 1.5积分 = ¥0.15/张 |
| AI标题 | 0.1积分 = ¥0.01/次 |
| 充值档位 | ¥10/¥50/¥100/¥300/¥500 |
| 赠送规则 | 满1000积分赠50% |

---

## 九、总结

澜途AI的核心商业模式：**积分制按量计费 + 商业API赚差价**。
- 用户充值积分（¥0.10/积分）
- AI调用扣积分（生图1.5积分=¥0.15）
- 澜途付OpenAI API费（gpt-image-1约$0.04/张≈¥0.27）
- **等等，这个账算不过来**——¥0.15 < ¥0.27？

**可能的原因**：
1. 澜途用的是gpt-image-1的批量/缓存折扣
2. 或者澜途用的是其他更便宜的模型（gpt-image-2可能是自研/第三方）
3. 或者积分定价有补贴（用户充值时有赠送，实际成本更低）

**对我们的启示**：如果走商业API路线，要算清API成本 vs 积分定价的差价，确保盈利。
