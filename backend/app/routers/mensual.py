"""Resumen mensual del rechazo: bultos, hectolitros, valorizado y % sobre venta.

Es la solapa 2 del tablero (la 1 es el detalle operativo para la matinal). Acá
el foco es la evolución: cómo viene el rechazo mes a mes contra la venta del
mismo período, y qué motivos lo explican.

El % se calcula contra `ventas_dia` (venta BRUTA facturada, antes de la nota de
crédito). Numerador y denominador comparten los filtros de fuente, período,
supervisor y promotor; el filtro por MOTIVO aplica solo al numerador (la
pregunta es "cuánto de la venta se rechazó por este motivo").

⚠️ El numerador excluye los rechazos marcados `excluido` (devoluciones por
trámite, refuerzos, mostrador) igual que el resto del tablero; el denominador es
la venta completa. Es la lectura conservadora: el % nunca queda inflado.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query

from app.db import get_conn, dict_cursor

router = APIRouter(prefix="/api", tags=["mensual"])

# Unidades que publica el endpoint. `col` = columna del numerador (rechazos),
# `venta` = columna del denominador (ventas_dia).
UNIDADES = [("bultos", "bultos_rechazados", "bultos"),
            ("hl", "hl_rechazados", "hl"),
            ("importe", "importe_rechazado", "importe")]


def _where_rechazos(fuente, desde, hasta, supervisor, vendedor, motivo):
    where, params = ["excluido = false", "fecha >= %s", "fecha <= %s"], [desde, hasta]
    if fuente and fuente.upper() != "TODO":
        where.append("fuente = %s")
        params.append(fuente.upper())
    if supervisor:
        where.append("supervisor = %s")
        params.append(supervisor)
    if vendedor:
        where.append("vendedor = %s")
        params.append(vendedor)
    if motivo:
        where.append("motivo = %s")
        params.append(motivo)
    return " WHERE " + " AND ".join(where), params


def _where_ventas(fuente, desde, hasta, supervisor, vendedor):
    """Denominador: mismos cortes, SIN el filtro de motivo (la venta no tiene)."""
    where, params = ["fecha >= %s", "fecha <= %s"], [desde, hasta]
    if fuente and fuente.upper() != "TODO":
        where.append("fuente = %s")
        params.append(fuente.upper())
    if supervisor:
        where.append("supervisor = %s")
        params.append(supervisor)
    if vendedor:
        where.append("vendedor = %s")
        params.append(vendedor)
    return " WHERE " + " AND ".join(where), params


def _pct(num, den):
    """% redondeado a 2 decimales. Sin venta cargada devuelve None (no 0): la
    diferencia entre "no se rechazó nada" y "no hay denominador" importa."""
    if den in (None, 0):
        return None
    return round(float(num or 0) * 100.0 / float(den), 2)


def _con_pct(fila):
    """Agrega pct_bultos / pct_hl / pct_importe a una fila que ya trae ambos lados."""
    for clave, _col, vcol in UNIDADES:
        fila[f"pct_{clave}"] = _pct(fila.get(clave), fila.get(f"venta_{vcol}"))
    return fila


@router.get("/mensual")
def mensual(
    fuente: str = Query("TODO"),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    supervisor: Optional[str] = Query(None),
    vendedor: Optional[str] = Query(None),
    motivo: Optional[str] = Query(None),
):
    """Serie mensual del rechazo + desglose por motivo, en las tres unidades."""
    hoy = date.today()
    desde = fecha_desde or date(hoy.year, 1, 1).isoformat()
    hasta = fecha_hasta or hoy.isoformat()

    w_r, p_r = _where_rechazos(fuente, desde, hasta, supervisor, vendedor, motivo)
    w_v, p_v = _where_ventas(fuente, desde, hasta, supervisor, vendedor)

    conn = get_conn()
    try:
        cur = dict_cursor(conn)

        # --- Serie mensual: rechazo y venta se agregan por separado y se
        # cruzan por mes (un mes puede tener venta y no tener rechazo).
        cur.execute(f"""
            SELECT to_char(fecha, 'YYYY-MM') AS mes,
                   COUNT(*)                                  AS lineas,
                   COUNT(DISTINCT fecha)                     AS dias_rechazo,
                   COUNT(DISTINCT id_cliente)                AS clientes,
                   COALESCE(SUM(bultos_rechazados), 0)       AS bultos,
                   COALESCE(SUM(hl_rechazados), 0)           AS hl,
                   COALESCE(SUM(importe_rechazado), 0)       AS importe
            FROM rechazos{w_r}
            GROUP BY 1 ORDER BY 1""", p_r)
        rech_mes = {r["mes"]: r for r in cur.fetchall()}

        cur.execute(f"""
            SELECT to_char(fecha, 'YYYY-MM') AS mes,
                   COUNT(DISTINCT fecha)     AS dias_venta,
                   COALESCE(SUM(bultos), 0)  AS venta_bultos,
                   COALESCE(SUM(hl), 0)      AS venta_hl,
                   COALESCE(SUM(importe), 0) AS venta_importe
            FROM ventas_dia{w_v}
            GROUP BY 1 ORDER BY 1""", p_v)
        venta_mes = {r["mes"]: r for r in cur.fetchall()}

        meses = []
        for m in sorted(set(rech_mes) | set(venta_mes)):
            r = rech_mes.get(m, {})
            v = venta_mes.get(m, {})
            # Cobertura: si el mes tiene menos días de venta cargados que días
            # con rechazo, el % está sobreestimado (numerador completo contra
            # denominador parcial). El frontend lo marca en vez de mentir.
            dias_venta = v.get("dias_venta", 0)
            meses.append(_con_pct({
                "mes": m,
                "lineas": r.get("lineas", 0),
                "dias_venta": dias_venta,
                "dias_rechazo": r.get("dias_rechazo", 0),
                "parcial": bool(dias_venta) and dias_venta < r.get("dias_rechazo", 0),
                "clientes": r.get("clientes", 0),
                "bultos": r.get("bultos", 0),
                "hl": r.get("hl", 0),
                "importe": r.get("importe", 0),
                "venta_bultos": v.get("venta_bultos", 0),
                "venta_hl": v.get("venta_hl", 0),
                "venta_importe": v.get("venta_importe", 0),
            }))

        # --- Totales del período ---
        cur.execute(f"""
            SELECT COUNT(*) AS lineas,
                   COUNT(DISTINCT id_cliente) AS clientes,
                   COALESCE(SUM(bultos_rechazados), 0) AS bultos,
                   COALESCE(SUM(hl_rechazados), 0)     AS hl,
                   COALESCE(SUM(importe_rechazado), 0) AS importe
            FROM rechazos{w_r}""", p_r)
        kpis = cur.fetchone()
        cur.execute(f"""
            SELECT COALESCE(SUM(bultos), 0)  AS venta_bultos,
                   COALESCE(SUM(hl), 0)      AS venta_hl,
                   COALESCE(SUM(importe), 0) AS venta_importe
            FROM ventas_dia{w_v}""", p_v)
        kpis.update(cur.fetchone())
        _con_pct(kpis)

        # --- Desglose por motivo del período (el % es sobre la MISMA venta
        # total: cada motivo aporta su porción del % global).
        cur.execute(f"""
            SELECT motivo,
                   COUNT(*) AS lineas,
                   COUNT(DISTINCT id_cliente) AS clientes,
                   COALESCE(SUM(bultos_rechazados), 0) AS bultos,
                   COALESCE(SUM(hl_rechazados), 0)     AS hl,
                   COALESCE(SUM(importe_rechazado), 0) AS importe
            FROM rechazos{w_r}
            GROUP BY 1 ORDER BY importe DESC""", p_r)
        por_motivo = []
        for r in cur.fetchall():
            r["venta_bultos"] = kpis["venta_bultos"]
            r["venta_hl"] = kpis["venta_hl"]
            r["venta_importe"] = kpis["venta_importe"]
            por_motivo.append(_con_pct(r))

        # --- Motivo x mes: alimenta el gráfico apilado y el filtro visual.
        cur.execute(f"""
            SELECT to_char(fecha, 'YYYY-MM') AS mes, motivo,
                   COALESCE(SUM(bultos_rechazados), 0) AS bultos,
                   COALESCE(SUM(hl_rechazados), 0)     AS hl,
                   COALESCE(SUM(importe_rechazado), 0) AS importe
            FROM rechazos{w_r}
            GROUP BY 1, 2 ORDER BY 1, importe DESC""", p_r)
        motivos_mes = cur.fetchall()

        # Cobertura del denominador: sin venta cargada el % no se puede mostrar.
        cur.execute("SELECT MIN(fecha) AS desde, MAX(fecha) AS hasta, COUNT(*) AS filas FROM ventas_dia")
        cobertura = cur.fetchone()

        return {
            "filtros": {"fuente": fuente, "fecha_desde": desde, "fecha_hasta": hasta,
                        "supervisor": supervisor, "vendedor": vendedor, "motivo": motivo},
            "kpis": kpis,
            "meses": meses,
            "por_motivo": por_motivo,
            "motivos_mes": motivos_mes,
            "cobertura_venta": cobertura,
        }
    finally:
        conn.close()
