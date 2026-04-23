import logging
import os
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Dict, Any

from backend.routes.query import router as query_router
from backend.routes.document import router as document_router
from backend.routes.memory import router as memory_router
from backend.routes.predictor import router as predictor_router
from backend.services.qdrant import ensure_collections, seed_legal_document
from backend.config import BACKEND_URL, PRIMARY_LLM_MODEL, VAPI_API_KEY, VAPI_PUBLIC_KEY
from backend.prompts import get_language_name, get_shared_system_prompt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
DOCS_DIR = os.path.join(BASE_DIR, "generated_docs")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
os.makedirs(DOCS_DIR, exist_ok=True)

app = FastAPI(
    title="NyayaVoice API",
    description="Voice-first multilingual legal aid assistant — powered by Vapi + Qdrant",
    version="2.0.0",
    docs_url="/api-docs",
    redoc_url="/api-redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files — accessible at /static/styles.css, /static/app.js, etc.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
# Mount generated docs at /generated-docs (avoid conflict with FastAPI's /docs Swagger UI)
# Only mount if the directory has files to prevent StaticFiles RuntimeError on empty dir
if os.listdir(DOCS_DIR):
    app.mount("/generated-docs", StaticFiles(directory=DOCS_DIR), name="generated-docs")

# Include routers
app.include_router(query_router, prefix="/api", tags=["Query"])
app.include_router(document_router, prefix="/api", tags=["Document"])
app.include_router(memory_router, prefix="/api", tags=["Memory"])
app.include_router(predictor_router, prefix="/api", tags=["Predictor"])


@app.on_event("startup")
async def startup():
    logger.info("Starting NyayaVoice API...")
    ensure_collections()
    logger.info("Qdrant collections ready.")
    # Run seeding in background to avoid blocking startup
    asyncio.create_task(_auto_seed_if_empty())


async def _auto_seed_if_empty():
    from backend.services.qdrant import qdrant
    from backend.config import LEGAL_COLLECTION
    try:
        # Give server a moment to fully start
        await asyncio.sleep(1)
        info = qdrant.get_collection(LEGAL_COLLECTION)
        if info.points_count == 0:
            logger.info("Legal knowledge base is empty — seeding now...")
            try:
                from backend.scripts.seed_legal_data import LEGAL_DATA
                for item in LEGAL_DATA:
                    seed_legal_document(
                        content=item["content"],
                        category=item["category"],
                        language="en",
                    )
                logger.info(f"Seeded {len(LEGAL_DATA)} legal knowledge entries.")
            except ImportError:
                logger.info("Seed data not available — skipping auto-seed.")
        else:
            logger.info(f"Legal knowledge base already populated ({info.points_count} documents).")
    except Exception as e:
        logger.warning(f"Background seeding failed: {e}")


@app.get("/health")
async def health():
    print("Health check requested")
    return {"status": "ok", "service": "NyayaVoice API"}


@app.get("/api/config")
async def get_config():
    print("Config requested")
    return {
        "vapi_public_key": VAPI_PUBLIC_KEY,
        "backend_url": BACKEND_URL,
    }


@app.get("/docs/{filename}")
async def legacy_serve_document(filename: str):
    filename = os.path.basename(filename)
    filepath = os.path.join(DOCS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(filepath, media_type="application/pdf", filename=filename)


@app.post("/vapi-webhook")
async def vapi_webhook(request: Request):
    """
    Vapi webhook — handles voice call events.
    Vapi runs the LLM on its own; we provide RAG context + document generation.
    """
    from backend.services.qdrant import search_legal_knowledge, store_conversation

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    message = payload.get("message", {})
    msg_type = message.get("type", "")
    logger.info(f"Vapi webhook received: type={msg_type}")

    def _tool_result_response(result_text: str) -> JSONResponse:
        tool_call_id = (
            message.get("toolCallId")
            or message.get("tool_call_id")
            or message.get("call", {}).get("toolCallId")
            or message.get("functionCall", {}).get("toolCallId")
            or message.get("functionCall", {}).get("id")
            or payload.get("toolCallId")
        )
        if tool_call_id:
            return JSONResponse({
                "results": [
                    {
                        "toolCallId": tool_call_id,
                        "result": result_text,
                    }
                ]
            })
        return JSONResponse({"result": result_text})

    # 1. Assistant request — return assistant config
    if msg_type == "assistant-request":
        call = message.get("call", {})
        metadata = call.get("metadata", {})
        language = metadata.get("language", "en")
        session_mode = metadata.get("mode", "voice")

        is_chat_mode = session_mode == "chat"

        target_language = get_language_name(language)
        logger.info(
            "Vapi assistant-request: session_mode=%s language=%s model_provider=%s model=%s voice_provider=%s transcriber=%s",
            session_mode,
            language,
            "openai",
            PRIMARY_LLM_MODEL,
            "azure",
            "deepgram",
        )

        return JSONResponse({
            "assistant": {
                "firstMessage": None if is_chat_mode else _get_greeting(language),
                "firstMessageMode": "assistant-waits-for-user" if is_chat_mode else "assistant-speaks-first",
                "model": {
                    "provider": "openai",
                    "model": PRIMARY_LLM_MODEL,
                    "systemPrompt": (
                        get_shared_system_prompt(language)
                        + " "
                        + f"For this session, the active response language is {target_language}. "
                        + f"Always restate tool results in {target_language} instead of copying them verbatim."
                    ),
                    "functions": [
                        {
                            "name": "query_legal",
                            "description": "Query the legal knowledge base for relevant legal information. Use this before answering legal questions unless the answer is only a greeting or emergency numbers. After receiving the result, answer in the active session language and do not copy English text directly.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string", "description": "User's legal question"},
                                },
                                "required": ["text"],
                            },
                        },
                        {
                            "name": "generate_document",
                            "description": "Generate a legal document (FIR, complaint) from collected details.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "doc_type": {"type": "string"},
                                    "details": {"type": "object"},
                                },
                                "required": ["doc_type", "details"],
                            },
                        },
                    ],
                },
                "voice": {"provider": "azure", "voiceId": "multilingual-auto"},
                "transcriber": {
                    "provider": "deepgram",
                    "model": "nova-2",
                    "language": "multi",
                },
            }
        })

    # 2. Function call — search Qdrant or generate document
    if msg_type == "function-call":
        fn = message.get("functionCall", {})
        fn_name = fn.get("name", "")
        params = fn.get("parameters", {})
        metadata = message.get("call", {}).get("metadata", {})
        logger.info(
            "Vapi function-call: session_mode=%s function=%s language=%s",
            metadata.get("mode", "voice"),
            fn_name,
            metadata.get("language", "en"),
        )

        if fn_name == "query_legal":
            from backend.services.llm import (
                _filter_results_for_intent,
                detect_intent,
                get_retrieval_candidates,
            )
            text = params.get("text", "")
            if not text:
                return _tool_result_response("Please tell me your problem.")

            language = metadata.get("language", "en")
            intent = detect_intent(text).get("intent", "general_legal_query")
            merged = {}
            for candidate in get_retrieval_candidates(text, intent):
                for result in search_legal_knowledge(candidate, top_k=4):
                    key = (result.get("category", ""), result.get("content", ""))
                    existing = merged.get(key)
                    if not existing or result.get("score", 0) > existing.get("score", 0):
                        merged[key] = result

            all_results = sorted(merged.values(), key=lambda item: item.get("score", 0), reverse=True)
            filtered_results = _filter_results_for_intent(all_results, intent)
            strong_filtered = [r for r in filtered_results if r.get("score", 0) > 0.2]
            results = (strong_filtered or filtered_results or all_results)[:4]
            if results:
                topic_lines = "\n\n".join(
                    f"- [{r['category'].replace('_', ' ').title()}] {r['content']}"
                    for r in results if r["score"] > 0.2
                )
                context = "\n\n".join(
                    [
                        f"Active language: {get_language_name(language)}.",
                        "Facts from the legal knowledge base are below.",
                        "Use these facts, but write the final answer only in the active language.",
                        "The active language comes from the UI selection and is authoritative.",
                        "If the active language is English, do not answer in Hindi.",
                        "Do not copy English sentences directly unless the user asks for English.",
                        topic_lines,
                    ]
                )
                return _tool_result_response(context or "No specific information found.")
            return _tool_result_response("No specific legal information found for this query.")

        if fn_name == "generate_document":
            from backend.services.llm import generate_document_content
            from backend.services.document_gen import generate_pdf
            from backend.config import BACKEND_URL

            user_id = params.get("user_id", "anonymous")
            doc_type = params.get("doc_type", "Complaint Letter")
            details = params.get("details", {})

            content = generate_document_content(doc_type, details)
            filepath = generate_pdf(user_id=user_id, doc_type=doc_type, content=content, details=details)
            filename = os.path.basename(filepath)
            doc_url = f"{BACKEND_URL}/api/docs/{filename}"

            return _tool_result_response(f"Your {doc_type} has been generated. Download it here: {doc_url}")

    # 3. End of call — store conversation in Qdrant
    if msg_type == "end-of-call-report":
        artifact = message.get("artifact", {})
        messages_list = artifact.get("messages", [])
        call = message.get("call", {})
        metadata = call.get("metadata", {})
        user_id = metadata.get("user_id", "anonymous")

        if messages_list:
            conversation = [
                {"role": m.get("role", "user"), "text": m.get("content", "")}
                for m in messages_list
                if m.get("role") in ("user", "assistant")
            ]
            store_conversation(user_id=user_id, conversation=conversation, case_type="voice_call")
            logger.info(f"Stored end-of-call conversation for user {user_id}")

        return JSONResponse({"status": "stored"})




# ── Serve frontend (must be LAST so API routes take priority) ────
if os.path.isdir(FRONTEND_DIR):
    @app.get("/")
    async def serve_frontend():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/styles.css")
    async def serve_css():
        return FileResponse(os.path.join(FRONTEND_DIR, "styles.css"))

    @app.get("/app.js")
    async def serve_app_js():
        return FileResponse(os.path.join(FRONTEND_DIR, "app.js"))

    @app.get("/i18n.js")
    async def serve_i18n_js():
        return FileResponse(os.path.join(FRONTEND_DIR, "i18n.js"))

    # NOTE: Do NOT add a catch-all /{path:path} route here.
    # That would intercept /static/* requests before StaticFiles mount can serve them,
    # causing 404 errors in production for CSS/JS files.


def _get_greeting(lang: str) -> str:
    greetings = {
        "hi": "नमस्ते! मैं NyayaVoice हूँ। आपकी कानूनी समस्या बताइए, मैं आपकी मदद करूँगा।",
        "en": "Hello! I'm NyayaVoice, your legal aid assistant. Please tell me your problem.",
        "ta": "வணக்கம்! நான் NyayaVoice. உங்கள் சட்ட பிரச்சனையை சொல்லுங்கள்.",
        "bn": "নমস্কার! আমি NyayaVoice। আপনার আইনি সমস্যা বলুন।",
        "mr": "नमस्कार! मी NyayaVoice आहे। तुमची कायदेशीर समस्या सांगा.",
        "te": "నమస్కారం! నేను NyayaVoice. మీ చట్టపరమైన సమస్య చెప్పండి.",
        "gu": "નમસ્તે! હું NyayaVoice છું. તમારી કાનૂની સમસ્યા જણાવો.",
        "kn": "ನಮಸ್ಕಾರ! ನಾನು NyayaVoice. ನಿಮ್ಮ ಕಾನೂನು ಸಮಸ್ಯೆ ಹೇಳಿ.",
    }
    return greetings.get(lang, greetings["en"])
