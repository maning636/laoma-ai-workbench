"""
热点话题抓取服务
━━━━━━━━━━━━━━━━
支持 5 个平台：微博热搜 / 知乎热榜 / 抖音热点 / 今日头条 / 小红书热榜
统一接口: fetch_hot_topics(platform) -> List[dict]

数据来源为各平台公开热榜接口，直连（trust_env=False，不走 GitHub 代理）。
- 微博：weibo.com/ajax/side/hotSearch → data.realtime（真实热搜，52 条）
- 头条：toutiao.com/hot-event/hot-board → data[].Title/HotValue
- 抖音：iesdouyin.com/aweme/v1/hot/search/list → data.word_list（word/hot_value）
- 知乎：公共 API 已锁（403/404），需登录 cookie 或浏览器抓取——诚实兜底
- 小红书：需浏览器抓取——诚实兜底
"""

from __future__ import annotations
import os, json, time, re
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path
from loguru import logger

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_FILE = _DATA_DIR / "hot_topics_cache.json"
CACHE_TTL = 1800

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _client(timeout: int = 15):
    """httpx 直连客户端：trust_env=False 走系统直连，不套 GitHub 代理（国内热榜站点直连可达）。"""
    import httpx
    return httpx.AsyncClient(timeout=timeout, trust_env=False)


def _parse_heat(note: str) -> float:
    """从 '2.5亿' / '1234万' / '12345' 这类热度文案提数值。"""
    if not note:
        return 0.0
    m = re.search(r"([\d.]+)\s*亿", note)
    if m:
        return float(m.group(1)) * 1_0000_0000
    m = re.search(r"([\d.]+)\s*万", note)
    if m:
        return float(m.group(1)) * 1_0000
    m = re.search(r"([\d.]+)", note)
    return float(m.group(1)) if m else 0.0


# ============================================================
# 微博热搜（公开榜单）
# ============================================================
async def _fetch_weibo_hot() -> List[Dict[str, Any]]:
    try:
        async with _client() as client:
            resp = await client.get(
                "https://weibo.com/ajax/side/hotSearch",
                headers={"User-Agent": _UA, "Referer": "https://weibo.com/"},
            )
            if resp.status_code != 200:
                return _weibo_fallback()
            data = resp.json().get("data", {})
            # realtime = 实时热搜（真实热榜，~52 条），hotgovs = 政务置顶
            items = data.get("realtime", []) or data.get("hotgovs", [])
            results = []
            for idx, item in enumerate(items):
                word = item.get("word", "") or item.get("note", "")
                if not word:
                    continue
                note = item.get("note", "") or item.get("label_name", "")
                results.append({
                    "title": word,
                    "heat_score": _parse_heat(note),
                    "rank": idx + 1,
                    "source": "weibo",
                    "platform": "微博",
                    "url": f"https://s.weibo.com/weibo?q={word}",
                    "note": note or None,
                    "fetched_at": _now(),
                })
            return results[:50] or _weibo_fallback()
    except Exception as e:
        logger.warning(f"微博热搜抓取失败: {e}")
        return _weibo_fallback()


def _weibo_fallback() -> List[Dict[str, Any]]:
    return [{
        "title": "（微博热搜暂不可用）", "heat_score": 0, "rank": 0,
        "source": "weibo", "platform": "微博", "fetched_at": _now(),
        "note": "weibo.com/ajax/side/hotSearch 抓取失败，稍后重试",
    }]


# ============================================================
# 今日头条热榜
# ============================================================
async def _fetch_toutiao_hot() -> List[Dict[str, Any]]:
    try:
        async with _client() as client:
            resp = await client.get(
                "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
                headers={"User-Agent": _UA, "Referer": "https://www.toutiao.com/"},
            )
            if resp.status_code != 200:
                return _toutiao_fallback()
            data = resp.json().get("data", [])
            results = []
            for idx, item in enumerate(data):
                title = item.get("Title", "")
                if not title:
                    continue
                results.append({
                    "title": title,
                    "heat_score": float(item.get("HotValue", 0) or 0),
                    "rank": idx + 1,
                    "source": "toutiao",
                    "platform": "今日头条",
                    "url": item.get("Url", ""),
                    "image": item.get("LabelUrl", ""),
                    "fetched_at": _now(),
                })
            return results[:50] or _toutiao_fallback()
    except Exception as e:
        logger.warning(f"今日头条抓取失败: {e}")
        return _toutiao_fallback()


def _toutiao_fallback() -> List[Dict[str, Any]]:
    return [{
        "title": "（今日头条热榜暂不可用）", "heat_score": 0, "rank": 0,
        "source": "toutiao", "platform": "今日头条", "fetched_at": _now(),
        "note": "toutiao hot-board 抓取失败，稍后重试",
    }]


# ============================================================
# 抖音热榜
# ============================================================
async def _fetch_douyin_hot() -> List[Dict[str, Any]]:
    try:
        async with _client() as client:
            resp = await client.get(
                "https://www.iesdouyin.com/aweme/v1/hot/search/list/",
                headers={"User-Agent": _UA},
            )
            if resp.status_code != 200:
                return _douyin_fallback()
            data = resp.json().get("data", {})
            items = data.get("word_list", [])
            results = []
            for idx, item in enumerate(items):
                word = item.get("word", "")
                if not word:
                    continue
                results.append({
                    "title": word,
                    "heat_score": float(item.get("hot_value", 0) or 0),
                    "rank": idx + 1,
                    "source": "douyin",
                    "platform": "抖音",
                    "image": (item.get("word_cover", {}) or {}).get("url_list", [None])[0],
                    "fetched_at": _now(),
                })
            return results[:50] or _douyin_fallback()
    except Exception as e:
        logger.warning(f"抖音热榜抓取失败: {e}")
        return _douyin_fallback()


def _douyin_fallback() -> List[Dict[str, Any]]:
    return [{
        "title": "（抖音热榜暂不可用）", "heat_score": 0, "rank": 0,
        "source": "douyin", "platform": "抖音", "fetched_at": _now(),
        "note": "iesdouyin.com 抓取失败，稍后重试",
    }]


# ============================================================
# 知乎热榜（公共 API 已锁，需 cookie / 浏览器抓取）
# ============================================================
async def _fetch_zhihu_hot() -> List[Dict[str, Any]]:
    # 知乎公共热榜 API 已全部 403/404（需登录态）。留诚实兜底，指明下一步。
    return [{
        "title": "（知乎热榜需登录 cookie 或浏览器抓取）", "heat_score": 0, "rank": 0,
        "source": "zhihu", "platform": "知乎", "fetched_at": _now(),
        "note": "公共 API 已锁（403/404）。在 老马AI工作台配置知乎登录 cookie 走 api/v4/topstory/hot-lists，或用 mediacrawler 浏览器抓取 https://www.zhihu.com/hot",
    }]


# ============================================================
# 小红书热榜（需浏览器抓取）
# ============================================================
async def _fetch_xiaohongshu_hot() -> List[Dict[str, Any]]:
    return [{
        "title": "（小红书热榜需浏览器抓取）", "heat_score": 0, "rank": 0,
        "source": "xiaohongshu", "platform": "小红书", "fetched_at": _now(),
        "note": "小红书接口签名复杂，需用 mediacrawler 浏览器抓取热榜页",
    }]


# ============================================================
# 统一入口
# ============================================================
_PLATFORM_HANDLERS = {
    "weibo": _fetch_weibo_hot,
    "zhihu": _fetch_zhihu_hot,
    "toutiao": _fetch_toutiao_hot,
    "douyin": _fetch_douyin_hot,
    "xiaohongshu": _fetch_xiaohongshu_hot,
}

_PLATFORM_LABELS = {
    "weibo": "微博", "zhihu": "知乎", "toutiao": "今日头条",
    "douyin": "抖音", "xiaohongshu": "小红书",
}


async def fetch_hot_topics(platform: str) -> List[Dict[str, Any]]:
    handler = _PLATFORM_HANDLERS.get(platform)
    if handler:
        return await handler()
    return [{"error": f"未知平台: {platform}"}]


async def fetch_all_hot_topics() -> Dict[str, List[Dict[str, Any]]]:
    import asyncio
    tasks = [fetch_hot_topics(pid) for pid in _PLATFORM_HANDLERS]
    results = await asyncio.gather(*tasks)
    return {pid: items for pid, items in zip(_PLATFORM_HANDLERS.keys(), results)}


def list_platforms() -> List[Dict[str, Any]]:
    return [{"id": pid, "name": label, "label": label}
            for pid, label in _PLATFORM_LABELS.items()]


# ============================================================
# 缓存
# ============================================================
async def fetch_with_cache(platform: str) -> Dict[str, Any]:
    cache = _load_cache()
    ts = cache.get(platform, {}).get("ts", 0)
    topics = cache.get(platform, {}).get("topics", [])
    if topics and time.time() - ts < CACHE_TTL:
        return {"platform": platform, "topics": topics, "from_cache": True, "fetched_at": topics[0].get("fetched_at") if topics else ""}

    topics = await fetch_hot_topics(platform)
    _save_cache_item(platform, topics)
    return {"platform": platform, "topics": topics, "from_cache": False, "fetched_at": _now()}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_cache() -> Dict[str, Any]:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache_item(platform: str, topics: List[Dict[str, Any]]) -> None:
    cache = _load_cache()
    cache[platform] = {"ts": time.time(), "topics": topics}
    _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
