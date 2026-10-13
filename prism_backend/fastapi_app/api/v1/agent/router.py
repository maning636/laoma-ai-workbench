"""
Agent API routes.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from typing import Dict, Any, Optional, Union, AsyncGenerator, List
from pydantic import BaseModel, Field
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

from .models import (
    SaveScriptRequest,
    SaveScriptResponse,
    ExecuteScriptRequest,
    ExecuteScriptResponse,
    SystemContext,
)
from .services import agent_service
from .config_routes import router as config_router
from ....core.logger import logger
from ....core import paths
from ....schemas.common import Response


router = APIRouter(prefix="/agent", tags=["AI Agent"])
router.include_router(config_router, prefix="")


# ── Easel status（P2-1）：独立端点，避免把 3s 网络探测内嵌进 /hermes 拖慢响应 ──
@router.get("/easel/status")
async def easel_status():
    """返回 Easel Web 工作台状态 + skills_dir。

    `get_easel_status` 本身是 async 函数，内部已经用 httpx.AsyncClient 做
    3s 超时的 Web API / gateway 探测，直接 await 即可，事件循环不会被阻塞。
    """
    try:
        from ....services.easel_workbench import get_easel_status

        status = await get_easel_status()
        try:
            status["skills_dir"] = str(paths.get_skills_dir())
        except Exception:
            status["skills_dir"] = None
        return {"data": status}
    except Exception as exc:  # noqa: BLE001
        return {"data": {"error": str(exc)}}


# ── Easel update 只读端点（P3-3a）：只暴露 status/check，不暴露 apply/rollback ──
# apply_update / rollback_update 是危险操作，保留 CLI 或后续独立确认端点。
@router.get("/easel/update/status")
async def easel_update_status():
    """返回 Easel 上游更新的状态与设置（读本地 JSON，无副作用）。"""
    try:
        from ....agent.easel_update import _settings_path, _state_path, _read_json

        state = _read_json(_state_path()) if _state_path().exists() else {}
        settings = _read_json(_settings_path()) if _settings_path().exists() else {}
        return {"data": {"state": state, "settings": settings}}
    except Exception as exc:  # noqa: BLE001
        return {"data": {"error": str(exc)}}


@router.post("/easel/update/check")
async def easel_update_check():
    """只读检查上游是否有更新：git fetch --depth 1 + 对比 SHA，不 modify 本地。

    `check_for_updates` 目前是同步函数（内部含 git subprocess），
    用 asyncio.to_thread 包一层避免阻塞事件循环；若后续改成 async 则直接 await。
    """
    try:
        from ....agent.easel_update import check_for_updates
        import inspect

        if inspect.iscoroutinefunction(check_for_updates):
            result = await check_for_updates()
        else:
            result = await asyncio.to_thread(check_for_updates)
        return {"data": result}
    except Exception as exc:  # noqa: BLE001
        return {"data": {"error": str(exc)}}


_agent_stream_lock = asyncio.Lock()
_agent_stop_event: Optional[asyncio.Event] = None
_agent_confirm_event: Optional[asyncio.Event] = None
_agent_confirm_approved: Optional[bool] = None

# Hermes 会话持久化（SSE 断线补偿）—— 参考 tools/easel-ref/app.py 的 SESSIONS_DIR/_turn_file 模式。
# 目录：<DATA_DIR>/ai-sessions/hermes/<session_id>/<turn_id>.jsonl
_SESSIONS_DIR = Path(os.getenv("LAOMA_SESSIONS_DIR") or str(paths.get_data_dir() / "ai-sessions" / "hermes"))


def _session_dir(session_id: str) -> Path:
    """规范化 session_id，创建并返回会话目录。"""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)[:128]
    if not safe:
        safe = uuid.uuid4().hex[:16]
    p = _SESSIONS_DIR / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def _append_turn_event(session_id: str, turn_id: str, event: Dict[str, Any]) -> None:
    """把一条 SSE 事件 append 到该 turn 的 JSONL 文件。失败仅记日志。"""
    try:
        d = _session_dir(session_id)
        safe_turn = "".join(c if c.isalnum() or c in "-_." else "_" for c in turn_id)[:64]
        f = d / f"{safe_turn}.jsonl"
        line = json.dumps({"ts": time.time(), "event": event}, ensure_ascii=False)
        with open(f, "a", encoding="utf-8") as fp:
            fp.write(line + "\n")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[HermesSession] append failed session={session_id} turn={turn_id}: {e}")


def _write_session_meta(session_id: str, turn_id: str, goal: str, context: Optional[Dict[str, Any]]) -> None:
    """更新会话元数据：把当前 turn 记为最新。"""
    try:
        d = _session_dir(session_id)
        meta = {"session_id": session_id, "current_turn": turn_id, "updated_at": time.time()}
        p = d / "meta.json"
        if p.exists():
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        meta.update({"session_id": session_id, "current_turn": turn_id, "updated_at": time.time()})
        p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        # turn 的 goal/context 首行
        safe_turn = "".join(c if c.isalnum() or c in "-_." else "_" for c in turn_id)[:64]
        turn_meta = d / f"{safe_turn}.meta.json"
        turn_meta.write_text(json.dumps({"goal": goal, "context": context or {}, "turn_id": turn_id, "created_at": time.time()}, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[HermesSession] meta write failed: {e}")


def _last_turn_file(session_id: str) -> Optional[Path]:
    """返回该会话最新的 turn jsonl 文件；无则 None。"""
    d = _session_dir(session_id)
    meta = d / "meta.json"
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            cur = data.get("current_turn")
            if cur:
                safe_turn = "".join(c if c.isalnum() or c in "-_." else "_" for c in cur)[:64]
                f = d / f"{safe_turn}.jsonl"
                if f.exists():
                    return f
        except Exception:
            pass
    # 回退：按 mtime 找最新
    files = [f for f in d.glob("*.jsonl") if f.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


class AgentRunRequest(BaseModel):
    goal: str = Field(..., description="自然语言目标描述")
    context: Optional[Union[Dict[str, Any], str, list]] = Field(None, description="额外上下文信息")


class AgentRunResponse(BaseModel):
    success: bool
    result: str
    steps: list = Field(default_factory=list)
    error: Optional[str] = None


class StreamAgentRequest(BaseModel):
    goal: str = Field(..., description="自然语言目标描述")
    context: Optional[Union[Dict[str, Any], str, list]] = Field(None, description="额外上下文信息")
    thread_id: Optional[str] = Field(None, description="线程 ID，当前仅用于接口兼容")
    require_confirmation: bool = Field(False, description="是否需要用户确认")


class AgentConfirmRequest(BaseModel):
    approved: bool = Field(..., description="用户是否同意执行")


def _normalize_agent_context(
    raw: Optional[Union[Dict[str, Any], str, list]]
) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return {"conversation": raw}
    return {"context": raw}


def _format_sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _run_agent_once(request: AgentRunRequest):
    from ....agent.hermes_agent import run_hermes_goal

    try:
        result = await run_hermes_goal(
            goal=request.goal,
            context=_normalize_agent_context(request.context),
        )
        return Response(success=True, data=AgentRunResponse(**result))
    except Exception as e:
        logger.error(f"[HermesRun] failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/hermes-run", response_model=Response[AgentRunResponse])
async def hermes_run(request: AgentRunRequest):
    return await _run_agent_once(request)


@router.post("/openclaw-run", response_model=Response[AgentRunResponse])
async def openclaw_run(request: AgentRunRequest):
    return await hermes_run(request)


async def hermes_stream_execution(
    goal: str,
    context: Optional[Union[Dict[str, Any], str, list]] = None,
    require_confirmation: bool = False,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """SSE 流式执行 Hermes Agent；每条事件同步 append 到 JSONL 供断线补偿。"""
    if not session_id:
        session_id = thread_id or f"sess-{uuid.uuid4().hex[:12]}"
    if not turn_id:
        turn_id = f"turn-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
    global _agent_stop_event, _agent_confirm_event, _agent_confirm_approved

    from ....agent.hermes_agent import run_hermes_goal

    _agent_stop_event = asyncio.Event()
    _agent_confirm_event = None
    _agent_confirm_approved = None

    normalized_context = _normalize_agent_context(context)
    _write_session_meta(session_id, turn_id, goal, normalized_context)

    async def emit(event: Dict[str, Any]) -> str:
        line = _format_sse(event)
        _append_turn_event(session_id, turn_id, event)
        return line

    async def on_event(event: Dict[str, Any], queue: "asyncio.Queue[Optional[Dict[str, Any]]]") -> None:
        mapped = event
        if event["type"] == "assistant_message":
            mapped = {"type": "thinking", "content": event.get("content", "")}
        elif event["type"] == "tool_call":
            mapped = {"type": "tool_call", "tool_name": event.get("tool_name"), "arguments": event.get("arguments")}
        elif event["type"] == "tool_result":
            mapped = {"type": "step_complete", "tool_name": event.get("tool_name"), "result": event.get("result")}
        await queue.put(mapped)

    try:
        async with _agent_stream_lock:
            queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()
            step_counter = 0

            yield await emit({
                "type": "init", "status": "starting",
                "session_id": session_id, "turn_id": turn_id,
                "message": "Hermes Agent 正在准备运行环境。",
            })
            yield await emit({
                "type": "plan",
                "plan": {"goal": goal, "context": normalized_context or {}, "mode": "hermes-agent"},
            })

            if require_confirmation:
                _agent_confirm_event = asyncio.Event()
                yield await emit({
                    "type": "confirmation_required",
                    "message": "请确认是否执行这个 Hermes Agent 任务。",
                    "task_summary": {"goal": goal, "context": normalized_context or {}},
                })
                wait_tasks = [asyncio.create_task(_agent_confirm_event.wait())]
                if _agent_stop_event:
                    wait_tasks.append(asyncio.create_task(_agent_stop_event.wait()))
                done, pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                for task in done:
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                if _agent_stop_event and _agent_stop_event.is_set():
                    yield await emit({"type": "error", "error": "Task stopped by user"})
                    yield await emit({"type": "done"})
                    return
                approved = bool(_agent_confirm_approved)
                yield await emit({"type": "confirmation_received", "approved": approved})
                if not approved:
                    yield await emit({"type": "error", "error": "Task rejected by user"})
                    yield await emit({"type": "done"})
                    return

            async def worker() -> None:
                try:
                    result = await run_hermes_goal(
                        goal=goal, context=normalized_context,
                        event_handler=lambda event: on_event(event, queue),
                        should_stop=lambda: bool(_agent_stop_event and _agent_stop_event.is_set()),
                    )
                    await queue.put({"type": "final_result", "result": result})
                except Exception as exc:
                    await queue.put({"type": "error", "error": str(exc)})
                finally:
                    await queue.put({"type": "done"})
                    await queue.put(None)

            task = asyncio.create_task(worker())

            while True:
                event = await queue.get()
                if event is None:
                    break
                if event.get("type") == "tool_call":
                    step_counter += 1
                    event["step"] = step_counter
                elif event.get("type") == "step_complete":
                    event["step"] = step_counter
                yield await emit(event)
                if event.get("type") == "done":
                    break

            await task
    except Exception as e:
        logger.error(f"[HermesStream] failed: {e}", exc_info=True)
        yield await emit({"type": "error", "error": str(e)})
    finally:
        _agent_stop_event = None
        _agent_confirm_event = None
        _agent_confirm_approved = None


@router.post("/hermes-stream")
async def hermes_stream(request: StreamAgentRequest):
    return StreamingResponse(
        hermes_stream_execution(
            request.goal, request.context,
            request.require_confirmation,
            request.thread_id,
            session_id=request.thread_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/hermes-stream/last/{session_id}")
async def hermes_stream_last(session_id: str):
    """SSE 断线补偿：重放该 session 最近一次 turn 的完整事件流。参照 tools/easel-ref/app.py:1112。"""
    f = _last_turn_file(session_id)
    if not f:
        return Response(success=True, data={"session_id": session_id, "turn_id": None, "events": [], "replay": True})
    events: List[Dict[str, Any]] = []
    ts_list: List[float] = []
    try:
        for raw in f.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                events.append(obj.get("event"))
                ts_list.append(obj.get("ts") or 0.0)
            except json.JSONDecodeError:
                continue
    except Exception as e:
        logger.error(f"[HermesLast] read failed: {e}")
        raise HTTPException(status_code=500, detail=f"读取会话失败：{e}")
    return Response(success=True, data={
        "session_id": session_id,
        "turn_id": f.stem,
        "events": events,
        "first_ts": ts_list[0] if ts_list else None,
        "last_ts": ts_list[-1] if ts_list else None,
        "replay": True,
    })


@router.post("/openclaw-stream")
async def openclaw_stream(request: StreamAgentRequest):
    return await hermes_stream(request)


@router.post("/hermes-stop")
async def hermes_stop():
    global _agent_stop_event
    if _agent_stop_event:
        _agent_stop_event.set()
        return Response(success=True, data={"message": "已发送 Hermes 停止信号。"})
    return Response(success=False, data={"message": "当前没有正在运行的 Hermes 任务。"})


@router.post("/openclaw-stop")
async def openclaw_stop():
    return await hermes_stop()


@router.post("/hermes-confirm")
async def hermes_confirm(request: AgentConfirmRequest):
    global _agent_confirm_event, _agent_confirm_approved
    if not _agent_confirm_event:
        return Response(success=False, data={"message": "当前没有待确认的 Hermes 任务。"})
    _agent_confirm_approved = bool(request.approved)
    _agent_confirm_event.set()
    return Response(success=True, data={"approved": _agent_confirm_approved})


@router.post("/openclaw-confirm")
async def openclaw_confirm(request: AgentConfirmRequest):
    return await hermes_confirm(request)


@router.post("/save-script", response_model=Response[SaveScriptResponse])
async def save_script(request: SaveScriptRequest):
    """
    淇濆瓨AI鐢熸垚鐨勮剼鏈?

    - 鏀寔JSON鍜孭ython鑴氭湰
    - 鑷姩鐢熸垚script_id
    - 钀界洏鍒皊torage/scripts鐩綍
    - 璁板綍鍒版暟鎹簱

    Args:
        request: 鑴氭湰鍐呭鍜屽厓鏁版嵁

    Returns:
        {script_id, path}
    """
    try:
        result = await agent_service.save_script(request)
        return Response(
            success=True,
            data=SaveScriptResponse(
                status="success",
                script_id=result['script_id'],
                path=result['path']
            )
        )
    except Exception as e:
        logger.error(f"Save script failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/execute-script", response_model=Response[ExecuteScriptResponse])
async def execute_script(request: ExecuteScriptRequest):
    """
    鎵ц鑴氭湰

    - execute妯″紡: 鐪熷疄鍒涘缓浠诲姟骞舵墽琛?
    - dry-run妯″紡: 浠呴獙璇佽鍒掍笉鎵ц

    Args:
        request: 鑴氭湰ID鍜屾墽琛岄€夐」

    Returns:
        {task_batch_id, tasks_created, estimated_time}
    """
    try:
        result = await agent_service.execute_script(
            script_id=request.script_id,
            mode=request.mode,
            options=request.options.dict() if request.options else {}
        )

        return Response(
            success=True,
            data=ExecuteScriptResponse(
                status="accepted",
                task_batch_id=result['task_batch_id'],
                tasks_created=result['tasks_created'],
                estimated_time=result['estimated_time']
            )
        )
    except ValueError as e:
        logger.error(f"Execute script failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Execute script failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/context", response_model=Response[SystemContext])
async def get_system_context():
    """
    鑾峰彇绯荤粺涓婁笅鏂?

    渚汚I浣跨敤,鍖呭惈:
    - 鎵€鏈夊彲鐢ㄨ处鍙蜂俊鎭?
    - 绱犳潗搴撹棰戝垪琛?
    - 宸插彂甯冨巻鍙?

    Returns:
        {accounts: [...], videos: [...]}
    """
    try:
        context = await agent_service.get_system_context()
        return Response(
            success=True,
            data=context
        )
    except Exception as e:
        logger.error(f"Get context failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/scripts")
async def list_scripts(skip: int = 0, limit: int = 20):
    """
    鑾峰彇鑴氭湰鍒楄〃

    Args:
        skip: 璺宠繃鏁伴噺
        limit: 闄愬埗鏁伴噺

    Returns:
        鑴氭湰鍒楄〃
    """
    try:
        import sqlite3
        from pathlib import Path

        db_path = Path(agent_service.db_path)

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT script_id, filename, script_type, plan_name,
                       description, generated_by, created_at, status
                FROM scripts
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, skip))

            scripts = [dict(row) for row in cursor.fetchall()]

            # 鑾峰彇鎬绘暟
            count_cursor = conn.execute("SELECT COUNT(*) FROM scripts")
            total = count_cursor.fetchone()[0]

        return Response(
            success=True,
            data={
                "total": total,
                "items": scripts
            }
        )
    except Exception as e:
        logger.error(f"List scripts failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/scripts/{script_id}")
async def get_script(script_id: str):
    """
    鑾峰彇鑴氭湰璇︽儏

    Args:
        script_id: 鑴氭湰ID

    Returns:
        鑴氭湰璇︾粏淇℃伅
    """
    try:
        import sqlite3
        from pathlib import Path

        db_path = Path(agent_service.db_path)

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM scripts WHERE script_id = ?",
                (script_id,)
            )
            script = cursor.fetchone()

            if not script:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Script not found: {script_id}"
                )

            return Response(
                success=True,
                data=dict(script)
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get script failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/executions")
async def list_executions(skip: int = 0, limit: int = 20):
    """
    鑾峰彇鎵ц鍘嗗彶

    Args:
        skip: 璺宠繃鏁伴噺
        limit: 闄愬埗鏁伴噺

    Returns:
        鎵ц鍘嗗彶鍒楄〃
    """
    try:
        import sqlite3
        from pathlib import Path

        db_path = Path(agent_service.db_path)

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT e.*, s.filename, s.plan_name
                FROM script_executions e
                LEFT JOIN scripts s ON e.script_id = s.script_id
                ORDER BY e.started_at DESC
                LIMIT ? OFFSET ?
            """, (limit, skip))

            executions = [dict(row) for row in cursor.fetchall()]

            # 鑾峰彇鎬绘暟
            count_cursor = conn.execute("SELECT COUNT(*) FROM script_executions")
            total = count_cursor.fetchone()[0]

        return Response(
            success=True,
            data={
                "total": total,
                "items": executions
            }
        )
    except Exception as e:
        logger.error(f"List executions failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
