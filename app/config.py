"""Configuração central: caminhos, nome da aplicação e modelo Gemini."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DADOS_DIR = BASE_DIR / "dados"
REGULAMENTO_PATH = DADOS_DIR / "regulamento.md"

# Dados do condomínio (reservas, visitantes, confirmações) e sessões do ADK
# ficam em dois arquivos SQLite locais, sem nenhum serviço externo.
AURORA_DB_PATH = Path(os.getenv("AURORA_DB_PATH", BASE_DIR / "aurora.db"))
SESSOES_DB_PATH = Path(os.getenv("SESSOES_DB_PATH", BASE_DIR / "sessoes.db"))

APP_NAME = "residencial_aurora"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
