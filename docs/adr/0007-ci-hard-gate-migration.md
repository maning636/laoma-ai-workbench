# ADR-0007: CI 从软门全改硬门

- **状态**：已接受（补录）
- **日期**：2026-10-23
- **决策者**：工作组
- **证据分级**：【已验证】

---

## 背景

2026-10-16 至 10-23 期间，`prism_backend` 的后端测试长期处于「软门」状态——CI 会跑但失败不阻塞合并。原因：pytest 陈旧断言、陈旧接口、注册码篡改用例偶发失败（1/16 概率炸）。

收官阶段面临两个压力：

1. **开源发布前必须 CI 全绿**，社区贡献无法接受一个「本地过 CI 挂」的仓库
2. **AGPL 义务与代码质量**：CI 全绿是「提供对应源码」的可信度证据

**证据**：
- `docs/handover/PROJECT-HANDOVER.md` §3 阶段 D3「开源发布与 CI 全绿」
- `git show --stat 0df4683`：修后端 pytest 陈旧断言/陈旧接口，软门转硬门
- `git show --stat d1fee57`：修 cloud_service 注册码篡改用例随机失败
- `git show --stat 206a202`：把 license 护栏测试纳入 CI 硬门
- `git show --stat 1f90fba`：CI Node 20→22

## 决策

**CI 从软门全改硬门**：所有后端 pytest、cloud_service 测试、license 护栏测试、依赖声明闸门、安全扫描、ESLint 全部纳入 `required status checks`，任一失败即阻塞合并。

**具体落地**：
- `0df4683`：修后端 pytest 陈旧断言/陈旧接口，软门转硬门
- `d1fee57`：修 cloud_service 注册码篡改用例随机失败（1/16 概率炸）
- `206a202`：把 license 护栏测试纳入 CI 硬门 + 修一条早就失效的路由枚举用例
- `1f90fba`：CI Node 20→22（jsdom 30.1.3 内嵌 undici 8.12.3，engines 要求 node ≥ 22.19.0）
- `11cc1f7`：补 cryptography 依赖声明 + 新增依赖声明闸门（双向自测）
- `d27c980`：ESLint 全量检查清零（121 → 0）
- `ab48194`：修后端 ruff 8 条 F821 真 NameError

**8 硬门清单**：见 `.github/workflows/ci.yml` 与 `docs/handover/PROJECT-HANDOVER.md` §2.2。

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| 保留软门，靠人工 review 兜底 | 开源发布前 CI 全绿是社区贡献的信任前提 |
| 只修最紧急的软门（后端 pytest） | 依赖声明闸门、安全扫描、ESLint 都是硬门；漏任何一处都会回归 |
| 用 `continue-on-error: true` 局部放行 | 等于把软门换了个名字，长期看不解决 |
| 用 `--allow-failures` GitHub Actions 语法 | 同上；且 `required status checks` 里被跳过的 check 会导致 GitHub 显示 warning |
| 把 CI 拆成「阻塞 + 非阻塞」两条 workflow | 复杂度上升，且 AGPL 义务要求提供「可运行」的源码；两条 workflow 语义模糊 |

## 代价

**收益**：
- 开源发布前 CI 全绿，社区贡献可信
- AGPL 义务履行有 CI 证据链
- 每次提交都跑全量测试，回归早发现

**代价**：
- 修 8 硬门花了 `0df4683` `d1fee57` `206a202` `1f90fba` `11cc1f7` `d27c980` `ab48194` 共 7 个 commit
- CI 运行时间从软门时代的「快但不可信」变成「慢但可信」（8 硬门串跑）
- 后续任何 CI 变更都必须评估是否会破坏硬门

**已知副作用**：
- 依赖声明闸门必须带 `--self-test` 反向自测（逐个删掉候选包的声明，要求它们必须被重新报出来），否则闸门失灵
- 注册码篡改用例曾在 1/16 概率炸（`d1fee57` 修复），测试代码仍需注意随机性

## 未来复审触发条件

- CI 运行时间超过 15 分钟，需拆分并行化
- 引入新语言 / 新测试框架（需评估是否纳入硬门）
- 社区贡献者反馈 CI 过严（需评估放宽某硬门的门槛）

## 参考

- `docs/handover/PROJECT-HANDOVER.md` §2.2、§3 阶段 D3
- `.github/workflows/ci.yml`
- Commit: `0df4683` `d1fee57` `206a202` `1f90fba` `11cc1f7` `d27c980` `ab48194`
