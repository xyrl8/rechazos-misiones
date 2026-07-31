"""Endpoints de sincronizacion (disparo manual o por cron)."""
import json
import logging
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.config import settings
from app.db import get_conn
from app.sync import sync_rango, sync_referencias, sync_ventas_rango

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
    desde: Optional[str] = Query(None, description="yyyy-MM-dd; con `hasta`, sincroniza ese rango"),
    hasta: Optional[str] = Query(None, description="yyyy-MM-dd"),
):
    """Sync disparado desde el boton de la UI.

    Sin secreto, igual que `/api/mapeo`: se protege a nivel Vercel. No
    refresca referencias (eso tarda ~3 min); solo trae rechazos.

    Por defecto sincroniza la ventana movil de `dias` hacia atras. Si llegan
    `desde` y `hasta`, sincroniza ese rango (el periodo elegido en los
    filtros). El rango se limita a 45 dias: para backfills mas largos hay que
    usar /run, que responde en streaming y no se corta a los ~300s de Vercel.
    """
    if desde and hasta:
        d, h = desde, hasta
        if (date.fromisoformat(h) - date.fromisoformat(d)).days > 45:
            raise HTTPException(
                status_code=400,
                detail="Rango mayor a 45 dias: usar el sync manual por tramos.",
            )
    else:
        d = (date.today() - timedelta(days=dias)).isoformat()
        h = date.today().isoformat()
    total = sync_rango(d, h, ["CHESS", "GESCOM"])
    log.info("Refrescar (UI) %s..%s -> %s", d, h, total)
    return {"ok": True, "desde": d, "hasta": h, "rechazos": total}


@router.post("/referencias")
def disparar_referencias(
    x_sync_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    """Refresca solo las tablas de referencia (clientes, rutas, articulos)."""
    _check_secret(x_sync_secret, secret)
    return {"ok": True, "referencias": sync_referencias()}


@router.post("/init-db")
def init_db(
    x_sync_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    """Aplica `schema.sql` a la base. Idempotente (CREATE TABLE IF NOT EXISTS).

    Inicializa la base productiva tras el primer deploy, cuando no hay acceso
    directo a la DB para correr `scripts/init_db.py`. Protegido por SYNC_SECRET.
    """
    _check_secret(x_sync_secret, secret)
    schema = Path(__file__).resolve().parents[1] / "schema.sql"
    sql = schema.read_text(encoding="utf-8")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
    finally:
        conn.close()
    log.info("Schema aplicado via /init-db")
    return {"ok": True, "schema": "aplicado"}


@router.post("/backfill-hl")
def backfill_hl(
    x_sync_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    """Rellena `hl_rechazados` del histórico SIN volver a consultar Chess.

    El `raw` de cada rechazo de Chess ya guarda `unimedtotal` (el hectolitraje
    de la línea), así que el HL histórico se reconstruye con un UPDATE. De paso
    arma el maestro `ref_articulos.hl_bulto`, que es lo que permite valorizar en
    HL los rechazos de GESCOM (no traen unidad de medida).

    Idempotente. No toca el denominador (`ventas_dia`): eso necesita el sync
    completo del período, que sí baja las líneas de venta.
    """
    _check_secret(x_sync_secret, secret)
    conn = get_conn()
    out = {}
    try:
        cur = conn.cursor()
        # HL de los rechazos de Chess, prorrateado igual que el importe.
        cur.execute("""
            UPDATE rechazos SET hl_rechazados = ROUND(
                     ABS((raw->>'unimedtotal')::numeric) * ABS(bultos_rechazados)
                     / NULLIF(ABS((raw->>'cantidadesTotal')::numeric), 0), 5)
             WHERE fuente = 'CHESS'
               AND raw ? 'unimedtotal' AND raw ? 'cantidadesTotal'
               AND (raw->>'cantidadesTotal')::numeric <> 0""")
        out["chess"] = cur.rowcount
        # Maestro HL/bulto por artículo (se queda con el dato más reciente).
        cur.execute("""
            INSERT INTO ref_articulos (fuente, id_articulo, descripcion, hl_bulto)
            SELECT DISTINCT ON (id_articulo) 'CHESS', id_articulo, articulo,
                   ABS((raw->>'unimedtotal')::numeric
                       / NULLIF((raw->>'cantidadesTotal')::numeric, 0))
              FROM rechazos
             WHERE fuente = 'CHESS' AND id_articulo <> ''
               AND raw ? 'unimedtotal' AND raw ? 'cantidadesTotal'
               AND (raw->>'cantidadesTotal')::numeric <> 0
               AND (raw->>'unimedtotal')::numeric <> 0
             ORDER BY id_articulo, fecha DESC
            ON CONFLICT (fuente, id_articulo) DO UPDATE
               SET hl_bulto = EXCLUDED.hl_bulto, updated_at = now()""")
        out["articulos"] = cur.rowcount
        # GESCOM: HL derivado del maestro por código de artículo.
        cur.execute("""
            UPDATE rechazos r
               SET hl_rechazados = ROUND(ABS(r.bultos_rechazados) * a.hl_bulto, 5)
              FROM ref_articulos a
             WHERE r.fuente = 'GESCOM' AND a.fuente = 'CHESS'
               AND a.id_articulo = r.id_articulo AND a.hl_bulto IS NOT NULL""")
        out["gescom"] = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    log.info("Backfill HL -> %s", out)
    return {"ok": True, "actualizados": out}


def _stream(trabajo):
    """Ejecuta `trabajo()` en un hilo y va emitiendo heartbeats.

    Vercel corta las respuestas NO-streaming a ~300s aunque la función pueda
    correr hasta 800s; mandando un byte cada 5s la conexión se mantiene viva.
    La última línea es el JSON con el resultado.
    """
    def gen():
        resultado = {}

        def run():
            try:
                resultado["ok"] = True
                resultado["resultado"] = trabajo()
            except Exception as e:  # noqa: BLE001
                resultado["ok"] = False
                resultado["error"] = repr(e)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        while t.is_alive():
            yield "."
            time.sleep(5)
        t.join()
        yield "\n" + json.dumps(resultado) + "\n"

    return StreamingResponse(gen(), media_type="text/plain")


@router.post("/ventas")
def sync_ventas(
    desde: str = Query(..., description="yyyy-MM-dd"),
    hasta: str = Query(..., description="yyyy-MM-dd"),
    fuentes: str = Query("CHESS,GESCOM"),
    x_sync_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    """Backfill del denominador (`ventas_dia`) de un rango, en streaming.

    NO toca la tabla `rechazos`: completa el histórico del % sin reescribir los
    rechazos ya publicados. Un día de Chess tarda ~30s, así que conviene pedir
    tramos de ~15 días por invocación (límite de 800s de la función).
    """
    _check_secret(x_sync_secret, secret)
    fs = [x.strip().upper() for x in fuentes.split(",") if x.strip()]
    log.info("Backfill ventas %s..%s fuentes=%s", desde, hasta, fs)
    return _stream(lambda: sync_ventas_rango(desde, hasta, fs))


@router.post("/run")
def run_stream(
    desde: Optional[str] = Query(None, description="yyyy-MM-dd; default = ayer"),
    hasta: Optional[str] = Query(None, description="yyyy-MM-dd; default = hoy"),
    fuentes: str = Query("CHESS,GESCOM"),
    referencias: bool = Query(False),
    x_sync_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    """Sync con respuesta en streaming. Emite un heartbeat cada 5s mientras
    corre para que la conexion no se corte: Vercel limita las respuestas
    NO-streaming a ~300s, aunque la funcion pueda correr hasta 800s. Util para
    el sync de referencias (pagina ~2.500 clientes) y el backfill inicial.

    La ultima linea es el JSON con el resultado.
    """
    _check_secret(x_sync_secret, secret)
    d = desde or (date.today() - timedelta(days=1)).isoformat()
    h = hasta or date.today().isoformat()
    fs = [x.strip().upper() for x in fuentes.split(",") if x.strip()]

    def trabajo():
        out = {"desde": d, "hasta": h, "fuentes": fs}
        if referencias:
            out["referencias"] = sync_referencias()
        out["rechazos"] = sync_rango(d, h, fs)
        return out

    def gen():
        resultado = {}

        def run():
            try:
                resultado["ok"] = True
                resultado["resultado"] = trabajo()
            except Exception as e:  # noqa: BLE001
                resultado["ok"] = False
                resultado["error"] = repr(e)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        while t.is_alive():
            yield "."
            time.sleep(5)
        t.join()
        log.info("Sync /run -> %s", resultado.get("ok"))
        yield "\n" + json.dumps(resultado) + "\n"

    return StreamingResponse(gen(), media_type="text/plain")
