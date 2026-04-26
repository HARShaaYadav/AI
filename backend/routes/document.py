import os
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.services.llm import generate_document_content
from backend.services.document_gen import generate_pdf
from backend.config import VALID_DOC_TYPES

logger = logging.getLogger(__name__)
router = APIRouter()

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "generated_docs")


class DocumentRequest(BaseModel):
    user_id: str
    doc_type: str
    details: dict


class DocumentResponse(BaseModel):
    document_url: str
    status: str
    filename: str


@router.post("/generate-document", response_model=DocumentResponse)
async def generate_document(req: DocumentRequest):
    # Validate doc_type
    if req.doc_type not in VALID_DOC_TYPES:
        # Accept it anyway but log a warning
        logger.warning(f"Non-standard doc_type requested: {req.doc_type}")

    if not req.details:
        raise HTTPException(status_code=400, detail="Details cannot be empty")

    # Generate document content via LLM
    content = generate_document_content(req.doc_type, req.details)

    if content.startswith("[Document generation failed"):
        raise HTTPException(status_code=500, detail="Document generation failed")

    # Render to PDF
    filepath = generate_pdf(
        user_id=req.user_id,
        doc_type=req.doc_type,
        content=content,
        details=req.details,
    )

    filename = os.path.basename(filepath)
    document_url = f"/api/docs/{filename}"

    return DocumentResponse(
        document_url=document_url,
        status="generated",
        filename=filename,
    )
    print(f"Document generated for user {req.user_id}: {req.doc_type}")


@router.get("/docs/{filename}")
async def serve_document(filename: str):
    # Sanitize filename to prevent path traversal
    filename = os.path.basename(filename)
    filepath = os.path.join(DOCS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Document not found")
    print(f"Serving document: {filename}")
    return FileResponse(filepath, media_type="application/pdf", filename=filename)
