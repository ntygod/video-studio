import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture()
def app(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        media_dir=tmp_path / "media",
        work_dir=tmp_path / "work",
    )
    return create_app(settings)


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def project(client):
    response = client.post(
        "/api/projects",
        json={
            "title": "任意创作项目",
            "project_type": "anything",
            "workflow_id": "freeform",
            "concept": "用户可以自由创作任意数量和类型的内容",
        },
    )
    assert response.status_code == 201
    return response.json()

