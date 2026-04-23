import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.llm import generate_case_predictor_analysis

logger = logging.getLogger(__name__)
router = APIRouter()


class PredictorAnswer(BaseModel):
    role: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)


class PredictorRequest(BaseModel):
    case_type: str = Field(..., min_length=1)
    facts: str = Field(..., min_length=1)
    evidence: List[str] = Field(default_factory=list)
    language: str = Field("en")
    answers: List[PredictorAnswer] = Field(default_factory=list)
    question_target: int = Field(6, ge=5, le=7)


class PredictorQuestion(BaseModel):
    role: str
    text: str


class PredictorReport(BaseModel):
    case_summary: str
    strengths: List[str]
    weaknesses: List[str]
    missing_evidence: List[str]
    legal_risks: List[str]
    suggestions: List[str]
    win_probability: int
    confidence_score: str


class PredictorResponse(BaseModel):
    case_summary: str
    next_step: Literal["question", "final_report"]
    question: Optional[PredictorQuestion] = None
    report: Optional[PredictorReport] = None
    source: str
    source_detail: Optional[str] = None


@router.post("/case-predictor", response_model=PredictorResponse)
async def case_predictor(req: PredictorRequest) -> PredictorResponse:
    try:
        facts = req.facts.strip()
        if not facts:
            raise HTTPException(status_code=400, detail="Case facts cannot be empty")

        answers_payload = [item.model_dump() for item in req.answers]
        result = generate_case_predictor_analysis(
            case_type=req.case_type.strip(),
            facts=facts,
            evidence=req.evidence,
            answers=answers_payload,
            lang=req.language or "en",
            question_target=req.question_target,
        )
        return PredictorResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Case predictor failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Case predictor failed")
