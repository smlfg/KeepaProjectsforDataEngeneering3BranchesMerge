#!/usr/bin/env python3
"""
Integration tests for DealFinder Filter API
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.data.database import AsyncSessionLocal, close_async_engine


BASE_URL = "http://localhost:8000"


@pytest.mark.skip(reason="requires running FastAPI server and app import")
class TestFilterAPI:
    """Test suite for Filter Management API"""

    @pytest.fixture(scope="class")
    async def client(self):
        """Create async test client"""
        async with httpx.AsyncClient(app=app, base_url=BASE_URL) as client:
            yield client

    @pytest.fixture(scope="class")
    async def user_id(self):
        """Get or create demo user ID"""
        async with AsyncSessionLocal() as session:
            from src.data.entities import User
            from sqlalchemy import select

            result = await session.execute(
                select(User).where(User.email == "demo@dealfinder.app")
            )
            user = result.scalar_one_or_none()

            if not user:
                user = User(email="demo@dealfinder.app")
                session.add(user)
                await session.commit()
                await session.refresh(user)

            return str(user.id)

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Test health check endpoint"""
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_create_filter(self, client, user_id):
        """Test filter creation"""
        filter_data = {
            "name": "Electronics Deals",
            "categories": ["16142011", "16142012"],
            "min_price": 50,
            "max_price": 500,
            "min_discount": 20,
            "max_discount": 70,
            "min_rating": 4.0,
            "min_review_count": 10,
            "max_sales_rank": 50000,
            "email_enabled": True,
            "email_time": "06:00",
        }

        response = await client.post(
            "/api/v1/filters", json=filter_data, headers={"X-User-ID": user_id}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "created"
        assert "id" in data
        assert data["message"] == "Filter created successfully!"

        return data["id"]

    @pytest.mark.asyncio
    async def test_list_filters(self, client, user_id):
        """Test filter listing"""
        response = await client.get("/api/v1/filters", headers={"X-User-ID": user_id})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_get_filter(self, client, user_id):
        """Test single filter retrieval"""
        # First get list to get an ID
        list_response = await client.get(
            "/api/v1/filters", headers={"X-User-ID": user_id}
        )
        filters = list_response.json()

        if filters:
            filter_id = filters[0]["id"]

            response = await client.get(
                f"/api/v1/filters/{filter_id}", headers={"X-User-ID": user_id}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == filter_id
            assert "name" in data
            assert "categories" in data

    @pytest.mark.asyncio
    async def test_update_filter(self, client, user_id):
        """Test filter update"""
        # Get first filter
        list_response = await client.get(
            "/api/v1/filters", headers={"X-User-ID": user_id}
        )
        filters = list_response.json()

        if filters:
            filter_id = filters[0]["id"]

            response = await client.patch(
                f"/api/v1/filters/{filter_id}",
                json={"name": "Updated Filter Name", "email_enabled": False},
                headers={"X-User-ID": user_id},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "updated"

    @pytest.mark.asyncio
    async def test_deactivate_filter(self, client, user_id):
        """Test filter deactivation"""
        # Create a new filter to deactivate
        create_response = await client.post(
            "/api/v1/filters",
            json={
                "name": "To Deactivate",
                "categories": ["16142011"],
                "min_price": 0,
                "max_price": 1000,
                "min_discount": 10,
                "max_discount": 50,
                "min_rating": 3.5,
                "min_review_count": 5,
                "max_sales_rank": 100000,
            },
            headers={"X-User-ID": user_id},
        )

        filter_id = create_response.json()["id"]

        # Deactivate
        response = await client.delete(
            f"/api/v1/filters/{filter_id}?hard_delete=false",
            headers={"X-User-ID": user_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "deactivated" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        """Test root endpoint"""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "DealFinder API"


async def run_tests():
    """Run all tests"""
    print("=" * 60)
    print("🧪 Running DealFinder API Integration Tests")
    print("=" * 60)

    import subprocess

    result = subprocess.run(
        ["pytest", "test_api.py", "-v", "--tb=short"],
        cwd=Path(__file__).parent,
        capture_output=False,
    )

    return result.returncode == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
