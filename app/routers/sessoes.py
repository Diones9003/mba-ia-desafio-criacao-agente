import logging

from fastapi import APIRouter, HTTPException

from app import agent_runner
from app.routers.schemas import Mensagem, NovaSessao, RespostaConversa, SessaoCriada, exigir_sessao, montar_resposta

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessoes", tags=["sessoes"])


@router.post("", status_code=201, response_model=SessaoCriada)
async def criar_sessao(body: NovaSessao) -> SessaoCriada:
    session_id = await agent_runner.criar_sessao(body.apartamento.strip())
    return SessaoCriada(session_id=session_id)


@router.post("/{session_id}/mensagens", response_model=RespostaConversa)
async def enviar_mensagem(session_id: str, body: Mensagem) -> RespostaConversa:
    await exigir_sessao(session_id)
    async with agent_runner.lock_da_sessao(session_id):
        try:
            resposta = await agent_runner.enviar_mensagem(session_id, body.texto)
        except Exception as exc:  # falha do modelo/provedor (cota, rede, chave)
            logger.exception("Falha ao executar o agente na sessão %s", session_id)
            raise HTTPException(status_code=502, detail=f"Falha ao consultar o modelo: {exc}") from exc
    return montar_resposta(session_id, resposta)
