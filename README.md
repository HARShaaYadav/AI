# NyayaVoice — Voice Legal Aid Assistant

> Empowering access to justice through voice technology.

A voice-first, multilingual AI legal aid assistant for people who face barriers accessing legal services — rural communities, low-literacy individuals, and migrant workers.

**No OpenAI API key required.** Text chat uses free local AI (FastEmbed + Qdrant). Voice calls use Vapi credits.

---

## Tech Stack

| Component | Technology |
|---|---|
| Voice Interface | [Vapi](https://vapi.ai) (STT + LLM + TTS) |
| Vector DB | [Qdrant](https://qdrant.tech) (RAG + memory) |
| Embeddings | FastEmbed (BAAI/bge-small-en) |
| Backend | FastAPI (Python) |
| Document Gen | ReportLab (PDF templates) |
| Frontend | HTML / CSS / Vanilla JS |

---

## Quick Start (3 Steps)

### Step 1: Install dependencies

```bash
pip install -r requirements.txt
```

> First run downloads the embedding model (~50MB). This is cached for future runs.

### Step 2: Configure your Vapi keys

```bash
copy .env.example .env
```

Edit `.env` with your Vapi credentials:

```
VAPI_API_KEY=your-vapi-api-key-here
VAPI_PUBLIC_KEY=your-vapi-public-key-here
QDRANT_URL=:memory:
BACKEND_URL=http://localhost:8000
```

**How to get Vapi keys:**
1. Sign up at [vapi.ai](https://vapi.ai)
2. Go to Dashboard → copy your **API Key** and **Public Key**
3. Paste them in `.env`

> **Text chat works WITHOUT Vapi keys** — only voice calls need them.

### Step 3: Start the server

```bash
uvicorn backend.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser. Done!

The server automatically:
1. Loads the FastEmbed model (local)
2. Creates Qdrant collections (in-memory)
3. Seeds 18 legal knowledge entries into the vector DB
4. Serves the frontend

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USER                                 │
│                   (Voice or Text)                            │
└──────────┬──────────────────────┬───────────────────────────┘
           │                      │
     ┌─────▼─────┐        ┌──────▼──────┐
     │   VOICE   │        │    TEXT     │
     │ Vapi SDK  │        │  /query    │
     │ (Browser) │        │  endpoint  │
     └─────┬─────┘        └──────┬──────┘
           │                      │
     ┌─────▼─────┐        ┌──────▼──────┐
     │   Vapi    │        │  FastEmbed  │
     │  Cloud    │        │  (Local)    │
     │ STT+LLM  │        │  Embeddings │
     │  +TTS    │        └──────┬──────┘
     └─────┬─────┘               │
           │              ┌──────▼──────┐
     ┌─────▼─────┐        │   Qdrant   │
     │ Webhook   │◄───────│  Vector DB │
     │/vapi-     │        │  (Search)  │
     │ webhook   │        └──────┬──────┘
     └─────┬─────┘               │
           │              ┌──────▼──────┐
     ┌─────▼─────┐        │  Response  │
     │  Qdrant   │        │  Engine    │
     │  Search   │        │ (Template) │
     └─────┬─────┘        └──────┬──────┘
           │                      │
     ┌─────▼─────┐        ┌──────▼──────┐
     │  Context  │        │  Formatted │
     │  to Vapi  │        │  Reply to  │
     │  LLM      │        │  Frontend  │
     └───────────┘        └─────────────┘
```

### How Qdrant is Used

1. **Legal Knowledge Base** (`legal_knowledge` collection)
   - 18 pre-seeded entries covering: theft, domestic violence, harassment, wage theft, land disputes, FIR process, legal aid, cyber crime, consumer rights, RTI, child rights
   - Text is embedded locally using FastEmbed (BAAI/bge-small-en-v1.5)
   - When user asks a question → query is embedded → semantic search finds the most relevant legal knowledge (RAG)

2. **User Memory** (`user_memory` collection)
   - Stores conversation summaries per user
   - When user returns, past conversations are retrieved for personalization
   - Enables continuity across sessions

### How Vapi is Used

1. **Voice Calls** (uses Vapi credits)
   - User clicks mic → Vapi Web SDK starts a voice call
   - Vapi handles: Speech-to-Text (Deepgram) → LLM (GPT-4o) → Text-to-Speech (PlayHT)
   - During the call, Vapi calls our `/vapi-webhook` for:
     - `query_legal` → searches Qdrant, returns legal context to the LLM
     - `generate_document` → creates a PDF document
     - `end-of-call-report` → stores conversation in Qdrant memory

2. **Text Chat** (FREE — no Vapi credits used)
   - User types → `POST /query` → FastEmbed + Qdrant search → template response
   - Works completely offline from Vapi
   - Uses local embeddings (no API calls)

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/query` | Text chat — Qdrant RAG search (free, no API key) |
| POST | `/generate-document` | Generate FIR/complaint PDF (template-based) |
| POST | `/store-memory` | Save conversation to Qdrant |
| POST | `/recall-memory` | Retrieve past conversations |
| GET | `/docs/{filename}` | Download generated PDF |
| POST | `/vapi-webhook` | Vapi voice call webhook |
| GET | `/health` | Health check |
| GET | `/api/config` | Frontend config (Vapi public key) |
| GET | `/` | Serve frontend UI |

---

## Features

- **Voice-first** — speak in your language, hear the answer back (via Vapi)
- **No OpenAI key needed** — text chat uses local embeddings
- **Bilingual** — Hindi & English
- **RAG-powered** — legal knowledge retrieved from Qdrant vector DB
- **Personalized memory** — remembers past conversations per user
- **Document generation** — auto-generates FIR drafts and complaints as PDF (template-based, no LLM)
- **Emergency detection** — instantly surfaces helpline numbers when danger is detected
- **In-memory Qdrant** — no Docker required
- **18 legal knowledge entries** covering Indian law

---

## Optional: Qdrant Cloud (for persistent storage)

For data that persists across server restarts:

1. Sign up free at [cloud.qdrant.io](https://cloud.qdrant.io)
2. Create a free cluster (1GB free tier)
3. Copy the cluster URL and API key
4. Set in `.env`:
   ```
   QDRANT_URL=https://your-cluster-id.us-east4-0.gcp.cloud.qdrant.io:6333
   QDRANT_API_KEY=your-qdrant-api-key
   ```

---

## Optional: Run Qdrant with Docker (alternative)

```bash
docker run -p 6333:6333 qdrant/qdrant
```

Set `QDRANT_URL=http://localhost:6333` in `.env`.

---

## Supported Languages

| Code | Language |
|---|---|
| hi | हिंदी (Hindi) |
| en | English |
#AI