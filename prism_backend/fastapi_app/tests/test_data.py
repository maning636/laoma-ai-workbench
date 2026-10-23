"""
Test data center endpoints

注意：这里测的都是**当前真实存在**的接口。
早期版本写的是 /api/v1/data/center、/api/v1/data/videos、/api/v1/data/trends、
/api/v1/data/publish-status —— 这四个接口从来没有被实现过（请求返回 404），
属于"照着一套没写的设计写的测试"，只能永远红着。已改挂到真实存在的数据类接口。
"""
from fastapi_app.main import app


def test_data_health(client):
    """Test data center health"""
    response = client.get("/api/v1/data/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


def test_data_collect_route_registered():
    """采集端点已注册。

    不真跑：/data/collect 会走 Playwright 抓各平台数据，需要真实 Cookie 与网络。
    """
    paths = app.openapi()["paths"]
    assert "/api/v1/data/collect" in paths
    assert "post" in paths["/api/v1/data/collect"]


def test_data_video_parse_requires_url(client):
    """视频解析必须带 url 查询参数"""
    response = client.get("/api/v1/data/video/parse")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(item["loc"][-1] == "url" for item in detail)


def test_data_center_summary(client):
    """数据汇总（洞察总览）"""
    response = client.get("/api/v1/insights/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total_insights" in data
    assert "total_plays" in data
    assert "total_likes" in data


def test_data_videos(client):
    """视频列表（分析面板）"""
    response = client.get("/api/v1/analytics/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["videos"], list)
    assert "totalVideos" in data["summary"]
    assert "totalPlays" in data["summary"]


def test_data_trends(client):
    """趋势曲线（分析面板图表数据）"""
    response = client.get("/api/v1/analytics/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["chartData"], list)


def test_publish_status(client):
    """发布状态统计"""
    response = client.get("/api/v1/publish/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    stats = data["data"]
    assert "total_published" in stats
    assert "pending_tasks" in stats
    assert "failed_tasks" in stats
