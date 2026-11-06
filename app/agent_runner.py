"""Runner do ADK com sessões persistidas em SQLite (Garantia 3).

O Runner é recriado a cada subida da API, mas aponta sempre para o mesmo
arquivo `sessoes.db`; por isso sessões, state e eventos continuam após reinício.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from typing import Any

from google.adk.apps import App
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import Session
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types

from app.agents import root_agent
from app.agents._sessao import STATE_APARTAMENTO
from app.config import APP_NAME, SESSOES_DB_PATH

logger = logging.getLogger(__name__)

AUTOR_SISTEMA = "sistema_confirmacoes"

# Serviço de sessão nativo do ADK para SQLite (aiosqlite), eventos gravados em JSON.
session_service = SqliteSessionService(db_path=str(SESSOES_DB_PATH))
adk_app = App(name=APP_NAME, root_agent=root_agent)
runner = Runner(app=adk_app, session_service=session_service)

# Serializa o trabalho dentro de UMA sessão (evita gravação concorrente de
# eventos na mesma sessão). Sessões diferentes continuam em paralelo.
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def lock_da_sessao(session_id: str) -> asyncio.Lock:
    return _locks[session_id]


def _user_id(session_id: str) -> str:
    # Cada sessão tem o próprio user_id: assim as rotas localizam a sessão só pelo id.
    return session_id


async def criar_sessao(apartamento: str) -> str:
    session_id = str(uuid.uuid4())
    # Garantia 2: o apartamento entra no state UMA vez, aqui, pelo sistema.
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=_user_id(session_id),
        session_id=session_id,
        state={STATE_APARTAMENTO: apartamento},
    )
    return session_id


async def obter_sessao(session_id: str) -> Session | None:
    return await session_service.get_session(app_name=APP_NAME, user_id=_user_id(session_id), session_id=session_id)


async def enviar_mensagem(session_id: str, texto: str) -> str:
    """Executa o agente para uma mensagem e devolve o texto final da resposta."""
    mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
    respostas: list[str] = []
    async for event in runner.run_async(user_id=_user_id(session_id), session_id=session_id, new_message=mensagem):
        if event.author == "user" or event.partial or not event.content or not event.content.parts:
            continue
        if event.get_function_calls() or event.get_function_responses():
            continue
        texto_evento = "".join(p.text for p in event.content.parts if p.text and not p.thought).strip()
        if texto_evento:
            respostas.append(texto_evento)
    return respostas[-1] if respostas else ""


async def registrar_evento_do_sistema(session_id: str, texto: str) -> None:
    """Grava na sessão o resultado de uma confirmação, para o histórico e o modelo."""
    session = await obter_sessao(session_id)
    if session is None:
        return
    event = Event(
        invocation_id=f"e-{uuid.uuid4()}",
        author=AUTOR_SISTEMA,
        content=types.Content(role="model", parts=[types.Part(text=texto)]),
    )
    await session_service.append_event(session, event)


def eventos_serializados(session: Session) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json", exclude_none=True) for e in session.events]
