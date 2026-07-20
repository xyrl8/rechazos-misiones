"""Comentarios sobre rechazos — estilo HILO.

Cada "hilo" se ancla a un evento de rechazo tal como se muestra en el detalle
del tablero: fecha + fuente + cliente. La clave `thread_key` es estable entre
syncs (ver `schema.sql`). Los comentarios son inmutables (no hay endpoint de
borrado): a lo sumo el hilo se marca como resuelto, y se puede reabrir.

Endpoints SIN auth en v1, igual que `/api/mapeo` → se protege a nivel Vercel.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.db import get_conn, dict_cursor

router = APIRouter(prefix="/api/comentarios", tags=["comentarios"])


def thread_key(fecha: str, fuente: str, id_cliente) -> str:
    """Clave estable del hilo. Debe coincidir con la del frontend
    (`threadKey` en `lib/format.js`)."""
    fec = (fecha or "")[:10]
    fte = (fuente or "").upper()
    idc = "" if id_cliente is None else str(id_cliente)
    return f"{fec}|{fte}|{idc}"


class ComentarioIn(BaseModel):
    fecha: str
    fuente: str
    id_cliente: Optional[str] = None
    cliente: str = ""
    comentario: str
    autor: str = ""


class ResolverIn(BaseModel):
    thread_key: str
    resuelto: bool = True
    autor: str = ""


def _hilo(cur, tk: str):
    """Devuelve el hilo (con sus comentarios) o None."""
    cur.execute(
        """SELECT thread_key, fecha, fuente, id_cliente, cliente,
                  resuelto, resuelto_at, resuelto_por, created_at, updated_at
           FROM rechazo_hilos WHERE thread_key = %s""",
        (tk,),
    )
    h = cur.fetchone()
    if not h:
        return None
    cur.execute(
        """SELECT id, comentario, autor, created_at
           FROM rechazo_comentarios
           WHERE thread_key = %s ORDER BY created_at, id""",
        (tk,),
    )
    h["comentarios"] = cur.fetchall()
    return h


@router.get("")
def listar(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
):
    """Hilos del período (con sus comentarios), indexados por `thread_key`.

    El frontend cruza esta respuesta con las filas del detalle para mostrar el
    estado de cada hilo y abrir el modal. Si no se pasan fechas, devuelve todo.
    """
    where, params = [], []
    if fecha_desde:
        where.append("h.fecha >= %s")
        params.append(fecha_desde)
    if fecha_hasta:
        where.append("h.fecha <= %s")
        params.append(fecha_hasta)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = get_conn()
    try:
        cur = dict_cursor(conn)
        cur.execute(
            f"""SELECT h.thread_key, h.fecha, h.fuente, h.id_cliente, h.cliente,
                       h.resuelto, h.resuelto_at, h.resuelto_por,
                       h.created_at, h.updated_at,
                       COUNT(c.id)        AS n_comentarios,
                       MAX(c.created_at)  AS ultimo_at
                FROM rechazo_hilos h
                LEFT JOIN rechazo_comentarios c ON c.thread_key = h.thread_key
                {clause}
                GROUP BY h.thread_key
                ORDER BY h.fecha DESC""",
            params,
        )
        hilos = cur.fetchall()
        return {"hilos": {h["thread_key"]: h for h in hilos}}
    finally:
        conn.close()


@router.get("/hilo")
def detalle(thread_key: str = Query(...)):
    """Un hilo completo con todos sus comentarios."""
    conn = get_conn()
    try:
        cur = dict_cursor(conn)
        h = _hilo(cur, thread_key)
        if not h:
            return {"hilo": None}
        return {"hilo": h}
    finally:
        conn.close()


@router.post("")
def comentar(body: ComentarioIn):
    """Agrega un comentario al hilo del evento (lo crea si no existe).

    No cambia el estado `resuelto`: para eso está `/resolver`.
    """
    texto = (body.comentario or "").strip()
    if not texto:
        raise HTTPException(400, "el comentario no puede estar vacío")
    try:
        fec = date.fromisoformat((body.fecha or "")[:10])
    except ValueError:
        raise HTTPException(400, "fecha inválida")
    fuente = (body.fuente or "").upper()
    if fuente not in ("CHESS", "GESCOM"):
        raise HTTPException(400, "fuente inválida")
    idc = None if body.id_cliente in (None, "") else str(body.id_cliente)
    tk = thread_key(body.fecha, fuente, idc)
    autor = (body.autor or "").strip()
    conn = get_conn()
    try:
        cur = dict_cursor(conn)
        cur.execute(
            """INSERT INTO rechazo_hilos (thread_key, fecha, fuente, id_cliente, cliente)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (thread_key) DO UPDATE
                 SET cliente = CASE WHEN EXCLUDED.cliente <> '' THEN EXCLUDED.cliente
                                    ELSE rechazo_hilos.cliente END,
                     updated_at = now()""",
            (tk, fec, fuente, idc, (body.cliente or "").strip()),
        )
        cur.execute(
            """INSERT INTO rechazo_comentarios (thread_key, comentario, autor)
               VALUES (%s, %s, %s)""",
            (tk, texto, autor),
        )
        conn.commit()
        return {"ok": True, "hilo": _hilo(cur, tk)}
    finally:
        conn.close()


@router.post("/resolver")
def resolver(body: ResolverIn):
    """Marca el hilo como resuelto (o lo reabre). No borra nada."""
    tk = (body.thread_key or "").strip()
    if not tk:
        raise HTTPException(400, "thread_key requerido")
    autor = (body.autor or "").strip()
    conn = get_conn()
    try:
        cur = dict_cursor(conn)
        if body.resuelto:
            cur.execute(
                """UPDATE rechazo_hilos
                   SET resuelto = true, resuelto_at = now(),
                       resuelto_por = %s, updated_at = now()
                   WHERE thread_key = %s""",
                (autor, tk),
            )
        else:
            cur.execute(
                """UPDATE rechazo_hilos
                   SET resuelto = false, resuelto_at = NULL,
                       resuelto_por = '', updated_at = now()
                   WHERE thread_key = %s""",
                (tk,),
            )
        if cur.rowcount == 0:
            raise HTTPException(404, "hilo inexistente")
        conn.commit()
        return {"ok": True, "hilo": _hilo(cur, tk)}
    finally:
        conn.close()
