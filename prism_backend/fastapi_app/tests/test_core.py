"""
Test system core endpoints
"""
import pytest

from fastapi_app.core import settings


def test_root_endpoint(client):
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "version" in data
    assert data["version"] == "2.0.0"


def test_health_check(client):
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "2.0.0"
    assert "timestamp" in data


def test_api_ping(client):
    """Test ping endpoint"""
    response = client.get("/api/v1/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "pong"


def test_openapi_spec(client):
    """Test OpenAPI specification"""
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "info" in data
    # 标题/版本来自 settings（.env 可覆盖），不要硬编码字面量。
    # 之前这里硬编码 "老马AI工作台 API"，但那个值全仓从未被设置过
    # （core/config.py 的默认值是 "Prism"，.env.example 里也是注释掉的），
    # 于是 CI（无 .env）必然 assert 'Prism' == '老马AI工作台 API' 失败。
    # 改成对着真值断言：既能验证 main.py 把配置正确接进了 FastAPI(title=...)，
    # 又不会因为部署环境的 .env 差异而误报。
    assert data["info"]["title"] == settings.PROJECT_NAME
    assert data["info"]["version"] == settings.VERSION
    assert "paths" in data
    # Check that we have a reasonable number of endpoints
    assert len(data["paths"]) > 50


def test_docs_endpoint(client):
    """Test Swagger UI docs endpoint"""
    response = client.get("/api/docs")
    assert response.status_code == 200
    assert b"swagger-ui" in response.content.lower()


def test_redoc_endpoint(client):
    """Test ReDoc endpoint"""
    response = client.get("/api/redoc")
    assert response.status_code == 200
    assert b"redoc" in response.content.lower()
