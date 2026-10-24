# ADR-0006: 抖音登录禁 HTTP 逆向，走浏览器

- **状态**：已接受（补录）
- **日期**：2026-10-13（初版）→ 2026-10-24（补录 ADR）
- **决策者**：工作组
- **证据分级**：【已验证】

---

## 背景

`prism_backend/app_new/platforms/douyin_http.py`（`DouyinHttpAdapter`）是实验性逆向实现，通过纯 HTTP 请求模拟抖音扫码登录流程。2026-10 期间在开发环境反复出现 `error_code=2156 "系统繁忙"` 报错，实测证据链见 `prism_backend/reverse_api/DOUYIN_HTTP_2156_FINDINGS.md`。

根因分析：

1. passport 在扫码确认阶段要求 verifycenter 会话信任
2. `/passport/web/challenge/` + rmc-nocaptcha 行为指纹采集，种 `s_v_web_id` 等 cookie
3. 该信任**只能由真实浏览器 JS 建立**，HTTP 客户端无法复刻
4. 结果：扫码确认被拒

**证据**：
- `prism_backend/AGENTS.md` §「抖音登录：HTTP 逆向（app_new）生产禁用」
- `prism_backend/reverse_api/DOUYIN_HTTP_2156_FINDINGS.md` — 实测证据链
- `prism_backend/app_new/platforms/douyin_http.py` — HTTP 逆向实现
- `prism_backend/app_new/platforms/douyin.py` — 生产用浏览器适配器

## 决策

**生产登录必须走浏览器模式**：

- ✅ `DouyinAdapter`（`app_new/platforms/douyin.py`，patchright + 本机浏览器）
- ✅ `PlaywrightLoginManager`（`fastapi_app/api/v1/auth/services.py`）

**生产禁用 HTTP 逆向**，包括但不限于：

- ❌ 把 `LAOMA_DOUYIN_LOGIN_MODE` 设为 `http` 用于正式环境
- ❌ 让 worker / API 默认走 `DouyinHttpAdapter`
- ❌ 在账号系统、发布链路、桌面端中依赖 HTTP 登录产出的 cookie
- ❌ 移除/绕过下述限制、或把 HTTP 登录伪装成正式功能

**具体落地**：
- `prism_backend/AGENTS.md` §「抖音登录」章节，明确「experimental」定位
- 生产默认 `LAOMA_DOUYIN_LOGIN_MODE = browser`（未在 `.env.example` 中显式写 http 值）

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| HTTP 逆向作为正式功能 | 扫码确认被拒（`error_code=2156`），无法完成登录闭环 |
| 移除浏览器模式，全面走 HTTP | 依赖 JS 建立的行为指纹信任无法用 HTTP 复刻 |
| 用 headless 但伪装成非 headless | verifycenter 有反 headless 检测，风险高 |
| 混合模式（HTTP 探测 + 浏览器确认） | 复杂度上升，且浏览器确认本身仍要 patchright 拉起 |
| 移除 `DouyinHttpAdapter` 代码 | 保留开发/逆向研究用途；HTTP 请求的 a_bogus / D-Trait 签名研究价值仍在 |

## 代价

**收益**：
- 生产登录稳定，扫码确认成功率接近 100%
- 与抖音官方 ToS 距离更近（走真实浏览器，不像 HTTP 逆向）
- 逆向研究代码保留，可用于 a_bogus 签名研究

**代价**：
- 生产需拉起本机浏览器（patchright），CPU/内存占用比 HTTP 高
- 依赖系统安装的浏览器内核（Chromium）
- 无法在无显示器的服务器环境跑登录（需 headless 但有反 headless 风险）

**已知副作用**：
- 修改登录相关代码前，必须先读 `DOUYIN_HTTP_2156_FINDINGS.md` 与 `prism_backend/AGENTS.md`
- HTTP 逆向代码若被误用作生产功能，会产生难以排查的登录失败

## 未来复审触发条件

- 抖音官方 API 开放（抖音开放平台登录 API 正式可用）
- verifycenter 会话信任机制变化（HTTP 逆向成为可能）
- 引入无头浏览器方案（如 Playwright 官方反 headless 支持成熟）

## 参考

- `prism_backend/AGENTS.md` §「抖音登录：HTTP 逆向（app_new）生产禁用」
- `prism_backend/reverse_api/DOUYIN_HTTP_2156_FINDINGS.md`
- `prism_backend/app_new/platforms/douyin_http.py`
- `prism_backend/app_new/platforms/douyin.py`
