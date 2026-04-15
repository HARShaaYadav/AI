"""
Tests for NyayaVoice backend
"""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_check():
    """Test health endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "NyayaVoice API"}


def test_query_endpoint():
    """Test query endpoint with valid input"""
    payload = {
        "user_id": "test_user",
        "text": "I need help with a legal issue",
        "language": "en"
    }
    response = client.post("/api/query", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "intent" in data
    assert "language" in data
    assert "follow_up" in data
    assert "urgency" in data


def test_query_endpoint_empty_text():
    """Test query endpoint rejects empty text"""
    payload = {
        "user_id": "test_user",
        "text": "",
        "language": "en"
    }
    response = client.post("/api/query", json=payload)
    assert response.status_code == 422  # Pydantic validation error


def test_query_endpoint_long_text():
    """Test query endpoint rejects overly long text"""
    payload = {
        "user_id": "test_user",
        "text": "a" * 10001,  # Over 10k characters
        "language": "en"
    }
    response = client.post("/api/query", json=payload)
    assert response.status_code == 400


def test_config_endpoint():
    """Test config endpoint"""
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "vapi_public_key" in data
    assert "backend_url" in data


if __name__ == "__main__":
    pytest.main([__file__])