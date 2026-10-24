## 改了什么

<!-- 一句话说清：本 PR 完成了什么、没完成什么。 -->
- 

## 为什么这么改

<!-- 引用 Issue / ADR / 决策台账条目。避免「为了更好」类空话。 -->
- Closes #<issue-number>
- 参见 ADR-<编号> 或决策台账条目 <编号>

## 测试证据

<!-- 逐条列出你怎么验证的。命令 + 输出摘要。禁止「应该可以了」类表述。 -->

**本地测试**：
```
$ <command>
<输出摘要 / passed / failed 数量>
```

**CI 结果**（PR 合并前必须全绿）：
- [ ] `lint` 硬门通过
- [ ] `lint-frontend` 硬门通过（如涉及前端）
- [ ] `test` 硬门通过
- [ ] `deps-gate` 硬门通过（如涉及依赖）
- [ ] `security.yml` 全部通过（如涉及依赖/代码）

**新增/修改的测试文件**：
- `tests/test_*.py` / `src/__tests__/__*.test.tsx`

## 涉及哪些坑清单条目

<!-- 引用 `docs/handover/PROJECT-HANDOVER.md` §8 的编号（如 G1 / C4 / W3 / P2）。 -->
- 触及：{{编号 1}}，{{编号 2}}
- 新增：{{若有新坑，请说明并同步更新坑清单}}

## 坑清单更新

<!-- 本 PR 是否发现了新坑？如有，请勾选并附条目草案。 -->
- [ ] 本 PR 未新增坑
- [ ] 本 PR 新增坑，条目草案如下（合并后需同步进坑清单 §8）：

```
### <编号> 坑：<一句话现象>

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| <编号> | <现象> | <根因> | <修法> |
```

## 文档同步

<!-- 涉及口径、决策、机制变动的，勾选对应项。 -->
- [ ] 不涉及文档同步
- [ ] 已更新 `README.md` / `CONTRIBUTING.md` / `SECURITY.md` / `NOTICE.txt`
- [ ] 已更新 `docs/handover/PROJECT-HANDOVER.md`（坑清单或决策台账）
- [ ] 已更新 `docs/engineering/ENGINEERING-PLAYBOOK.md`
- [ ] 已新增/更新 ADR（`docs/architecture/decisions/`）
- [ ] 已更新 `CHANGELOG.md`

## AI 参与记录

<!-- AI 参与的 commit 必须带 AI-Model trailer。 -->
- [ ] 本 PR 全部由人完成
- [ ] 本 PR 有 AI 参与，commit 均带 `AI-Model:` trailer
- AI 参与范围（如有）：{{哪些 commit / 哪些文件}}

## Reviewer 请确认

- [ ] 改动范围与 PR 描述一致
- [ ] 测试证据可复现
- [ ] 涉及坑清单条目已勾选
- [ ] 文档同步项已勾选
- [ ] 无敏感信息（凭据 / 账号 / 本机路径）泄漏
