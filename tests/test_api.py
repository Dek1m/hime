"""Tests for API endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
from hime.api.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestServicesCRUD:
    async def test_create_service(self, client):
        resp = await client.post("/services", json={
            "name": "test_service",
            "url": "https://httpbin.org/ip",
            "method": "GET",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test_service"
        assert data["url"] == "https://httpbin.org/ip"
        assert "uuid" in data

    async def test_list_services(self, client):
        # Create one first
        await client.post("/services", json={
            "name": "list_test",
            "url": "https://example.com",
        })
        resp = await client.get("/services")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_get_service(self, client):
        # Create
        create_resp = await client.post("/services", json={
            "name": "get_test",
            "url": "https://example.com",
        })
        uuid = create_resp.json()["uuid"]

        # Get
        resp = await client.get(f"/services/{uuid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "get_test"

    async def test_update_service(self, client):
        # Create
        create_resp = await client.post("/services", json={
            "name": "update_test",
            "url": "https://example.com",
        })
        uuid = create_resp.json()["uuid"]

        # Update
        resp = await client.patch(f"/services/{uuid}", json={"timeout": 30.0})
        assert resp.status_code == 200
        assert resp.json()["timeout"] == 30.0

    async def test_delete_service(self, client):
        # Create
        create_resp = await client.post("/services", json={
            "name": "delete_test",
            "url": "https://example.com",
        })
        uuid = create_resp.json()["uuid"]

        # Delete
        resp = await client.delete(f"/services/{uuid}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # Verify deleted
        resp = await client.get(f"/services/{uuid}")
        assert resp.status_code == 404

    async def test_duplicate_name(self, client):
        await client.post("/services", json={
            "name": "dup_test",
            "url": "https://example.com",
        })
        resp = await client.post("/services", json={
            "name": "dup_test",
            "url": "https://other.com",
        })
        assert resp.status_code == 409

    async def test_not_found(self, client):
        resp = await client.get("/services/nonexistent")
        assert resp.status_code == 404
