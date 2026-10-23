"""
Test other module endpoints

注意：/api/v1/campaigns/ping 与 /api/v1/ai/status 这两个接口从来没有被实现过
（请求返回 404），属于照着没写的设计写的测试。已改挂到真实存在的等价接口。
"""


def test_recovery_health(client):
    """Test recovery module health"""
    response = client.get("/api/v1/recovery/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["module"] == "recovery"


def test_scripts_list(client):
    """Test listing available scripts"""
    response = client.get("/api/v1/scripts/list")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "success"
    assert "scripts" in data
    assert isinstance(data["scripts"], list)


def test_campaigns_list(client):
    """计划列表（原来测的 /campaigns/ping 不存在）"""
    response = client.get("/api/v1/campaigns/list")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert isinstance(data["result"]["items"], list)


def test_tasks_health(client):
    """Test tasks health endpoint"""
    response = client.get("/api/v1/tasks/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "enabled" in data


def test_ai_model_configs(client):
    """AI 模型配置列表（原来测的 /ai/status 不存在）"""
    response = client.get("/api/v1/ai/model-configs")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert isinstance(data["data"], list)
