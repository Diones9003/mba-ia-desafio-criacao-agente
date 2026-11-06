"""Especialista do regulamento interno.

Garantia 4: o regulamento é CONSULTADO por uma tool, nunca carregado inteiro.
`buscar_no_regulamento` escolhe UM capítulo (o mais relevante para o tópico) e
devolve só os artigos mais relevantes desse capítulo. O resultado da tool é o
único trecho do regulamento que entra num evento da sessão, então nenhum evento
carrega capítulos que tratam de outros assuntos. Nenhum agente recebe o arquivo
nas instruções.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from google.adk.agents import LlmAgent

from app.config import GEMINI_MODEL, REGULAMENTO_PATH

MAX_ARTIGOS = 3

_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "pra", "com", "sem", "sobre", "e",
    "ou", "que", "qual", "quais", "quando", "como", "onde", "ate", "se", "ser", "eu",
    "meu", "minha", "posso", "pode", "podem", "ao", "aos", "ha", "tem", "ter", "e",
    "regra", "regras", "regulamento", "condominio", "horas", "hora", "sao", "esta",
    "isso", "esse", "essa", "este", "nao", "sim", "mais", "menos", "muito", "algum",
}

# Sinônimos comuns em perguntas que não aparecem literalmente no texto.
_SINONIMOS = {
    "cachorro": ["cao", "caes", "animal", "animais"],
    "cachorros": ["cao", "caes", "animal", "animais"],
    "gato": ["animal", "animais"],
    "pet": ["animal", "animais", "pet"],
    "barulho": ["ruido", "silencio", "som"],
    "festa": ["festas", "salao"],
    "lixo": ["residuos", "coleta", "lixo"],
    "carro": ["veiculo", "veiculos", "garagem"],
    "horario": ["funciona", "disponivel"],
    "visita": ["visitante", "visitantes"],
}


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def _radical(palavra: str) -> str:
    """Stemming bem simples: compara pelos 5 primeiros caracteres."""
    return palavra[:5] if len(palavra) > 5 else palavra


def _termos(texto: str) -> list[str]:
    return [_radical(p) for p in re.findall(r"[a-z0-9]+", _normalizar(texto)) if p not in _STOPWORDS and len(p) > 1]


def _termos_da_consulta(topico: str) -> set[str]:
    palavras = [p for p in re.findall(r"[a-z0-9]+", _normalizar(topico)) if p not in _STOPWORDS and len(p) > 1]
    expandidas = list(palavras)
    for p in palavras:
        expandidas.extend(_SINONIMOS.get(p, []))
    return {_radical(p) for p in expandidas}


@dataclass
class Capitulo:
    titulo: str
    artigos: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _capitulos() -> tuple[Capitulo, ...]:
    """Divide o regulamento em capítulos (##) e cada capítulo em artigos (**Art.)."""
    capitulos: list[Capitulo] = []
    atual: Capitulo | None = None
    artigo: list[str] = []

    def fechar_artigo() -> None:
        if atual is not None and artigo:
            atual.artigos.append("\n".join(artigo).strip())

    for linha in REGULAMENTO_PATH.read_text(encoding="utf-8").splitlines():
        if linha.startswith("## "):
            fechar_artigo()
            artigo = []
            atual = Capitulo(titulo=linha[3:].strip())
            capitulos.append(atual)
        elif atual is not None:
            if linha.startswith("**Art."):
                fechar_artigo()
                artigo = [linha]
            elif artigo:
                artigo.append(linha)
    fechar_artigo()
    return tuple(capitulos)


def _pontuar(termos_consulta: set[str], texto: str) -> int:
    termos = _termos(texto)
    return sum(1 for t in termos if t in termos_consulta)


def buscar_no_regulamento(topico: str) -> dict[str, Any]:
    """Busca no regulamento interno o trecho que trata de um tópico.

    Devolve apenas os artigos mais relevantes do capítulo mais relevante,
    nunca o regulamento inteiro.

    Args:
        topico: palavras-chave do assunto (ex.: "piscina horário domingo").
    """
    consulta = _termos_da_consulta(topico)
    if not consulta:
        return {"encontrado": False, "mensagem": "Informe palavras-chave do assunto."}

    melhor: tuple[int, Capitulo] | None = None
    for cap in _capitulos():
        pontos = 5 * _pontuar(consulta, cap.titulo) + sum(_pontuar(consulta, a) for a in cap.artigos)
        if pontos and (melhor is None or pontos > melhor[0]):
            melhor = (pontos, cap)
    if melhor is None:
        return {"encontrado": False, "mensagem": "O regulamento não trata desse assunto."}

    capitulo = melhor[1]
    pontuados = [(_pontuar(consulta, a), i, a) for i, a in enumerate(capitulo.artigos)]
    relevantes = sorted((p for p in pontuados if p[0] > 0), key=lambda p: -p[0])[:MAX_ARTIGOS]
    if not relevantes:  # só o título bateu: devolve o primeiro artigo do capítulo
        relevantes = pontuados[:1]
    artigos = [a for _, _, a in sorted(relevantes, key=lambda p: p[1])]  # ordem original
    return {"encontrado": True, "capitulo": capitulo.titulo, "trecho": "\n\n".join(artigos)}


INSTRUCAO = """
Você é o especialista no regulamento interno do Residencial Aurora.
Para qualquer dúvida sobre regras, chame buscar_no_regulamento com poucas
palavras-chave do assunto (ex.: "piscina horário domingo"). Responda somente
com base no trecho devolvido, citando o artigo. Se o trecho não responder,
tente outra busca com palavras diferentes; se ainda assim não houver
informação, diga que o regulamento não trata do assunto e sugira falar com a
administração. Nunca invente regras. Responda em português, de forma breve.
Se o pedido não for sobre o regulamento, transfira de volta para o agente principal.
"""

regulamento_agent = LlmAgent(
    name="regulamento_agent",
    model=GEMINI_MODEL,
    description="Especialista que responde dúvidas sobre o regulamento interno consultando só o trecho relevante.",
    instruction=INSTRUCAO,
    tools=[buscar_no_regulamento],
)
