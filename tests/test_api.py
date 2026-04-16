"""
Tests for NyayaVoice backend
"""
import pytest
from fastapi.testclient import TestClient
from main import app
from backend.services import llm

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


def test_generate_response_answers_specific_question(monkeypatch):
    """Specific legal questions should get a targeted answer, not a generic prompt."""
    monkeypatch.setattr(llm, "search_legal_knowledge", lambda *args, **kwargs: [
        {
            "content": "You can file an FIR at any police station. This is called a Zero FIR. The police must transfer it to the correct station.",
            "category": "fir_process",
            "score": 0.82,
        },
        {
            "content": "You have the right to get a free copy of your FIR after it is registered.",
            "category": "fir_process",
            "score": 0.74,
        },
    ])
    monkeypatch.setattr(llm, "get_user_memory", lambda *args, **kwargs: [])
    monkeypatch.setattr(llm, "store_turn", lambda *args, **kwargs: None)

    result = llm.generate_response(
        user_id="test_user",
        user_message="How do I file an FIR?",
        conversation=[],
        language_code="en",
    )

    assert "nearest police station" in result["response"] or "any police station" in result["response"]
    assert "Please describe your issue in detail" not in result["response"]


def test_generate_response_fir_query_without_strong_search_still_answers(monkeypatch):
    """FIR queries should still get relevant guidance even if retrieval is weak."""
    monkeypatch.setattr(llm, "search_legal_knowledge", lambda *args, **kwargs: [])
    monkeypatch.setattr(llm, "get_user_memory", lambda *args, **kwargs: [])
    monkeypatch.setattr(llm, "store_turn", lambda *args, **kwargs: None)

    result = llm.generate_response(
        user_id="test_user",
        user_message="I need to report a fir where to go",
        conversation=[],
        language_code="en",
    )

    assert "nearest police station" in result["response"] or "zero fir" in result["response"].lower()
    assert "Please describe your issue in detail" not in result["response"]


def test_generate_response_legal_aid_without_search_uses_intent_fallback(monkeypatch):
    """Known intents should return relevant help even without retrieval context."""
    monkeypatch.setattr(llm, "search_legal_knowledge", lambda *args, **kwargs: [])
    monkeypatch.setattr(llm, "get_user_memory", lambda *args, **kwargs: [])
    monkeypatch.setattr(llm, "store_turn", lambda *args, **kwargs: None)

    result = llm.generate_response(
        user_id="test_user",
        user_message="How can I get free legal aid",
        conversation=[],
        language_code="en",
    )

    assert "15100" in result["response"] or "district legal services authority" in result["response"].lower()


def test_generate_response_retries_qdrant_with_intent_fallback(monkeypatch):
    """If the user query is weak, fallback Qdrant queries should still surface relevant knowledge."""
    def fake_search(query, **kwargs):
        if "report a fir where to go" in query.lower():
            return []
        if "zero fir" in query.lower() or "fir process" in query.lower():
            return [
                {
                    "content": "You can file an FIR at any police station. This is called a Zero FIR.",
                    "category": "fir_process",
                    "score": 0.79,
                }
            ]
        return []

    monkeypatch.setattr(llm, "search_legal_knowledge", fake_search)
    monkeypatch.setattr(llm, "get_user_memory", lambda *args, **kwargs: [])
    monkeypatch.setattr(llm, "store_turn", lambda *args, **kwargs: None)

    result = llm.generate_response(
        user_id="test_user",
        user_message="I need to report a fir where to go",
        conversation=[],
        language_code="en",
    )

    assert "zero fir" in result["response"].lower() or "any police station" in result["response"].lower()


def test_detect_intent_for_constitutional_rights():
    """Basic constitutional-rights questions should be recognized."""
    result = llm.detect_intent("What are my rights under Article 21 and Article 22?")
    assert result["intent"] == "constitutional_rights"


if __name__ == "__main__":
    pytest.main([__file__])
