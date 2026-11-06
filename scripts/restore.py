"""Restaura reservas e visitantes ao estado de dados/*.json.

Uso: uv run python scripts/restore.py

- Recria reservas e visitantes a partir dos arquivos de dados.
- Descarta confirmações pendentes (referem-se a um estado que deixou de existir).
- Preserva as sessões do ADK (sessoes.db) e o histórico de códigos emitidos.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import database as db  # noqa: E402


def main() -> None:
    db.init_db()
    totais = db.restaurar_dados_iniciais()
    print(f"Dados restaurados: {totais['reservas']} reservas e {totais['visitantes']} visitantes.")


if __name__ == "__main__":
    main()
