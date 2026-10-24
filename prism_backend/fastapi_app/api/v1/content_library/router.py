"""
原生内容库 API —— 直读 Easel outputs 磁盘（不经 Easel 服务器）。

- GET  /api/v1/content-library            产物树（缓存）
- POST /api/v1/content-library/refresh    强制重扫
- GET  /api/v1/content-library/file?path= 读取文本产物内容
- GET  /api/v1/content-library/media?path= 媒体文件流式输出（预览/下载）
- GET  /api/v1/content-library/preview?path= HTML 渲染（本地图 base64 内联，防公众号回源裂图）
- GET  /api/v1/content-library/ideas      选题库（_ideas.json）
- POST /api/v1/content-library/ideas      保存选题库
- GET  /api/v1/content-library/schedule   排期（_schedule.json）
- POST /api/v1/content-library/schedule   保存排期
- GET  /api/v1/content-library/accounts   各平台登录态
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse

from fastapi_app.core.logger import logger
from fastapi_app.services import easel_outputs as outputs_svc

router = APIRouter(prefix="/content-library", tags=["内容库"])


@router.get("")
async def list_outputs():
    try:
        return {"status": "success", "result": outputs_svc.list_outputs_cached()}
    except Exception as e:
        logger.error(f"内容库扫描失败: {e}")
        raise HTTPException(status_code=500, detail=f"内容库扫描失败: {e}")


@router.post("/refresh")
async def refresh_outputs():
    outputs_svc.get_outputs_cached()
    return {"status": "success", "result": outputs_svc.list_outputs_cached()}


@router.get("/file")
async def read_file(path: str = Query(...)):
    try:
        return {"status": "success", "result": {"path": path, "content": outputs_svc.read_output_text(path)}}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/media")
async def media(path: str = Query(...)):
    try:
        full = outputs_svc.open_output(path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(full, filename=full.name)


@router.get("/preview")
async def preview_html(path: str = Query(...)):
    """HTML 预览：本地图 base64 内联，防公众号回源裂图。参照 Easel v0.2.1。"""
    try:
        result = outputs_svc.preview_html(path)
        return {"status": "success", "result": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"HTML 预览失败: {e}")
        raise HTTPException(status_code=500, detail=f"HTML 预览失败：{e}")


@router.get("/ideas")
async def get_ideas():
    return {"status": "success", "result": {"ideas": outputs_svc.get_ideas()}}


@router.get("/ideas/from-performance")
async def get_ideas_from_performance(
    limit: Optional[int] = 10,
    platforms: Optional[str] = None,
):
    """L3-1：基于自有表现的选题建议。

    查询 video_analytics 按互动量（播放 + 点赞 + 评论×2 + 收藏×2）排序，
    取 top N 映射为「建议选题」条目：
      title  —— 表现最好素材的标题（去重后）
      reason —— 数据摘要（平台 · 播放 · 点赞 · 评论 · 收藏）
      heat   —— 互动量归一化（0-1，相对本次结果最大者）
      source —— 固定 "performance"

    空数据（video_analytics 表空 / 无有效互动）时返回
    `{suggestions: [], hint: "...", data_ready: false}`，不抛错——
    让前端可展示空态引导先去发布回收数据。
    """
    import sqlite3
    from fastapi_app.core.config import settings

    limit = max(1, min(int(limit or 10), 50))

    # 平台过滤：把逗号分隔字符串规范化
    platform_list: Optional[list[str]] = None
    if platforms and platforms.strip():
        platform_list = [p.strip() for p in platforms.split(",") if p.strip()]

    try:
        conn = sqlite3.connect(settings.DATABASE_PATH)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        # 评审 I1：DB 不可用属服务故障，不能用 200+status:error 掩盖——
        # 前端 ideas 区块只在 res.ok 判定后解析，非 2xx 会走 toast 分支，
        # 这里返回 HTTP 503 让语义清晰、告警链路可观测。
        logger.error(f"from-performance: 数据库连接失败 {e}")
        raise HTTPException(status_code=503, detail="选题数据暂不可用")

    try:
        # 构造平台过滤（NULL 安全的 IN 子句）
        ph = ""
        args: list = []
        if platform_list:
            qs = ",".join("?" for _ in platform_list)
            ph = f" AND platform IN ({qs})"
            args.extend(platform_list)

        # 互动量加权：播放 ×1，点赞 ×1，评论 ×2，收藏 ×2（评论/收藏更能代表话题热度）
        sql = (
            "SELECT title, platform, play_count, like_count, comment_count, "
            "collect_count, share_count, video_id, publish_date "
            "FROM video_analytics "
            "WHERE COALESCE(play_count, 0) + COALESCE(like_count, 0) "
            "      + COALESCE(comment_count, 0) + COALESCE(collect_count, 0) > 0"
            + ph +
            " ORDER BY (COALESCE(play_count, 0) + COALESCE(like_count, 0) "
            "          + COALESCE(comment_count, 0) * 2 + COALESCE(collect_count, 0) * 2) DESC "
            "LIMIT ?"
        )
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError as e:
        # 表不存在 / 缺列 —— 视为空数据（老库未跑过 bootstrap）
        conn.close()
        return {
            "status": "success",
            "result": {
                "suggestions": [],
                "data_ready": False,
                "hint": f"视频回收数据表尚未就绪（{type(e).__name__}），请先完成一次数据回收。",
            },
        }
    finally:
        conn.close()

    if not rows:
        return {
            "status": "success",
            "result": {
                "suggestions": [],
                "data_ready": False,
                "hint": "暂无视频回收数据。请先在发布中心完成一次发布并触发数据回收，再回来生成选题建议。",
            },
        }

    # 归一化热度：以本批最大互动量为基准 → 0-1
    def _score(r):
        return (
            (r["play_count"] or 0)
            + (r["like_count"] or 0)
            + (r["comment_count"] or 0) * 2
            + (r["collect_count"] or 0) * 2
        )

    max_score = max(_score(r) for r in rows) or 1

    # 去重：同 title 保留互动量最高的一条（SQL 已按热度降序，首见即最高）
    seen_titles: set[str] = set()
    suggestions = []
    for r in rows:
        title = (r["title"] or "").strip() or "未命名话题"
        if title in seen_titles:
            continue
        seen_titles.add(title)
        score = _score(r)
        heat = round(score / max_score, 3) if max_score else 0.0
        suggestions.append({
            "id": f"perf-{r['video_id']}",
            "title": title[:120],
            "note": (
                f"平台 {r['platform'] or '-'} · 播放 {r['play_count'] or 0} · "
                f"点赞 {r['like_count'] or 0} · 评论 {r['comment_count'] or 0} · "
                f"收藏 {r['collect_count'] or 0}"
            ),
            "source": "performance",
            "heat": heat,
            "platform": r["platform"] or "",
            "video_id": r["video_id"],
        })
        if len(suggestions) >= limit:
            break

    return {
        "status": "success",
        "result": {
            "suggestions": suggestions,
            "data_ready": True,
            "hint": None,
        },
    }


@router.post("/ideas")
async def save_ideas(ideas: List[Dict] = Body(default=[])):
    outputs_svc.save_ideas(ideas)
    return {"status": "success", "result": {"count": len(ideas)}}


@router.get("/schedule")
async def get_schedule():
    return {"status": "success", "result": {"schedule": outputs_svc.get_schedule()}}


@router.post("/schedule")
async def save_schedule(schedule: List[Dict] = Body(default=[])):
    outputs_svc.save_schedule(schedule)
    return {"status": "success", "result": {"count": len(schedule)}}


@router.get("/accounts")
async def get_login_status():
    return {"status": "success", "result": {"accounts": outputs_svc.get_login_status()}}
