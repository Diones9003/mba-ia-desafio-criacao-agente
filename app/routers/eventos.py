from typing import Any

from fastapi import APIRouter

from app import agent_runner
from app.routers.schemas import exigir_sessao

router = APIRouter(prefix="/sessoes", tags=["eventos"])


@router.get("/{session_id}/eventos")
async def listar_eventos(session_id: str) -> list[dict[str, Any]]:
    session = await exigir_sessao(session_id)
    return agent_runner.eventos_serializados(session)
