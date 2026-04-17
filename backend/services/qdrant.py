import os
import ssl
import time
import uuid
import logging
import hashlib
import math

# Disable SSL verification for corporate proxy environments
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

import requests
_orig_request = requests.Session.request
def _patched_request(self, *args, **kwargs):
    kwargs["verify"] = False
    return _orig_request(self, *args, **kwargs)
requests.Session.request = _patched_request

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from fastembed import TextEmbedding
    FASTEMBED_AVAILABLE = True
except ImportError:
    FASTEMBED_AVAILABLE = False

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
)
from qdrant_client.http.models import PayloadSchemaType

from backend.config import (
    QDRANT_URL, QDRANT_API_KEY,
    LEGAL_COLLECTION, MEMORY_COLLECTION,
    EMBEDDING_MODEL, VECTOR_SIZE, USE_MEMORY_QDRANT,
)

logger = logging.getLogger(__name__)

embedding_model = None

_embedding_init_done = False
_embedding_lock = None

def _init_embedding_model():
    global embedding_model
    if FASTEMBED_AVAILABLE:
        try:
            logger.info(f"Loading embedding model: {EMBEDDING_MODEL} (may take a moment on first run)...")
            embedding_model = TextEmbedding(EMBEDDING_MODEL)
            logger.info("FastEmbed model ready.")
            return
        except Exception as e:
            logger.warning(f"FastEmbed model failed to load: {e}. Using hash-based fallback.")

    logger.info("Using built-in hash-based embeddings (no download needed).")
    embedding_model = None

# Initialize lazily on first embed() call to avoid blocking Railway startup health check

if USE_MEMORY_QDRANT:
    logger.info("Using in-memory Qdrant (no Docker/server needed)")
    qdrant = QdrantClient(location=":memory:")
else:
    qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


def ensure_collections(retries: int = 5, delay: float = 2.0):
    for attempt in range(retries):
        try:
            existing = [c.name for c in qdrant.get_collections().collections]
            if LEGAL_COLLECTION not in existing:
                qdrant.create_collection(
                    collection_name=LEGAL_COLLECTION,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                logger.info(f"Created collection: {LEGAL_COLLECTION}")
            if MEMORY_COLLECTION not in existing:
                qdrant.create_collection(
                    collection_name=MEMORY_COLLECTION,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                logger.info(f"Created collection: {MEMORY_COLLECTION}")
            _ensure_memory_indexes()
            return
        except Exception as e:
            logger.warning(f"Qdrant not ready (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    logger.error("Could not connect to Qdrant after retries.")


def _ensure_memory_indexes():
    """Ensure payload indexes used by filtered memory retrieval exist."""
    try:
        info = qdrant.get_collection(MEMORY_COLLECTION)
        payload_schema = getattr(info, "payload_schema", {}) or {}
        if "user_id" in payload_schema:
            return

        qdrant.create_payload_index(
            collection_name=MEMORY_COLLECTION,
            field_name="user_id",
            field_schema=PayloadSchemaType.KEYWORD,
            wait=True,
        )
        logger.info("Created payload index for user_memory.user_id")
    except Exception as e:
        logger.warning(f"Could not ensure payload index for user_memory.user_id: {e}")


def embed(text: str) -> list:
    """Generate embedding vector — uses FastEmbed if available, else hash-based fallback."""
    if embedding_model is not None:
        vectors = list(embedding_model.embed([text[:2000]]))
        return vectors[0].tolist()
    return _hash_embed(text)


def _hash_embed(text: str) -> list:
    """Deterministic hash-based embedding — works offline, no model download needed."""
    text = text.lower().strip()
    words = text.split()
    vector = [0.0] * VECTOR_SIZE

    for i, word in enumerate(words):
        h = hashlib.md5(word.encode()).hexdigest()
        for j in range(0, len(h), 2):
            idx = int(h[j:j+2], 16) % VECTOR_SIZE
            vector[idx] += 1.0 / (1 + i * 0.1)

    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def search_legal_knowledge(query: str, top_k: int = 4) -> list:
    try:
        vector = embed(query)
        results = qdrant.search(
            collection_name=LEGAL_COLLECTION,
            query_vector=vector,
            limit=top_k,
            with_payload=True,
        )
        return [
            {
                "content": r.payload.get("content", ""),
                "category": r.payload.get("category", ""),
                "score": round(r.score, 3),
            }
            for r in results
        ]
    except Exception as e:
        logger.error(f"Legal knowledge search failed: {e}")
        return []


def get_user_memory(user_id: str, top_k: int = 3) -> list:
    try:
        results, _ = _scroll_user_memory(user_id, limit=20)
        results.sort(key=lambda r: r.payload.get("timestamp", 0), reverse=True)
        return [
            {
                "summary": r.payload.get("summary", ""),
                "case_type": r.payload.get("case_type", ""),
                "timestamp": r.payload.get("timestamp", 0),
                "status": r.payload.get("status", "open"),
            }
            for r in results[:top_k]
        ]
    except Exception as e:
        if "Index required but not found" in str(e) and "user_id" in str(e):
            logger.warning("user_memory.user_id index missing during retrieval; creating it now and retrying once.")
            try:
                _ensure_memory_indexes()
                results, _ = _scroll_user_memory(user_id, limit=20)
                results.sort(key=lambda r: r.payload.get("timestamp", 0), reverse=True)
                return [
                    {
                        "summary": r.payload.get("summary", ""),
                        "case_type": r.payload.get("case_type", ""),
                        "timestamp": r.payload.get("timestamp", 0),
                        "status": r.payload.get("status", "open"),
                    }
                    for r in results[:top_k]
                ]
            except Exception as retry_error:
                logger.error(f"User memory retrieval retry failed after creating index: {retry_error}")
        logger.error(f"User memory retrieval failed: {e}")
        return []


def _scroll_user_memory(user_id: str, limit: int = 20):
    return qdrant.scroll(
        collection_name=MEMORY_COLLECTION,
        scroll_filter=Filter(
            must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
        ),
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )


def store_conversation(user_id: str, conversation: list, case_type: str = "general"):
    try:
        if not conversation:
            return
        summary_text = " | ".join(
            f"{m['role']}: {m['text']}" for m in conversation[-8:]
        )
        vector = embed(summary_text)
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "user_id": user_id,
                "summary": summary_text,
                "case_type": case_type,
                "timestamp": int(time.time()),
                "status": "open",
            },
        )
        qdrant.upsert(collection_name=MEMORY_COLLECTION, points=[point])
    except Exception as e:
        logger.error(f"Store conversation failed: {e}")


def seed_legal_document(content: str, category: str, language: str = "en"):
    vector = embed(content)
    point = PointStruct(
        id=str(uuid.uuid4()),
        vector=vector,
        payload={
            "content": content,
            "category": category,
            "language": language,
        },
    )
    qdrant.upsert(collection_name=LEGAL_COLLECTION, points=[point])
