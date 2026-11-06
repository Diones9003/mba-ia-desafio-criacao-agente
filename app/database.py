"""Camada de dados do condomínio em SQLite.

Todas as regras críticas que dependem de dados vivem aqui, no código:
- exclusividade de reserva por área/data no instante da gravação (Garantia 5);
- códigos de reserva que nunca se repetem, nem de reservas canceladas;
- confirmações pendentes que só o sistema aprova, uma única vez (Garantia 1);
- toda consulta e alteração filtrada pelo apartamento recebido do chamador,
  que nas tools é sempre o apartamento da sessão (Garantia 2).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import AURORA_DB_PATH, DADOS_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS reservas (
    codigo      TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    area        TEXT NOT NULL,
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa', 'cancelada')),
    criada_em   TEXT NOT NULL
);

-- Garantia 5: no máximo UMA reserva ativa por área e data.
-- O próprio SQLite recusa a segunda gravação, mesmo que duas requisições
-- tenham passado juntas pela conferência de agenda.
CREATE UNIQUE INDEX IF NOT EXISTS ux_reservas_area_data_ativa
    ON reservas (area, data) WHERE status = 'ativa';

-- Todo código já emitido. Nunca é limpo (nem pela restauração),
-- então um código novo jamais repete o de outra reserva, cancelada ou não.
CREATE TABLE IF NOT EXISTS codigos_emitidos (
    codigo TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL,
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL,
    criada_em   TEXT NOT NULL
);

-- Garantia 1: ações que geram cobrança ou liberam acesso ficam aqui
-- até o morador responder pela rota de confirmações.
CREATE TABLE IF NOT EXISTS pending_confirmations (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    apartamento  TEXT NOT NULL,
    action_type  TEXT NOT NULL CHECK (action_type IN ('reserva', 'visitante')),
    details      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'approved', 'denied', 'failed')),
    resultado    TEXT,
    created_at   TEXT NOT NULL,
    responded_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_pending_session ON pending_confirmations (session_id, status);

CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    # isolation_level=None: transações explícitas (BEGIN IMMEDIATE) controladas aqui.
    conn = sqlite3.connect(AURORA_DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def conexao() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transacao() -> Iterator[sqlite3.Connection]:
    """Transação de escrita com lock obtido já no início (BEGIN IMMEDIATE)."""
    with conexao() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


# --------------------------------------------------------------------------- #
# Inicialização e restauração
# --------------------------------------------------------------------------- #
def _ler_json(nome: str) -> list[dict[str, Any]]:
    with open(DADOS_DIR / nome, encoding="utf-8") as f:
        return json.load(f)


def init_db() -> None:
    """Cria as tabelas e, só na primeira execução, carrega os dados iniciais."""
    AURORA_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with conexao() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        semeado = conn.execute("SELECT 1 FROM meta WHERE chave = 'semeado'").fetchone()
    if not semeado:
        restaurar_dados_iniciais()


def restaurar_dados_iniciais() -> dict[str, int]:
    """Volta reservas e visitantes ao estado de dados/*.json.

    Também descarta confirmações pendentes (elas se referem a um estado que
    deixou de existir). Sessões do ADK ficam em outro arquivo e são preservadas.
    `codigos_emitidos` nunca é limpo, para nenhum código se repetir.
    """
    reservas = _ler_json("reservas.json")
    visitantes = _ler_json("visitantes.json")
    agora = _agora()
    with conexao() as conn:
        conn.executescript(SCHEMA)
    with transacao() as conn:
        conn.execute("DELETE FROM reservas")
        conn.execute("DELETE FROM visitantes")
        conn.execute("DELETE FROM pending_confirmations")
        for r in reservas:
            conn.execute(
                "INSERT INTO reservas (codigo, apartamento, area, data, status, criada_em) "
                "VALUES (?, ?, ?, ?, 'ativa', ?)",
                (r["codigo"], str(r["apartamento"]), r["area"], r["data"], agora),
            )
            conn.execute("INSERT OR IGNORE INTO codigos_emitidos (codigo) VALUES (?)", (r["codigo"],))
        for v in visitantes:
            conn.execute(
                "INSERT INTO visitantes (apartamento, nome, data, criada_em) VALUES (?, ?, ?, ?)",
                (str(v["apartamento"]), v["nome"], v["data"], agora),
            )
        conn.execute("INSERT OR REPLACE INTO meta (chave, valor) VALUES ('semeado', ?)", (agora,))
    return {"reservas": len(reservas), "visitantes": len(visitantes)}


# --------------------------------------------------------------------------- #
# Áreas e apartamentos (somente leitura, direto dos arquivos de dados)
# --------------------------------------------------------------------------- #
def listar_areas() -> list[dict[str, Any]]:
    return _ler_json("areas.json")


def obter_area(area_id: str) -> dict[str, Any] | None:
    return next((a for a in listar_areas() if a["id"] == area_id), None)


def apartamento_existe(numero: str) -> bool:
    return any(str(a["numero"]) == str(numero) for a in _ler_json("apartamentos.json"))


# --------------------------------------------------------------------------- #
# Reservas
# --------------------------------------------------------------------------- #
def data_ocupada(area: str, data: str) -> bool:
    """Só diz se existe reserva ativa. Nunca devolve dono ou código."""
    with conexao() as conn:
        row = conn.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
            (area, data),
        ).fetchone()
    return row is not None


def _novo_codigo(conn: sqlite3.Connection) -> str:
    """Gera e registra um código inédito dentro da transação corrente."""
    while True:
        codigo = f"RSV-{uuid.uuid4().hex[:8].upper()}"
        try:
            conn.execute("INSERT INTO codigos_emitidos (codigo) VALUES (?)", (codigo,))
            return codigo
        except sqlite3.IntegrityError:
            continue  # colisão (improvável): tenta outro código


def _gravar_reserva(conn: sqlite3.Connection, apartamento: str, area: str, data: str) -> str | None:
    """Grava a reserva dentro de uma transação já aberta.

    Garantia 5: a exclusividade é decidida pelo índice único
    `ux_reservas_area_data_ativa` no instante do INSERT. Se outra reserva
    ativa entrou antes, o SQLite levanta IntegrityError e devolvemos None
    (resposta normal de "data ocupada", nunca erro de servidor).
    """
    conn.execute("SAVEPOINT gravar_reserva")
    try:
        codigo = _novo_codigo(conn)
        conn.execute(
            "INSERT INTO reservas (codigo, apartamento, area, data, status, criada_em) "
            "VALUES (?, ?, ?, ?, 'ativa', ?)",
            (codigo, apartamento, area, data, _agora()),
        )
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK TO SAVEPOINT gravar_reserva")
        conn.execute("RELEASE SAVEPOINT gravar_reserva")
        return None
    conn.execute("RELEASE SAVEPOINT gravar_reserva")
    return codigo


def criar_reserva(apartamento: str, area: str, data: str) -> str | None:
    """Cria reserva (usado para áreas sem taxa). Devolve o código ou None se ocupada."""
    with transacao() as conn:
        return _gravar_reserva(conn, apartamento, area, data)


def cancelar_reserva(apartamento: str, area: str, data: str) -> str | None:
    """Cancela a reserva ativa DO apartamento informado. None se não houver.

    O filtro por apartamento está no próprio UPDATE: reserva de outro
    apartamento simplesmente não é encontrada, e nada sobre ela é revelado.
    """
    with transacao() as conn:
        row = conn.execute(
            "UPDATE reservas SET status = 'cancelada' "
            "WHERE apartamento = ? AND area = ? AND data = ? AND status = 'ativa' "
            "RETURNING codigo",
            (apartamento, area, data),
        ).fetchone()
    return row["codigo"] if row else None


def listar_reservas(apartamento: str) -> list[dict[str, str]]:
    with conexao() as conn:
        rows = conn.execute(
            "SELECT codigo, area, data FROM reservas "
            "WHERE apartamento = ? AND status = 'ativa' ORDER BY data, area",
            (str(apartamento),),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Visitantes
# --------------------------------------------------------------------------- #
def _gravar_visitante(conn: sqlite3.Connection, apartamento: str, nome: str, data: str) -> None:
    conn.execute(
        "INSERT INTO visitantes (apartamento, nome, data, criada_em) VALUES (?, ?, ?, ?)",
        (apartamento, nome, data, _agora()),
    )


def listar_visitantes(apartamento: str) -> list[dict[str, str]]:
    with conexao() as conn:
        rows = conn.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, id",
            (str(apartamento),),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Confirmações pendentes (Garantia 1)
# --------------------------------------------------------------------------- #
def _confirmacao_publica(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "acao": row["action_type"], "detalhes": json.loads(row["details"])}


def criar_confirmacao(session_id: str, apartamento: str, acao: str, detalhes: dict[str, Any]) -> dict[str, Any]:
    """Registra uma ação pendente. Se já existe uma idêntica pendente na sessão, reaproveita."""
    detalhes_json = json.dumps(detalhes, ensure_ascii=False, sort_keys=True)
    with transacao() as conn:
        existente = conn.execute(
            "SELECT * FROM pending_confirmations "
            "WHERE session_id = ? AND action_type = ? AND details = ? AND status = 'pending'",
            (session_id, acao, detalhes_json),
        ).fetchone()
        if existente:
            return _confirmacao_publica(existente)
        conf_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO pending_confirmations "
            "(id, session_id, apartamento, action_type, details, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (conf_id, session_id, apartamento, acao, detalhes_json, _agora()),
        )
        row = conn.execute("SELECT * FROM pending_confirmations WHERE id = ?", (conf_id,)).fetchone()
    return _confirmacao_publica(row)


def listar_confirmacoes_pendentes(session_id: str) -> list[dict[str, Any]]:
    with conexao() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_confirmations WHERE session_id = ? AND status = 'pending' "
            "ORDER BY created_at",
            (session_id,),
        ).fetchall()
    return [_confirmacao_publica(r) for r in rows]


def responder_confirmacao(session_id: str, conf_id: str, confirmado: bool) -> dict[str, Any] | None:
    """Responde uma confirmação pendente desta sessão, de forma atômica.

    Devolve None quando não existe confirmação PENDENTE com esse id nesta
    sessão (id inexistente, de outra sessão ou já respondido) -> HTTP 409.

    Leitura do status, execução da ação e mudança de status acontecem na
    mesma transação BEGIN IMMEDIATE: a ação executa no máximo uma vez.
    """
    with transacao() as conn:
        row = conn.execute(
            "SELECT * FROM pending_confirmations WHERE id = ? AND session_id = ? AND status = 'pending'",
            (conf_id, session_id),
        ).fetchone()
        if row is None:
            return None

        acao = row["action_type"]
        detalhes = json.loads(row["details"])
        apartamento = row["apartamento"]  # gravado pelo sistema a partir da sessão
        resultado: dict[str, Any] = {"id": conf_id, "acao": acao, "detalhes": detalhes}

        if not confirmado:
            status = "denied"
            resultado["status"] = "negada"
        elif acao == "reserva":
            codigo = _gravar_reserva(conn, apartamento, detalhes["area"], detalhes["data"])
            if codigo:
                status = "approved"
                resultado.update(status="executada", codigo=codigo)
            else:
                status = "failed"
                resultado["status"] = "data_ocupada"
        elif acao == "visitante":
            _gravar_visitante(conn, apartamento, detalhes["nome"], detalhes["data"])
            status = "approved"
            resultado["status"] = "executada"
        else:  # pragma: no cover - protegido pelo CHECK da tabela
            raise ValueError(f"Ação desconhecida: {acao}")

        conn.execute(
            "UPDATE pending_confirmations SET status = ?, resultado = ?, responded_at = ? WHERE id = ?",
            (status, json.dumps(resultado, ensure_ascii=False), _agora(), conf_id),
        )
    return resultado
