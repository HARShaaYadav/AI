import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.qdrant import store_conversation, get_user_memory

logger = logging.getLogger(__name__)
router = APIRouter()


class MemoryRequest(BaseModel):
    user_id: str
    conversation: list
    case_type: str = "general"


class MemoryResponse(BaseModel):
    status: str


class RecallRequest(BaseModel):
    user_id: str
    top_k: int = 5


@router.post("/store-memory", response_model=MemoryResponse)
async def store_memory(req: MemoryRequest):
    if not req.user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    store_conversation(
        user_id=req.user_id,
        conversation=req.conversation,
        case_type=req.case_type,
    )
    response = MemoryResponse(status="stored")
    print(f"Memory stored for user {req.user_id}")
    return response


@router.post("/recall-memory")
async def recall_memory(req: RecallRequest):
    if not req.user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    memories = get_user_memory(req.user_id, top_k=req.top_k)
    response = {"user_id": req.user_id, "memories": memories, "count": len(memories)}
    print(f"Memory recalled for user {req.user_id}: {len(memories)} items")
    return response
