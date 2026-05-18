"""Apartado de administración: mapeo manual de clientes a promotores.

Sirve para los clientes de GESCOM que no matchean automáticamente con el
listado de Chess y quedan como mostrador (excluidos). Al asignarles un promotor
real, el cliente se "rescata": deja de estar excluido y hereda el supervisor
del promotor.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import get_conn, dict_cursor
from app.sync import _norm

router = APIRouter(prefix="/api/mapeo", tags=["mapeo"])


class MapeoIn(BaseModel):
    cliente: str
    vendedor: str  # promotor de Chess


def _clientes_gescom_norm(cur):
    """Devuelve [(cliente, nombre_norm)] de los rechazos GESCOM."""
    cur.execute("SELECT DISTINCT cliente FROM rechazos WHERE fuente = 'GESCOM'")
    return [(c, _norm(c)) for (c,) in cur.fetchall()]


def _supervisor_de_promotor(cur):
    """Mapa promotor -> supervisor, derivado de los comprobantes de Chess."""
    cur.execute("""SELECT DISTINCT ON (vendedor) vendedor, supervisor
                   FROM ref_cliente_supervisor
                   WHERE vendedor <> ''
                   ORDER BY vendedor, ultima_fecha DESC""")
    return {v: s for (v, s) in cur.fetchall()}


@router.get("")
def listar():
    """Mapeos cargados + clientes GESCOM sin resolver + promotores válidos."""
    conn = get_conn()
    try:
        cur = dict_cursor(conn)
        cur.execute("""SELECT nombre_norm, cliente, vendedor, supervisor, updated_at
                       FROM cliente_supervisor_manual ORDER BY cliente""")
        mapeos = cur.fetchall()

        # Clientes GESCOM excluidos por ser mostrador sin match: los mapeables.
        cur.execute("""SELECT cliente, COUNT(*) lineas
                       FROM rechazos
                       WHERE fuente = 'GESCOM' AND excluido
                             AND motivo_exclusion = 'promotor'
                       GROUP BY cliente ORDER BY lineas DESC, cliente""")
        sin_resolver = cur.fetchall()

        cur.execute("""SELECT DISTINCT vendedor FROM rechazos
                       WHERE fuente = 'CHESS' AND NOT excluido AND vendedor <> ''
                       ORDER BY vendedor""")
        promotores = [r["vendedor"] for r in cur.fetchall()]
        return {"mapeos": mapeos, "sin_resolver": sin_resolver,
                "promotores": promotores}
    finally:
        conn.close()


@router.post("")
def guardar(body: MapeoIn):
    """Crea/actualiza un mapeo cliente→promotor y lo aplica de inmediato.

    El supervisor se deriva del promotor. Los rechazos GESCOM del cliente que
    estaban excluidos por mostrador dejan de estarlo.
    """
    cliente = (body.cliente or "").strip()
    vendedor = (body.vendedor or "").strip()
    if not cliente or not vendedor:
        raise HTTPException(400, "cliente y promotor son obligatorios")
    nn = _norm(cliente)
    if not nn:
        raise HTTPException(400, "nombre de cliente inválido")
    conn = get_conn()
    try:
        cur = conn.cursor()
        supervisor = _supervisor_de_promotor(cur).get(vendedor, "")
        cur.execute(
            """INSERT INTO cliente_supervisor_manual (nombre_norm, cliente, vendedor, supervisor)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (nombre_norm) DO UPDATE
                 SET cliente = EXCLUDED.cliente, vendedor = EXCLUDED.vendedor,
                     supervisor = EXCLUDED.supervisor, updated_at = now()""",
            (nn, cliente, vendedor, supervisor),
        )
        # Aplica sobre los rechazos GESCOM ya cargados: asigna promotor /
        # supervisor y los des-excluye si estaban como mostrador.
        afectados = [c for (c, n) in _clientes_gescom_norm(cur) if n == nn]
        filas = 0
        if afectados:
            cur.execute(
                """UPDATE rechazos
                   SET vendedor = %s, supervisor = %s,
                       excluido = CASE WHEN motivo_exclusion = 'promotor'
                                       THEN false ELSE excluido END,
                       motivo_exclusion = CASE WHEN motivo_exclusion = 'promotor'
                                               THEN '' ELSE motivo_exclusion END
                   WHERE fuente = 'GESCOM' AND cliente = ANY(%s)""",
                (vendedor, supervisor, afectados))
            filas = cur.rowcount
        conn.commit()
        return {"ok": True, "nombre_norm": nn, "vendedor": vendedor,
                "supervisor": supervisor, "filas_actualizadas": filas}
    finally:
        conn.close()


@router.delete("")
def borrar(nombre_norm: str):
    """Elimina un mapeo; los rechazos del cliente vuelven a mostrador excluido
    (el próximo sync los recalcula)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM cliente_supervisor_manual WHERE nombre_norm = %s",
                    (nombre_norm,))
        borrado = cur.rowcount
        afectados = [c for (c, n) in _clientes_gescom_norm(cur) if n == nombre_norm]
        if afectados:
            cur.execute(
                """UPDATE rechazos
                   SET excluido = true, motivo_exclusion = 'promotor',
                       vendedor = 'MOSTRADOR (GESCOM)',
                       supervisor = 'MOSTRADOR (GESCOM)'
                   WHERE fuente = 'GESCOM' AND cliente = ANY(%s)""",
                (afectados,))
        conn.commit()
        return {"ok": bool(borrado)}
    finally:
        conn.close()
