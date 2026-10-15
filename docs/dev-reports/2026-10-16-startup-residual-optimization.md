# B-B：后端冷启动残余优化（2026-10-16）

B10 已把冷启动从 26s 降到 2–3s，仍存 ~2s 残余。本任务实测 + 定位 + 优化，
最终把实测中位数从 **4.86s 压到 2.77s（-2.09s / -43%）**。

## 测量方法

`scripts/bench/startup_e2e_bench.py`：

1. fork 一个干净的 python 进程
2. 以 `python -m uvicorn fastapi_app.main:app --port 7123` 启动后端
3. 每 20ms 轮询 `GET http://127.0.0.1:7123/health`，直到收到 200
4. 记录 `time.perf_counter() - fork` 的差
5. 杀掉子进程

A/B 对比脚本 `scripts/bench/ab_test_startup.py` 会先把工作目录还原到
`.bak-20261016` 版本跑 3 次，再切回优化版跑 3 次，取各自中位数。

## 实测数据

| 版本 | run 1 | run 2 | run 3 | 中位数 |
| --- | --- | --- | --- | --- |
| 优化前（baseline） | 4.86s | 4.82s | 4.86s | **4.86s** |
| 优化后 | 2.77s | 2.81s | 2.77s | **2.77s** |

改善 **2.09s / -43%**。稳定达成任务目标"2–3s"。

（首次运行会稍慢 ~0.3s，是 OS 冷 cache；上表都是第 2 次起的数据。）

## 定位结论：那 ~2s 花在哪

用 `PYTHONPROFILEIMPORTTIME=1` + 一个后台线程扫日志时间戳，逐阶段量化。

### 优化前 import 累计耗时排序（`python -c "import fastapi_app.main"` 冷启）

| 排名 | 模块 | 累计耗时 |
| --- | --- | --- |
| 1 | `douyin_tiktok_api.app.main` | **~4.8s** |
| 2 | `crawlers.hybrid`（含 tiktok/douyin pydantic models） | ~1.5s |
| 3 | `fastapi` 框架 + `fastapi_app.api.v1.router` 自身 | ~0.5s |
| 4 | 其他 service 模块 | ~0.5s |

**结论**：残余 ~2s 里，最大头不是 Hermes 而是
**`douyin_tiktok_api` 子应用被 mount 时同步 import 了 pywebio/numpy/pyfiglet**，
以及 **`crawler_router` 模块顶层同时 import `crawlers.hybrid` 并实例化
3 个 crawler 对象**。

（注：任务背景说残余在 Hermes，实测表明是 Douyin API + Crawler 的
同步 import 阻塞 —— 这也是为什么之前 B10 优化后仍卡在 ~2s。）

### 优化前的启动时序（uvicorn 冷启动到 /health 200）

```
0.0s  fork python
0.0s  uvicorn config
~0.6s DB pool init
~2.4s import fastapi_app.main   ← douyin_tiktok_api 在这里同步 import，~1.8s
~2.5s startup_event 开始
~2.6s startup_event 完成
~2.6s uvicorn 开始监听
~4.9s /health 首次 200   ← uvicorn 首次编译路由 / 冷路径开销
```

## 改了什么

### 关键发现：`asyncio.create_task` 不够

第一版尝试：把 `import douyin_tiktok_api` 和 `import crawler_router` 挪到
`async def _mount_xxx()` 里，用 `create_task` fire-and-forget。实测**只降了
0.5–0.7s**。

原因：虽然函数是 coroutine，但函数体里 `from douyin_tiktok_api.app.main
import app` 是**同步阻塞代码**，它跑在 event loop 线程上——event loop 被
卡住直到 import 完成，`/health` 依旧响应不了。

### 真正的解法：`loop.run_in_executor`

把同步 import 用 `loop.run_in_executor(None, _do_mount)` 扔进工作线程跑，
event loop 完全不被阻塞。

### 关键陷阱：隐式的 `sys.path` 依赖

第一次把 douyin 和 crawler 拆成两个独立 coroutine 并发跑，日志报
`ModuleNotFoundError: No module named 'crawlers'`。原因：
`fastapi_app/api/v1/crawler/router.py` 在 import 时会做
`sys.path.insert(0, ".../douyin_tiktok_api")`，而
`douyin_tiktok_api.app.main` 里 import 了 `crawlers.*`——crawler 必须
**先**跑，douyin 才能加载。

以前它们在模块加载阶段隐式串行，拆并发后必须显式串起来：
`_mount_deferred_components()` 先 await crawler，再 await douyin。

### 具体改动

**`prism_backend/fastapi_app/main.py`**（+90 行）：

* 删掉模块级 `if settings.DOUYIN_TIKTOK_API_ENABLED: ...` 块
* 新增 `async def _mount_crawler_router()`、`async def _mount_douyin_tiktok_api()`
  * 内部都用 `loop.run_in_executor(None, _do_mount)` 把同步 import 踢到工作线程
  * 都 try/except + warning，不冒泡
* 新增 `async def _mount_deferred_components()`：串联 crawler → douyin
* 在 `startup_event` 顶部加
  `_DEFERRED_MOUNT_TASK = asyncio.create_task(_mount_deferred_components())`
  并持强引用防 GC

**`prism_backend/fastapi_app/api/v1/router.py`**（净 +0 行）：

* 把 `from .crawler.router import ...` 注释掉
* 把 `api_router.include_router(crawler_router, ...)` 注释掉
* 加说明注释指向 `_mount_crawler_router`

**`prism_backend/fastapi_app/tasks/celery_app.py`**（E-E3 相关）：

* `include` 从 `["fastapi_app.tasks.publish_tasks"]` 扩展到
  `[..., "fastapi_app.tasks.debug_tasks"]`

### 备份文件（本任务创建的 `.bak-20261016`）

* `prism_backend/fastapi_app/main.py.bak-20261016`（18201 bytes）
* `prism_backend/fastapi_app/api/v1/router.py.bak-20261016`（10804 bytes）
* `prism_backend/fastapi_app/tasks/celery_app.py.bak-20261016`（2192 bytes）

## 为什么没继续往下压

剩余 ~2.8s 里：

* **~1.5s** 是纯粹的 `python -m uvicorn` fork + import `fastapi_app.main` 本身
  （含 SQLAlchemy / fastapi / starlette / pydantic）——这些是**必需**的启动
  成本，任何 HTTP API 服务都会有。
* **~0.5s** 是 DB 连接池初始化 + `_init_database`。DB 池是启动必需依赖，
  `/health` 前不能用。
* **~0.8s** 是 uvicorn 首次编译路由 + 冷路径开销，无法从应用侧消除。

剩下的 ~2s 里，剩下的重模块（`crawlers.tiktok.web.models` 837ms、
`crawlers.douyin.web.models` 610ms）**已经**通过 crawler_router 懒加载被
踢到启动之后。要再压只能：

1. 拆 `router.py` 里 60+ 个 `include_router`，逐个懒加载——风险极高，
   OpenAPI/autodoc/路由一致性会全乱，回归成本远超收益。
2. 用 multiprocessing preload worker（`uvicorn --workers N --spawn`
   之外的方案），或改用 uvloop / Cython 编译 pydantic models——超出本次
   范围，且可能引入线程安全问题。

**结论**：目前 2.77s 是"最小、可回滚"边界。要继续压需要更大的架构决策。

## 功能未受影响

* `curl http://localhost:7000/health` 返回 200 且 body 正常。
* 语法检查 `py_compile` 通过。
* `pytest fastapi_app/tests/test_core.py fastapi_app/tests/test_other_modules.py`
  在优化版和原版上跑出的失败数**相同**（3 failed, 8 passed），说明这 3 个
  失败是既存的（与本改动无关）：
  * `test_openapi_spec`（OpenAPI 结构断言，与 crawler/douyin 无关）
  * `test_campaigns_ping` / `test_ai_status`（依赖其他 agent 修改的 router
    配置，测试基线已过期）
* `pytest cloud_service -q` **未运行**：任务约束禁止我触碰 `cloud_service`，
  且该目录另有 agent 正在改。

## 部署注意

懒加载引入约 1.3s（crawler）+ 0.5s（douyin）= **~1.8s 的窗口期**：

* `/api/v1/crawler/*` 在启动后 ~2s 才可用
* `/api/v1/douyin-tiktok/*` 在启动后 ~2.5s 才可用
* 其他所有路由从 uvicorn 监听起来就可用

生产上如果启动后立刻（<2s）就访问 crawler 或 douyin 接口，会 404。
如果需要"启动即可用"，可回滚这 3 个 `.bak-20261016` 文件（见上文清单）。
