import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agent.runtime import run_agent_runtime_diagnosis
from app.agent.workflow import run_agent_diagnosis
from app.core.config import settings
from app.db.session import get_db
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.schemas.agent import AgentDiagnoseRequest, AgentDiagnoseResponse


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agent",
    tags=["Agent"],
)


@router.post(
    "/diagnose",
    response_model=AgentDiagnoseResponse,
)
def diagnose(
    request: AgentDiagnoseRequest,
    db: Session = Depends(get_db),
    llm_provider: LLMProvider = Depends(get_llm_provider),
) -> AgentDiagnoseResponse:
    try:
        if settings.agent_runtime_enabled:
            return run_agent_runtime_diagnosis(
                db=db,
                request=request,
                llm_provider=llm_provider,
            )

        return run_agent_diagnosis(
            db=db,
            request=request,
            llm_provider=llm_provider,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected agent diagnosis API failure.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent diagnosis failed due to an internal error.",
        ) from exc
