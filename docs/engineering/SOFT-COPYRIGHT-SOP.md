# 软件著作权登记申请材料 SOP

> 中国计算机软件著作权（软著）登记申请材料的编写与准备标准操作流程。适用对象：`老马AI工作台 / Prism-Fusion / LaomaAI-Fusion` 项目。

---

## 1 适用范围与前置条件

- 本项目已在 2026-10-23 开源发布（AGPL-3.0，`maning636/laoma-ai-workbench`，Release `v1.1.5`）
- **AGPL 协议不影响软件著作权登记**，但登记后开源义务继续有效（见 §5）
- 前置条件：已获得中国版权保护中心（CPCC）账户；准备软件全称、简称、版本号等基本信息

## 2 申请表要素

登录 CPCC 官网填写申请表时，以下字段需与仓库 `NOTICE.txt`、`README.md`、`LICENSE` 保持一致：

| 字段 | 建议值 | 依据 |
|---|---|---|
| **软件全称** | 老马AI工作台V1.1.5 | 品牌切换后正式产品名（2026-10-13 从 `PRISM_` 切换） |
| **软件简称** | Prism-Fusion | 代码库名 |
| **版本号** | V1.1.5 | 与 Release `v1.1.5` 一致 |
| **开发完成日期** | 2026-10-23 | 单一客户端合并日（`e6c1925`） |
| **首次发表日期** | 2026-10-23 | 开源发布日 |
| **开发方式** | 独立开发 | 项目由个人/小微团队独立完成 |
| **开发完成人** | maning636（署名） | 与 `NOTICE.txt:3` 一致 |
| **编程语言** | Python + TypeScript | 后端 Python（FastAPI + Celery + patchright），前端 TypeScript（Next.js + React） |
| **源程序量（行）** | 见 §3.2 cloc 统计命令 | 前后端合计 |
| **使用的开发环境** | Windows 11 / Ubuntu 22.04 / GitHub Actions | 开发机 + CI |

## 3 源程序材料

### 3.1 材料形态

- 前后各连续 **30 页**（共 60 页），每页 **50 行**（共 3000 行）
- 页眉带软件名 + 版本号：`老马AI工作台V1.1.5`
- 页眉右侧带页码：`第 X 页`
- 每页首行加 `// Page X` 注释（Python 用 `# Page X`，TS 用 `// Page X`）

### 3.2 导出脚本思路

```python
# scripts/docs/build_soft_copyright_source.py
"""按目录顺序拼接前 30 页 + 后 30 页，每页 50 行，页眉带软件名+版本号"""

REPO = "D:/dim开发/Prism-Fusion"
VERSION = "1.1.5"
PAGE_SIZE = 50
PAGE_COUNT = 60  # 30 前 + 30 后

# 按逻辑顺序列出源文件（后端 → 前端 → 云端 → 桌面）
SOURCE_DIRS = [
    "prism_backend/fastapi_app",
    "prism_backend/app_new",
    "prism_backend/fusion_ai",
    "cloud_service",
    "prism_frontend/src",
    "desktop-electron/src",
]

def list_source_files():
    files = []
    for d in SOURCE_DIRS:
        for ext in ("*.py", "*.ts", "*.tsx", "*.js"):
            files.extend(glob.glob(f"{REPO}/{d}/**/{ext}", recursive=True))
    return sorted(files)

def paginate(files):
    """把源文件切分成 3000 行，前后各 30 页"""
    # ... 实现按页拆分逻辑
```

**cloc 统计行数命令**（用于「源程序量」字段）：

```bash
# 安装 cloc
pip install cloc  # 或 conda install -c conda-forge cloc

# 统计前后端源代码
cloc --exclude-dir=node_modules,.venv,_caches,_appdata_electron,artifacts,dist,node_modules,.git \
     --include-ext=py,ts,tsx,js \
     prism_backend/ cloud_service/ prism_frontend/src/ desktop-electron/src/

# 或用 Python 直接统计（无 cloc 时）
python -c "import os; total=0; [total:=total+sum(1 for _ in open(f)) for f in __import__('pathlib').Path('.').rglob('*.*') if f.suffix in ('.py','.ts','.tsx','.js')]; print(total)"
```

### 3.3 前 30 页 / 后 30 页选取原则

- **前 30 页**：从 `prism_backend/fastapi_app/__init__.py` 起，按文件顺序取 1500 行
- **后 30 页**：从 `desktop-electron/src/main/index.js` 起，按文件顺序取最后 1500 行
- 每页页眉：`老马AI工作台V1.1.5　　第 X 页`（居中或左侧对齐，字号 10pt）

## 4 文档材料（60 页）

文档材料**任选一**：用户手册 或 设计说明书。本项目建议改写 **PROJECT_OVERVIEW + ENGINEERING-PLAYBOOK 骨架**。

### 4.1 改写要点

- **标题**：`老马AI工作台V1.1.5 用户手册`（或设计说明书）
- **章节骨架**：
  1. 概述（从 `docs/PROJECT_OVERVIEW.md` §1「项目定位」）
  2. 系统架构（从 `docs/engineering/ENGINEERING-PLAYBOOK.md` §架构）
  3. 功能清单（从 `docs/feature-inventory-and-oss-boundary.md`）
  4. 部署说明（从 `docs/dev-reports/2026-10-13-deployment-guide.md`）
  5. 操作指南（新增，从 `docs/client-acceptance-checklist.docx` 反推）
  6. 附录（接口列表、数据模型、故障排查）
- **60 页约束**：文档材料不超过 60 页，超出需精简
- **署名**：与 `NOTICE.txt:3` 一致（`maning636`）

### 4.2 现有素材索引

| 现有文档 | 位置 | 建议用途 |
|---|---|---|
| PROJECT_OVERVIEW | `docs/PROJECT_OVERVIEW.md` | 用户手册 §1-2 |
| ENGINEERING-PLAYBOOK | `docs/engineering/ENGINEERING-PLAYBOOK.md` | 设计说明书骨架 |
| feature-inventory | `docs/feature-inventory-and-oss-boundary.md` | 功能清单 |
| PROJECT-HANDOVER | `docs/handover/PROJECT-HANDOVER.md` | 附录与背景 |
| dev-reports | `docs/dev-reports/` | 部署与操作指南 |

## 5 版本与权利归属

### 5.1 开源协议与软著的关系

- **AGPL-3.0 是开源协议**，规范的是「如何使用、修改、分发」该软件的**行为**
- **软件著作权登记**是**著作权**登记，登记的是「该软件的著作权归属」
- **两者不冲突**：AGPL 不影响著作权登记；反之，著作权登记后，AGPL 义务继续有效
- **实务建议**：登记时保留 `LICENSE`（AGPL-3.0）在仓库中，不要因登记而改协议

### 5.2 署名与 NOTICE 一致性

- `NOTICE.txt:3` 现署名：`maning636`（由 `312e4ba` 修正）
- 软著申请表「著作权人」字段：**必须**与 `NOTICE.txt:3` 一致
- 若后续变更署名（如引入合作方），需同步更新：
  1. `NOTICE.txt`
  2. 软著申请表
  3. 版本号 bump（`.github/workflows/release.yml` 触发新 Release）

### 5.3 版本号一致性

- 软著登记版本号（V1.1.5）**必须**与 Release tag `v1.1.5` 一致
- 后续版本更新需重新登记（软著登记按版本，非按产品）

## 6 时间线与费用

| 通道 | 周期 | 费用（参考） |
|---|---|---|
| **普通通道** | 60-75 工作日 | 官费约 300 元/件 |
| **加急通道** | 3-20 工作日（分档） | 官费 + 加急费（分档递增） |
| **当天通道** | 24 小时内 | 官费 + 高加急费 |

> ⚠️ **以上周期与费用为撰写本文档时的参考值**（2026-10）。**实际以中国版权保护中心当期口径为准**，请以官网公告为准（`https://www.ccopyright.com.cn/`）。

## 7 提交流程

1. 完成申请表填写（§2）
2. 导出源程序材料（§3）：前 30 页 + 后 30 页，共 60 页
3. 编写文档材料（§4）：用户手册或设计说明书，共 60 页
4. 在 CPCC 官网提交申请（`https://www.ccopyright.com.cn/`）
5. 上传电子材料（PDF 格式，每份 ≤ 50 MB）
6. 缴纳官费（在线支付）
7. 等待审查（普通 60-75 工作日 / 加急 3-20 工作日）
8. 领取登记证书（电子版 + 纸质版可选）

## 8 参考

- 中国版权保护中心：`https://www.ccopyright.com.cn/`
- `LICENSE`（AGPL-3.0）— 开源协议
- `NOTICE.txt:3` — 署名一致性依据
- `docs/PROJECT_OVERVIEW.md` — 用户手册骨架素材
- `docs/engineering/ENGINEERING-PLAYBOOK.md` — 设计说明书骨架素材
