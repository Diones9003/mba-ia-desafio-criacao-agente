from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app import agent_runner
from app import database as db


class NovaSessao(BaseModel):
    apartamento: str = Field(min_length=1)


class SessaoCriada(BaseModel):
    session_id: str


class Mensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


class ConfirmacaoPendente(BaseModel):
    id: str
    acao: str
    detalhes: dict[str, Any]


class RespostaConversa(BaseModel):
    resposta: str
    confirmacoes_pendentes: list[ConfirmacaoPendente]


async def exigir_sessao(session_id: str):
    session = await agent_runner.obter_sessao(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    return session


def montar_resposta(session_id: str, resposta: str) -> RespostaConversa:
    # As pendências vêm do banco (fonte da verdade), não do texto do modelo.
    pendentes = db.listar_confirmacoes_pendentes(session_id)
    return RespostaConversa(resposta=resposta, confirmacoes_pendentes=[ConfirmacaoPendente(**p) for p in pendentes])
