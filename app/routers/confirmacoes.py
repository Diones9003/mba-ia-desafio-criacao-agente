"""Rota de confirmações: a ÚNICA porta para executar ação com cobrança ou acesso (Garantia 1)."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app import agent_runner
from app import database as db
from app.routers.schemas import RespostaConfirmacao, RespostaConversa, exigir_sessao, montar_resposta

router = APIRouter(prefix="/sessoes", tags=["confirmacoes"])


def _mensagem(resultado: dict[str, Any]) -> str:
    d = resultado["detalhes"]
    status = resultado["status"]
    if resultado["acao"] == "reserva":
        alvo = f"{d.get('nome_area', d['area'])} em {d['data']}"
        if status == "executada":
            return (
                f"Reserva confirmada: {alvo}, código {resultado['codigo']}. "
                f"A taxa de R$ {float(d.get('taxa', 0)):.2f} será cobrada."
            )
        if status == "data_ocupada":
            return f"Não foi possível reservar {alvo}: a data já está ocupada. Nenhuma cobrança foi gerada."
        return f"Reserva de {alvo} não confirmada. Nada foi gravado e nenhuma cobrança foi gerada."
    alvo = f"{d['nome']} em {d['data']}"
    if status == "executada":
        return f"Entrada autorizada: {alvo}."
    return f"Autorização de {alvo} não confirmada. Nenhum acesso foi liberado."


@router.post("/{session_id}/confirmacoes", response_model=RespostaConversa)
async def responder_confirmacao(session_id: str, body: RespostaConfirmacao) -> RespostaConversa:
    await exigir_sessao(session_id)
    async with agent_runner.lock_da_sessao(session_id):
        # Leitura do status + execução + mudança de status numa única transação SQLite.
        resultado = await asyncio.to_thread(db.responder_confirmacao, session_id, body.id, body.confirmado)
        if resultado is None:
            raise HTTPException(status_code=409, detail="Não existe confirmação pendente com esse id nesta sessão.")
        resposta = _mensagem(resultado)
        await agent_runner.registrar_evento_do_sistema(session_id, f"[Resultado da confirmação {body.id}] {resposta}")
    return montar_resposta(session_id, resposta)
