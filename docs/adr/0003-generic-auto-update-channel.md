# ADR-0003: 自动更新保留 generic 自建通道，不切 GitHub provider

- **状态**：已接受（补录）
- **日期**：2026-10-23
- **决策者**：马哥（P3=A 拍板）+ 工作组
- **证据分级**：【已验证】

---

## 背景

electron-builder 支持两种自动更新通道：

1. **`github` provider**：`latest.yml` 落在 GitHub Release，客户端从 `raw.githubusercontent.com` / `github-releases.githubusercontent.com` 拉取
2. **`generic` provider**：任意 HTTPS 静态资源服务器

2026-10-23 开源发布前，`.github/workflows/release.yml` 里配置的是 generic provider，指向 `https://maning789link.top/downloads`。开源后出现「是否切 GitHub provider」的争论。

**证据**：
- `docs/handover/PROJECT-HANDOVER.md` §2.1「下载速度实测」表
- `docs/handover/PROJECT-HANDOVER.md` §4「P3=A」行
- `docs/handover/PROJECT-HANDOVER.md` §6.4 路线图「等国内带宽或镜像条件成熟，否则是净退化」

## 决策

**保留 generic provider + 自建镜像 `https://maning789link.top/downloads`，不切 GitHub provider**。

**具体落地**：
- `.github/workflows/release.yml`：`build.publish.provider = generic`，`url = https://maning789link.top/downloads`
- 官网 nginx 段：`location ^~ /downloads/ → alias /var/www/prism-downloads/`；`location = /downloads/latest.yml` 为 no-cache（确保 `latest.yml` 修改即时生效）
- 官网首页保留 GitHub 直链为主 + 自建镜像兜底 + Release 页三通道（P1=A）
- 版本顶号：`scripts/packaging/build-version.json`（现为 `1.1.5` / `buildNumber: 5`）

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| 切 GitHub provider 自动更新 | 国内 GitHub 直连 0.12 MB/s，639 MB 约 89 分钟，对国内用户是**净退化** |
| 双 provider 并存（用户自选） | electron-builder 客户端只支持单一 provider 配置，无法运行时切换 |
| 上 COS / OSS CDN | 需成本预算与运维；现阶段双通道 0 成本足够 |
| JS 智能分流（检测网络再决定） | 客户端已安装后才启动，分流逻辑只能在 Electron 侧写，复杂度高 |
| 升服务器带宽 | 自建镜像直连 0.36 MB/s，已够用；升级带宽是运维成本 |

## 代价

**收益**：
- 国内用户下载速度从 0.12 MB/s 提升到 0.36 MB/s（自建镜像）或 2.25 MB/s（走代理的 GitHub）
- 官网单一入口（P1=A），无分流复杂度
- 零带宽成本，无需 CDN 合同

**代价**：
- 更新元数据依赖 `maning789link.top` 域名，需自行维护
- `latest.yml` no-cache 段若配置错误，会缓存旧元数据导致用户收不到更新
- 服务器故障时自动更新不可用（无 CDN 兜底）

**已知副作用**：
- GitHub Release 的资产是 canonical 副本，`_appdata_` 侧的自建镜像需手工同步
- 服务器内存只有 3.6 GB，`latest.yml` 更新脚本需小心不要占满内存

## 未来复审触发条件

- 服务器带宽或稳定性成为瓶颈（>10 用户同时下载导致超时）
- 官方 GitHub Releases 国内直连速度提升到 >1 MB/s
- 引入 CDN 后自建镜像成为冗余

## 参考

- `docs/handover/PROJECT-HANDOVER.md` §2.1、§4「P3=A」、§6.4、§9.4
- `docs/release-delivery-statement.md` — 下载地址口径
- `.github/workflows/release.yml`
- `deploy/nginx-prism-cloud.conf`
