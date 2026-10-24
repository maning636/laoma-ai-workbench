# ADR-0010: 包体瘦身保守原则——patchright/selenium 不排除

- **状态**：已接受（补录）
- **日期**：2026-10-24
- **决策者**：工作组
- **证据分级**：【已验证】

---

## 背景

2026-10-24 收官冲刺中，安装包体积达 639 MB（约 610 MiB），用户下载体验差。瘦身目标 -150 MB，方案候选：

1. **prismenv 重复大件排除**：`.venv` 与 `prismenv/` 目录存在整份拷贝的第三方包（约 300 MB 重复）
2. **ffmpeg 按需下载**：视频渲染功能可选，ffmpeg 二进制可推迟下载
3. **locales 与杂项精简**：多语言资源只保留中文
4. **patchright/selenium 排除**：浏览器自动化引擎，体积较大但**核心功能依赖**

**证据**：
- `docs/handover/PROJECT-HANDOVER.md` §3 阶段 D3、§2.1「639 MB」
- `git show --stat da46f91`：build(size): 低风险瘦身——prismenv 重复大件排除/ffmpeg 按需/locales 与杂项精简
- `.superpowers/sdd/valkyrie-gamora-big-barda/size-analysis.md`

## 决策

**执行低风险瘦身方案，patchright/selenium 不排除**：

- ✅ 排除 `prismenv/` 重复大件（第三方包整份拷贝）
- ✅ ffmpeg 改为按需下载（首次视频渲染时下载）
- ✅ 精简多语言资源（只保留中文 + 英文兜底）
- ❌ **不排除 patchright**（浏览器自动化核心依赖，抖音/快手/小红书/B 站/视频号等平台登录发布全靠它）
- ❌ **不排除 selenium**（部分平台仍依赖 selenium fallback）

**具体落地**：
- `da46f91`：build(size): 低风险瘦身——prismenv 重复大件排除/ffmpeg 按需/locales 与杂项精简（目标 -150MB）
- `desktop-electron/electron-builder.yml`：`files` / `extraResources` 排除规则更新
- `ffmpeg` 下载脚本：`desktop-electron/scripts/download-ffmpeg-on-demand.js`

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| 排除 patchright | **核心功能依赖**：8 个平台中 6 个登录适配器、所有视频/直播采集都依赖它；排除后用户装完发现无法登录 |
| 排除 selenium | 部分平台（百家号、YouTube）仍依赖 selenium fallback |
| 用 Playwright 替代 patchright | 项目已用 patchright（patchright 是 Playwright 的 patched fork，反检测更好） |
| 全部按需下载（懒加载） | 用户体验倒退：首次使用时需下载 300+ MB |
| 上 CDN 分发大文件 | 需成本预算与运维；且用户本地解压仍占磁盘 |

## 代价

**收益**：
- 安装包体积下降（目标 -150 MB，实际约 -80 ~ -100 MB）
- 用户下载时间缩短
- 磁盘占用降低

**代价**：
- ffmpeg 首次视频渲染需联网下载（用户无网络时功能不可用）
- 精简多语言后，非中文用户体验略降
- patchright 与 selenium 仍在包内，体积优势有限

**已知副作用**：
- `prismenv/` 排除后，本地开发需重新 `pip install` 依赖
- ffmpeg 按需下载依赖网络可用性，弱网环境需 fallback

## 未来复审触发条件

- 用户反馈 ffmpeg 按需下载失败率高
- 引入 WebAssembly 版 ffmpeg（体积更小、无网络依赖）
- 平台发布通道改用官方 API（可下线 selenium fallback）
- patchright 有体积更小的替代方案

## 参考

- `docs/handover/PROJECT-HANDOVER.md` §2.1、§3 阶段 D3
- `.superpowers/sdd/valkyrie-gamora-big-barda/size-analysis.md`
- `desktop-electron/electron-builder.yml`
- Commit: `da46f91`
