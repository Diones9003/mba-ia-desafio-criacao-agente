"""API do assistente do Residencial Aurora."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import database as db
from app.routers import confirmacoes, eventos, sessoes, verificacao

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("aurora")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if not os.getenv("GOOGLE_API_KEY"):
        logger.warning("GOOGLE_API_KEY não definida: rotas de conversa vão falhar até configurar o .env.")
    yield


app = FastAPI(title="Assistente do Residencial Aurora", lifespan=lifespan)
app.include_router(sessoes.router)
app.include_router(confirmacoes.router)
app.include_router(eventos.router)
app.include_router(verificacao.router)
