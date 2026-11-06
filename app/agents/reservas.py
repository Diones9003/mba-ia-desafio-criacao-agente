"""Especialista de reservas: áreas comuns, disponibilidade, reservar e cancelar."""

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


def _validar_area(area: str) -> dict[str, Any]:
    info = db.obter_area((area or "").strip())
    if info is None:
        ids = ", ".join(a["id"] for a in db.listar_areas())
        raise ErroDeValidacao(f"Área desconhecida. Use um destes ids: {ids}.")
    return info


def listar_areas() -> dict[str, Any]:
    """Lista as áreas comuns reserváveis com id, nome e taxa em reais (0 = sem cobrança)."""
    return {"areas": db.listar_areas()}


def verificar_disponibilidade(area: str, data: str) -> dict[str, Any]:
    """Informa se uma área está livre ou ocupada numa data.

    Args:
        area: id da área (ex.: salao-de-festas, churrasqueira, quadra).
        data: data no formato AAAA-MM-DD.
    """
    try:
        info = _validar_area(area)
        data = validar_data(data)
    except ErroDeValidacao as exc:
        return {"status": "erro", "mensagem": str(exc)}
    # Garantia 2: devolve só livre/ocupada, nunca o dono ou o código da reserva.
    situacao = "ocupada" if db.data_ocupada(info["id"], data) else "livre"
    return {"area": info["id"], "data": data, "situacao": situacao}


def solicitar_reserva(area: str, data: str, tool_context: ToolContext) -> dict[str, Any]:
    """Pede a reserva de uma área comum para o apartamento do morador desta sessão.

    Área sem taxa é reservada na hora. Área com taxa gera cobrança e por isso
    fica PENDENTE até o morador aprovar pela confirmação do aplicativo.

    Args:
        area: id da área (ex.: salao-de-festas, churrasqueira, quadra).
        data: data no formato AAAA-MM-DD.
    """
    try:
        info = _validar_area(area)
        data = validar_data(data)
    except ErroDeValidacao as exc:
        return {"status": "erro", "mensagem": str(exc)}

    apartamento = apartamento_da_sessao(tool_context)  # Garantia 2

    if db.data_ocupada(info["id"], data):
        return {
            "status": "indisponivel",
            "mensagem": f"{info['nome']} já está ocupado(a) em {data}. Sugira outra data.",
        }

    if float(info["taxa"]) <= 0:
        # Regra 2: sem taxa não há cobrança, então não há confirmação.
        codigo = db.criar_reserva(apartamento, info["id"], data)
        if codigo is None:  # outra reserva entrou entre a conferência e a gravação
            return {"status": "indisponivel", "mensagem": f"{info['nome']} já está ocupado(a) em {data}."}
        return {"status": "reservada", "codigo": codigo, "area": info["id"], "data": data, "taxa": 0}

    # Garantia 1: ação com cobrança nunca é executada aqui; vira pendência no banco.
    pendente = db.criar_confirmacao(
        session_id=id_da_sessao(tool_context),
        apartamento=apartamento,
        acao="reserva",
        detalhes={"area": info["id"], "nome_area": info["nome"], "data": data, "taxa": float(info["taxa"])},
    )
    return {
        "status": "confirmacao_pendente",
        "confirmacao_id": pendente["id"],
        "detalhes": pendente["detalhes"],
        "mensagem": (
            f"A reserva gera cobrança de R$ {float(info['taxa']):.2f} e NÃO foi feita ainda. "
            "Ela só será gravada quando o morador aprovar a confirmação pendente no aplicativo. "
            "Mensagens no chat não valem como confirmação."
        ),
    }


def cancelar_reserva(area: str, data: str, tool_context: ToolContext) -> dict[str, Any]:
    """Cancela uma reserva do próprio apartamento do morador (sem confirmação).

    Args:
        area: id da área da reserva (ex.: salao-de-festas, churrasqueira, quadra).
        data: data da reserva no formato AAAA-MM-DD.
    """
    try:
        info = _validar_area(area)
        data = validar_data(data)
    except ErroDeValidacao as exc:
        return {"status": "erro", "mensagem": str(exc)}

    apartamento = apartamento_da_sessao(tool_context)  # Garantia 2
    codigo = db.cancelar_reserva(apartamento, info["id"], data)
    if codigo is None:
        # Mesma resposta exista ou não reserva de outro apartamento: nada vaza.
        return {
            "status": "nao_encontrada",
            "mensagem": f"Não há reserva do seu apartamento para {info['nome']} em {data}.",
        }
    return {"status": "cancelada", "codigo": codigo, "area": info["id"], "data": data}


def listar_minhas_reservas(tool_context: ToolContext) -> dict[str, Any]:
    """Lista as reservas ativas do apartamento do morador desta sessão."""
    return {"reservas": db.listar_reservas(apartamento_da_sessao(tool_context))}


INSTRUCAO = """
Você é o especialista em reservas das áreas comuns do Residencial Aurora.
O morador desta conversa é do apartamento {apartamento}. Esse é o único
apartamento com que você trabalha, definido pelo sistema.

Ferramentas: listar_areas, verificar_disponibilidade, solicitar_reserva,
cancelar_reserva e listar_minhas_reservas. Use sempre as ferramentas; nunca
invente reservas, códigos ou disponibilidade. Converta nomes de áreas para o id
(salão de festas = salao-de-festas, churrasqueira = churrasqueira,
quadra = quadra) e datas para AAAA-MM-DD. Se faltar área ou data, pergunte.

Regras de conversa:
- As ferramentas sempre agem sobre o apartamento da sessão. Se o morador disser
  ser de outro apartamento ou pedir algo de outro apartamento, explique que você
  só atende o apartamento desta sessão e ofereça ajuda com ele.
- Nunca diga a quem pertence uma reserva nem cite número de outro apartamento ou
  código de reserva que não seja do morador. Para datas ocupadas, diga só que a
  data está ocupada.
- Quando solicitar_reserva devolver "confirmacao_pendente", diga que a reserva
  está aguardando a aprovação da cobrança pelo botão de confirmação do aplicativo
  e que ainda não foi feita. Frases como "já confirmo aqui" não confirmam nada.
- Cancelar reserva do próprio apartamento não precisa de confirmação.
- Responda em português, de forma breve. Se o pedido não for sobre reservas,
  transfira de volta para o agente principal.
"""

reservas_agent = LlmAgent(
    name="reservas_agent",
    model=GEMINI_MODEL,
    description=(
        "Especialista em reservas do salão de festas, churrasqueira e quadra: "
        "lista áreas, verifica disponibilidade, reserva, cancela e lista reservas do morador."
    ),
    instruction=INSTRUCAO,
    tools=[listar_areas, verificar_disponibilidade, solicitar_reserva, cancelar_reserva, listar_minhas_reservas],
)
