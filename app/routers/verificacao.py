"""Rotas de verificação: leem os dados do condomínio direto, sem passar pelo modelo."""

from fastapi import APIRouter

from app import database as db

router = APIRouter(prefix="/apartamentos", tags=["verificacao"])


@router.get("/{numero}/reservas")
def reservas_do_apartamento(numero: str) -> list[dict[str, str]]:
    return db.listar_reservas(numero)


@router.get("/{numero}/visitantes")
def visitantes_do_apartamento(numero: str) -> list[dict[str, str]]:
    return db.listar_visitantes(numero)
