"""Helpers compartilhados pelas tools.

Garantia 2: o apartamento usado por TODAS as tools vem daqui, do state da
sessão gravado pela API em POST /sessoes. Nenhuma tool recebe o apartamento
como parâmetro, então o modelo não tem como escolher outro.
"""

from __future__ import annotations

from datetime import datetime

from google.adk.tools import ToolContext

STATE_APARTAMENTO = "apartamento"


class ErroDeValidacao(ValueError):
    pass


def apartamento_da_sessao(tool_context: ToolContext) -> str:
    apartamento = tool_context.state.get(STATE_APARTAMENTO)
    if not apartamento:
        raise RuntimeError("Sessão sem apartamento definido.")
    return str(apartamento)


def id_da_sessao(tool_context: ToolContext) -> str:
    return tool_context.session.id


def validar_data(data: str) -> str:
    texto = (data or "").strip()
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ErroDeValidacao("Data inválida. Use o formato AAAA-MM-DD.") from exc
