import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from backend.services.llm import generate_response

logger = logging.getLogger(__name__)
router = APIRouter()


class QueryRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="Unique user identifier")
    text: str = Field(..., min_length=1, description="User's query text")
    language: Optional[str] = Field("en", description="Language code (e.g., 'en', 'hi')")
    conversation: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Previous conversation history")


class QueryResponse(BaseModel):
    response: str = Field(..., description="AI-generated response")
    intent: str = Field(..., description="Detected intent of the query")
    language: str = Field(..., description="Response language")
    follow_up: bool = Field(..., description="Whether follow-up is needed")
    urgency: bool = Field(..., description="Whether the query indicates urgency")
    source: str = Field(..., description="Response source: openrouter, openai, or backend_fallback")
    source_detail: Optional[str] = Field(None, description="More detail about the response source or fallback reason")


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """
    Process a user query and return an AI-generated response.
    """
    try:
        if not req.text.strip():
            raise HTTPException(status_code=400, detail="Query text cannot be empty")

        if len(req.text) > 10000:  # Reasonable limit
            raise HTTPException(status_code=400, detail="Query text too long (max 10000 characters)")

        result = generate_response(
            user_id=req.user_id,
            user_message=req.text,
            conversation=req.conversation or [],
            language_code=req.language or "en",
        )

        response = QueryResponse(**result)
        logger.info(
            "Query processed for user %s: intent=%s language=%s source=%s source_detail=%s",
            req.user_id,
            response.intent,
            response.language,
            response.source,
            response.source_detail,
        )
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing query for user {req.user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
