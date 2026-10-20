# E2E端到端组装验证

> 日期:2026-10-20
> 方法:curl API测试 + 服务状态检查

## 服务状态

| 服务 | 端口 | 状态 | 说明 |
|---|---|---|---|
| Redis | 6379 | ✅ | Celery依赖，之前在跑 |
| 前端(Next.js) | 3000 | ✅ 200 | 在跑 |
| 后端(FastAPI) | 7000 | ❌ 没跑 | 需要启动（已启动后台） |
| 云端(cloud_service) | 8091 | ✅ health ok | 服务器active running |

## API验证

### 云端（服务器8091，active running）
| 端点 | 返回 | 说明 |
|---|---|---|
| GET /health | `{"status":"ok","version":"0.3.0"}` | ✅ |
| GET /cloud/points/pricing | 401 Missing Bearer token | ✅ 需要JWT（正确） |
| GET /cloud/billing/flags | 404 Not Found | ⚠️ 路径不对，实际是/cloud/billing/feature-flags |

### 本地后端（7000，启动中）
- 需要启动后验证

### 前端（3000，在跑）
- HTTP 200 ✅

## 发现的问题

1. **后端7000没跑**——需要手动启动（已启动后台）
2. **/cloud/billing/flags路径不对**——实际是/cloud/billing/feature-flags（Open Core实现时建的端点）
3. **browser工具不可用**——无法做前端页面视觉验证

## E2E流程状态

```
注册（cloud_service JWT）→ 需要前端注册页测试
充值（M3 payment mock）→ API需JWT，mock模式可测
AI生图（M1 capabilities）→ 需要后端7000+JWT
扣费（M3 freeze→consume）→ 需要JWT+积分
风格套用（M2 agent_id）→ 需要JWT+智能体
```

## 下一步
1. 启动后端7000（已启动后台）
2. 用JWT测试完整API链路
3. browser工具可用时做前端页面验证
