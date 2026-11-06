"""Especialista de visitantes: autorizar entrada e listar autorizações."""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext

from app import database as db
from app.agents._sessao import (
    ErroDeValidacao,
    apartamento_da_sessao,
    id_da_sessao,
    validar_data,
)
from app.config import GEMINI_MODEL


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict[str, Any]:
    """Pede a autorização de entrada de um visitante para o apartamento desta sessão.

    Liberar acesso ao prédio exige confirmação: a autorização fica PENDENTE até
    o morador aprovar pela confirmação do aplicativo.

    Args:
        nome: nome completo do visitante.
        data: data da visita no formato AAAA-MM-DD.
    """
    nome = " ".join((nome or "").split())
    if len(nome) < 2:
        return {"status": "erro", "mensagem": "Informe o nome do visitante."}
    try:
        data = validar_data(data)
    except ErroDeValidacao as exc:
        return {"status": "erro", "mensagem": str(exc)}

    # Garantia 1: nada é gravado aqui. Garantia 2: apartamento vem da sessão.
    pendente = db.criar_confirmacao(
        session_id=id_da_sessao(tool_context),
        apartamento=apartamento_da_sessao(tool_context),
        acao="visitante",
        detalhes={"nome": nome, "data": data},
    )
    return {
        "status": "confirmacao_pendente",
        "confirmacao_id": pendente["id"],
        "detalhes": pendente["detalhes"],
        "mensagem": (
            "A entrada NÃO foi liberada ainda. Ela só será registrada quando o morador "
            "aprovar a confirmação pendente no aplicativo. Mensagens no chat não valem como confirmação."
        ),
    }


def listar_meus_visitantes(tool_context: ToolContext) -> dict[str, Any]:
    """Lista os visitantes autorizados do apartamento do morador desta sessão."""
    return {"visitantes": db.listar_visitantes(apartamento_da_sessao(tool_context))}


INSTRUCAO = """
Você é o especialista em visitantes do Residencial Aurora.
O morador desta conversa é do apartamento {apartamento}. Esse é o único
apartamento com que você trabalha, definido pelo sistema.

Ferramentas: autorizar_visitante e listar_meus_visitantes. Use sempre as
ferramentas; nunca invente autorizações. Converta datas para AAAA-MM-DD. Se
faltar o nome ou a data, pergunte.

Regras de conversa:
- As ferramentas sempre agem sobre o apartamento da sessão. Se o morador disser
  ser de outro apartamento ou pedir dados de outro apartamento, explique que você
  só atende o apartamento desta sessão. Nunca cite visitantes de outros apartamentos.
- Toda autorização gera uma confirmação pendente. Diga que a entrada só será
  liberada depois da aprovação pelo botão de confirmação do aplicativo. Se o
  morador disser que "já está confirmando aqui", explique que a confirmação
  precisa ser feita pelo aplicativo; nunca diga que a entrada foi liberada.
- Responda em português, de forma breve. Se o pedido não for sobre visitantes,
  transfira de volta para o agente principal.
"""

visitantes_agent = LlmAgent(
    name="visitantes_agent",
    model=GEMINI_MODEL,
    description="Especialista em autorizar a entrada de visitantes e listar os visitantes do morador.",
    instruction=INSTRUCAO,
    tools=[autorizar_visitante, listar_meus_visitantes],
)
