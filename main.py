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
from backend.services.qdrant import ensure_collections, seed_legal_document
from backend.config import VAPI_PUBLIC_KEY, VAPI_API_KEY

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
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/docs", StaticFiles(directory=DOCS_DIR), name="docs")

# Include routers
app.include_router(query_router, prefix="/api", tags=["Query"])
app.include_router(document_router, prefix="/api", tags=["Document"])
app.include_router(memory_router, prefix="/api", tags=["Memory"])


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
        "backend_url": os.getenv("BACKEND_URL", "http://localhost:8080"),
    }


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

    # 1. Assistant request — return assistant config
    if msg_type == "assistant-request":
        call = message.get("call", {})
        metadata = call.get("metadata", {})
        language = metadata.get("language", "en")

        lang_names = {
            "hi": "Hindi", "en": "English", "ta": "Tamil",
            "bn": "Bengali", "mr": "Marathi", "te": "Telugu",
            "gu": "Gujarati", "kn": "Kannada", "pa": "Punjabi", "ur": "Urdu",
        }
        lang_name = lang_names.get(language, "English")

        return JSONResponse({
            "assistant": {
                "firstMessage": _get_greeting(language),
                "model": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "systemPrompt": (
                        f"You are NyayaVoice, a kind legal aid assistant for people in India. "
                        f"Always respond in {lang_name}. Use simple everyday language. "
                        f"Be empathetic. If the user is in danger, immediately give emergency numbers: "
                        f"Police 100, Women Helpline 181, Emergency 112. "
                        f"Ask one question at a time. Help users understand their rights and file complaints. "
                        f"When you have enough details, tell the user you will generate a document for them."
                    ),
                    "functions": [
                        {
                            "name": "query_legal",
                            "description": "Query the legal knowledge base for relevant legal information.",
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
                "voice": {"provider": "playht", "voiceId": "jennifer"},
                "transcriber": {
                    "provider": "deepgram",
                    "model": "nova-2",
                    "language": language if language != "en" else "en-IN",
                },
            }
        })

    # 2. Function call — search Qdrant or generate document
    if msg_type == "function-call":
        fn = message.get("functionCall", {})
        fn_name = fn.get("name", "")
        params = fn.get("parameters", {})

        if fn_name == "query_legal":
            text = params.get("text", "")
            if not text:
                return JSONResponse({"result": "Please tell me your problem."})

            results = search_legal_knowledge(text, top_k=4)
            if results:
                context = "\n\n".join(
                    f"[{r['category'].replace('_',' ').title()}]: {r['content']}"
                    for r in results if r["score"] > 0.2
                )
                return JSONResponse({"result": context or "No specific information found."})
            return JSONResponse({"result": "No specific legal information found for this query."})

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
            doc_url = f"{BACKEND_URL}/docs/{filename}"

            return JSONResponse({
                "result": f"Your {doc_type} has been generated. Download it here: {doc_url}"
            })

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

@app.post("/vapi-webhook")
async def vapi_webhook(request: Request):
    """
    Vapi webhook — handles voice call events.
    Vapi runs the LLM on its own; we provide RAG context + document generation.
    """
    print("Vapi webhook called")
    from backend.services.qdrant import search_legal_knowledge, store_conversation

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    message = payload.get("message", {})
    msg_type = message.get("type", "")
    logger.info(f"Vapi webhook received: type={msg_type}")

    # 1. Assistant request — return assistant config
    if msg_type == "assistant-request":
        call = message.get("call", {})
        metadata = call.get("metadata", {})
        language = metadata.get("language", "en")

        lang_names = {
            "hi": "Hindi", "en": "English", "ta": "Tamil",
            "bn": "Bengali", "mr": "Marathi", "te": "Telugu",
            "gu": "Gujarati", "kn": "Kannada", "pa": "Punjabi", "ur": "Urdu",
        }
        lang_name = lang_names.get(language, "English")

        return JSONResponse({
            "assistant": {
                "firstMessage": _get_greeting(language),
                "model": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "systemPrompt": (
                        f"You are NyayaVoice, a kind legal aid assistant for people in India. "
                        f"Always respond in {lang_name}. Use simple everyday language. "
                        f"Be empathetic. If the user is in danger, immediately give emergency numbers: "
                        f"Police 100, Women Helpline 181, Emergency 112. "
                        f"Ask one question at a time. Help users understand their rights and file complaints. "
                        f"When you have enough details, tell the user you will generate a document for them."
                    ),
                    "functions": [
                        {
                            "name": "query_legal",
                            "description": "Query the legal knowledge base for relevant legal information.",
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
                "voice": {"provider": "playht", "voiceId": "jennifer"},
                "transcriber": {
                    "provider": "deepgram",
                    "model": "nova-2",
                    "language": language if language != "en" else "en-IN",
                },
            }
        })

    # 2. Function call — search Qdrant or generate document
    if msg_type == "function-call":
        fn = message.get("functionCall", {})
        fn_name = fn.get("name", "")
        params = fn.get("parameters", {})

        if fn_name == "query_legal":
            text = params.get("text", "")
            if not text:
                return JSONResponse({"result": "Please tell me your problem."})

            results = search_legal_knowledge(text, top_k=4)
            if results:
                context = "\n\n".join(
                    f"[{r['category'].replace('_',' ').title()}]: {r['content']}"
                    for r in results if r["score"] > 0.2
                )
                return JSONResponse({"result": context or "No specific information found."})
            return JSONResponse({"result": "No specific legal information found for this query."})

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
            doc_url = f"{BACKEND_URL}/docs/{filename}"

            return JSONResponse({
                "result": f"Your {doc_type} has been generated. Download it here: {doc_url}"
            })

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

    print("Vapi webhook processed")
    return JSONResponse({"status": "received"})


# ── Serve frontend (must be LAST so API routes take priority) ────
if os.path.isdir(FRONTEND_DIR):
    @app.get("/")
    async def serve_frontend():
        print("Frontend served")
        print("Frontend requested")
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Catch-all route for SPA — serve index.html for client-side routing"""
        # If it's a static file, don't serve index.html
        if path.startswith("static/") or path.startswith("docs/"):
            return JSONResponse(status_code=404, content={"error": "Not found"})
        # Serve index.html for all other routes
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


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
