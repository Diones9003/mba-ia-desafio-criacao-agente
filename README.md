# Assistente do Residencial Aurora (Google ADK 2.13.0)

## Arquitetura

API FastAPI (`app/main.py`) na porta 8000 + assistente Google ADK com um agente principal e três especialistas, acionados por **transferência (sub_agents)** — cada especialista tem só as tools do seu assunto, o que reduz o contexto e o risco de uma tool errada ser chamada.

| Agente | Arquivo | Responsabilidade | Como é acionado |
|---|---|---|---|
| `assistente_aurora` (principal) | `app/agents/principal.py` | Entende o pedido e transfere. Não tem tools de dados nem o regulamento. | Recebe toda mensagem nova (Runner) |
| `reservas_agent` | `app/agents/reservas.py` | `listar_areas`, `verificar_disponibilidade`, `solicitar_reserva`, `cancelar_reserva`, `listar_minhas_reservas` | `transfer_to_agent` pelo principal |
| `visitantes_agent` | `app/agents/visitantes.py` | `autorizar_visitante`, `listar_meus_visitantes` | `transfer_to_agent` pelo principal |
| `regulamento_agent` | `app/agents/regulamento.py` | `buscar_no_regulamento` (devolve só o trecho relevante) | `transfer_to_agent` pelo principal |

Dados: `aurora.db` (SQLite: reservas, visitantes, confirmações) em `app/database.py`; sessões ADK em `sessoes.db` via `SqliteSessionService` (`app/agent_runner.py`). Rotas: `app/routers/`.

## Garantias

1. **Cobrança ou acesso só com confirmação** — `app/agents/reservas.py` (`solicitar_reserva`: taxa > 0 chama `db.criar_confirmacao`, nunca grava) e `app/agents/visitantes.py` (`autorizar_visitante`: sempre pendente). Execução só em `app/database.py::responder_confirmacao`, chamada apenas por `app/routers/confirmacoes.py`. Ela busca `status='pending'` por `id` **e** `session_id` dentro de `BEGIN IMMEDIATE`, executa e muda o status na mesma transação; senão devolve `None` → HTTP 409. Nenhuma tool executa a ação, então nenhum texto do morador consegue aprová-la. `confirmacoes_pendentes` é lido do banco (`app/routers/schemas.py::montar_resposta`).
2. **Sessão pertence a um apartamento** — `app/agent_runner.py::criar_sessao` grava `state={"apartamento": ...}`; `app/agents/_sessao.py::apartamento_da_sessao` é a única fonte usada pelas tools, que **não têm parâmetro de apartamento**. `verificar_disponibilidade` devolve só `livre/ocupada`; `database.cancelar_reserva` filtra `WHERE apartamento = ?` no próprio `UPDATE` e responde igual exista ou não reserva alheia.
3. **Nada se perde no reinício** — sessões/eventos em `sessoes.db` (`SqliteSessionService` em `app/agent_runner.py`); reservas, visitantes e pendências em `aurora.db`. `init_db()` só semeia na primeira execução (tabela `meta`).
4. **Regulamento consultado, não carregado** — `app/agents/regulamento.py::buscar_no_regulamento` divide o arquivo em capítulos (`##`) e artigos, escolhe **um** capítulo e devolve no máximo 3 artigos dele. O principal (`principal.py`) não recebe o regulamento.
5. **Dois moradores, uma reserva** — `app/database.py`: índice `ux_reservas_area_data_ativa` (`UNIQUE (area, data) WHERE status='ativa'`) + `_gravar_reserva` com `SAVEPOINT` que trata `sqlite3.IntegrityError` como “data ocupada” (resposta 200 normal). A exclusividade é decidida pelo SQLite no INSERT. Códigos `RSV-XXXXXXXX` são registrados em `codigos_emitidos` (nunca limpa), então não se repetem.

## Como rodar

Pré-requisitos: [uv](https://docs.astral.sh/uv/) (instala Python 3.12 sozinho) e chave do Google AI Studio.

```bash
cp .env.example .env        # preencha GOOGLE_API_KEY; GEMINI_MODEL é opcional (padrão gemini-2.5-flash)
uv sync
uv run python scripts/restore.py                          # restaura reservas/visitantes iniciais
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000    # sobe a API
```

Variáveis: `GOOGLE_API_KEY` (obrigatória), `GEMINI_MODEL` (opcional — confira os modelos ativos no AI Studio). Nenhum serviço externo: tudo em SQLite local. A restauração limpa reservas, visitantes e confirmações pendentes, e **preserva as sessões**.
