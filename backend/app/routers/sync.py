"""Endpoints de sincronizacion (disparo manual o por cron)."""
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import settings
from app.sync import sync_rango, sync_referencias

log = logging.getLogger("sync.router")
router = APIRouter(prefix="/api/sync", tags=["sync"])


def _check_secret(*candidatos: Optional[str]):
    """Valida el secreto contra SYNC_SECRET. Acepta varios portadores.

    Vercel Cron envia `Authorization: Bearer <CRON_SECRET>`; tambien se acepta
    el header `x-sync-secret` y el query param `secret` para disparo manual.
    """
    if not settings.SYNC_SECRET:
        raise HTTPException(503, "SYNC_SECRET no configurado en el servidor")
    vals = set()
    for c in candidatos:
        if not c:
            continue
        vals.add(c)
        if c.lower().startswith("bearer "):
            vals.add(c[7:].strip())
    if settings.SYNC_SECRET not in vals:
        raise HTTPException(401, "Secreto invalido")


@router.post("")
def disparar_sync(
    desde: Optional[str] = Query(None, description="yyyy-MM-dd; default = ayer"),
    hasta: Optional[str] = Query(None, description="yyyy-MM-dd; default = hoy"),
    fuentes: str = Query("CHESS,GESCOM", description="CHESS, GESCOM o ambas"),
    referencias: bool = Query(False, description="refrescar clientes/rutas/articulos antes"),
    x_sync_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    """Sincroniza rechazos de un rango de fechas. Protegido por SYNC_SECRET.

    El cron diario llama: POST /api/sync?referencias=true (rango por defecto
    ayer..hoy) con el header x-sync-secret.
    """
    _check_secret(x_sync_secret, secret)
    desde = desde or (date.today() - timedelta(days=1)).isoformat()
    hasta = hasta or date.today().isoformat()
    fs = [x.strip().upper() for x in fuentes.split(",") if x.strip()]

    ref_resumen = sync_referencias() if referencias else None
    total = sync_rango(desde, hasta, fs)
    log.info("Sync %s..%s fuentes=%s -> %s", desde, hasta, fs, total)
    return {"ok": True, "desde": desde, "hasta": hasta, "fuentes": fs,
            "rechazos": total, "referencias": ref_resumen}


@router.get("/cron")
def cron_sync(
    dias: int = Query(5, ge=1, le=31, description="ventana movil de dias hacia atras"),
    referencias: bool = Query(True),
    authorization: Optional[str] = Header(None),
    x_sync_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    """Endpoint para Vercel Cron (GET). Sincroniza una ventana movil.

    Se usa una ventana de varios dias porque un rechazo puede registrarse
    dias despues del pedido. Vercel Cron autentica con
    `Authorization: Bearer <CRON_SECRET>` (CRON_SECRET == SYNC_SECRET).
    """
    _check_secret(authorization, x_sync_secret, secret)
    desde = (date.today() - timedelta(days=dias)).isoformat()
    hasta = date.today().isoformat()
    ref_resumen = sync_referencias() if referencias else None
    total = sync_rango(desde, hasta, ["CHESS", "GESCOM"])
    log.info("Cron sync %s..%s -> %s", desde, hasta, total)
    return {"ok": True, "desde": desde, "hasta": hasta,
            "rechazos": total, "referencias": ref_resumen}


@router.post("/refrescar")
def refrescar_sync(
    dias: int = Query(7, ge=1, le=31, description="ventana movil de dias hacia atras"),
):
    """Sync de la ventana reciente disparado desde el boton de la UI.

    Sin secreto, igual que `/api/mapeo`: se protege a nivel Vercel. No
    refresca referencias (eso tarda ~3 min); solo trae rechazos recientes.
    """
    desde = (date.today() - timedelta(days=dias)).isoformat()
    hasta = date.today().isoformat()
    total = sync_rango(desde, hasta, ["CHESS", "GESCOM"])
    log.info("Refrescar (UI) %s..%s -> %s", desde, hasta, total)
    return {"ok": True, "desde": desde, "hasta": hasta, "rechazos": total}


@router.post("/referencias")
def disparar_referencias(
    x_sync_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    """Refresca solo las tablas de referencia (clientes, rutas, articulos)."""
    _check_secret(x_sync_secret, secret)
    return {"ok": True, "referencias": sync_referencias()}
