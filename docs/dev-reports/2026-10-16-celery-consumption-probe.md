# Celery 消费链路验证 (E-E3)

生产 `celery inspect ping` 已经能通，但那只证明 worker 在线，**"能消费任务"**
这一项之前没法在不触发真实发布的前提下验证（`publish.single` / `publish.batch`
都会真的往平台发内容）。

## 探针任务

* 任务名：`debug.echo`
* 位置：[`prism_backend/fastapi_app/tasks/debug_tasks.py`](../../prism_backend/fastapi_app/tasks/debug_tasks.py)
* 行为：接收一个任意 JSON-可序列化参数，原样回传，并打三条 `loguru` INFO 日志。
  无网络、无文件、无 DB、无平台 API 调用，任务体在毫秒级完成。
* 命名：所有探针任务都挂 `debug.` 前缀，且通过
  `celery_app.conf.include` 里的 `fastapi_app.tasks.debug_tasks` 单独加载，
  方便日后审计/关闭。

## 投递 & 观测

### 方式 A：临时独立验证 worker（推荐，对生产 worker 零影响）

生产 worker（`prism-worker-test@DESKTOP-HOT7UMB`，PID 6408 / 13168）启动时
没有 `debug_tasks`，不重启它，我们另起一个只监听 `debug_queue` 的验证 worker。

```powershell
Set-Location 'D:\dim开发\Prism-Fusion\prism_backend'
$env:PYTHONPATH = "D:\dim开发\Prism-Fusion\prism_backend;$env:PYTHONPATH"
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
$env:FORKED_BY_MULTIPROCESSING = '1'

Start-Process -FilePath 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe' `
    -ArgumentList '-m','celery','-A','fastapi_app.tasks.celery_app','worker',`
        '--loglevel=info','--pool=solo','--concurrency=1',`
        '--queues=debug_queue','--hostname=verify-debug@DESKTOP-HOT7UMB' `
    -WorkingDirectory 'D:\dim开发\Prism-Fusion\prism_backend' `
    -WindowStyle Hidden
# 记下 PID，验证完 Stop-Process -Id <PID> -Force
```

启动成功标志（约 2s）：

```
[tasks]
  . debug.echo
  . publish.batch
  . publish.single
```

`celery inspect registered` 应看到两个节点，`verify-debug@...` 那行多出 `debug.echo`。

### 方式 B：Celery 5.4 已移除 `send-task` 子命令

老的 `celery send-task debug.echo --queue=debug_queue --args='["hello"]'` 会报
`Error: No such command 'send-task'`。用下面这段等价脚本投递：

```powershell
@'
from fastapi_app.tasks.celery_app import celery_app
import time
result = celery_app.send_task("debug.echo", args=["hello"], kwargs={}, queue="debug_queue")
print("task_id:", result.id)
time.sleep(2)
print("state:", result.state)
print("result:", result.result)
'@ | & 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe' -
```

### 期望输出

```
state: SUCCESS
result: {'ok': True, 'received': 'hello', 'worker_received_at': <float>}
```

worker 日志同时会打出四条关键行：

```
[INFO/MainProcess] Task debug.echo[...] received
... | fastapi_app.tasks.debug_tasks:debug_echo:37 - [debug.echo] task received, payload_type=str
... | fastapi_app.tasks.debug_tasks:debug_echo:40 - [debug.echo] payload=hello
[INFO/MainProcess] Task debug.echo[...] succeeded in 0.003s: {...}
```

## 生产 worker 何时能消费 debug.echo

生产 worker 的 `include` 列表在
[`fastapi_app/tasks/celery_app.py`](../../prism_backend/fastapi_app/tasks/celery_app.py)
里维护，重启生产 worker 后它会自己加载 `debug_tasks`，同样能消费
`debug.echo`——不过它默认监听的是 `celery` 主队列而不是 `debug_queue`，
投递时必须用默认队列或改生产 worker 的 `--queues` 配置。

## 何时清理

* 任务定义（`debug_tasks.py`）建议保留，它是长期无害的探针。
* 验证 worker（方式 A）验证完 `Stop-Process` 掉；不会污染生产。
