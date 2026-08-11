"""Resumen mensual del rechazo: bultos, hectolitros, valorizado y % sobre venta.

Es la solapa 2 del tablero (la 1 es el detalle operativo para la matinal). Acá
el foco es la evolución: cómo viene el rechazo mes a mes contra la venta del
mismo período, y qué motivos lo explican.

El % se calcula contra `ventas_dia` (venta BRUTA facturada, antes de la nota de
crédito). Numerador y denominador comparten los filtros de fuente, período,
supervisor y promotor; el filtro por MOTIVO aplica solo al numerador (la
pregunta es "cuánto de la venta se rechazó por este motivo").

🚨 Hay DOS denominadores y el default es `reparto`, el del PBI de Quilmes:
solo lo que salió en CAMIÓN PROPIO. `total` es toda la venta facturada e
incluye mostrador, retiro y fleteros — es la lectura vieja del tablero y da un
% tres veces menor, no comparable con el PBI ni con el objetivo de 1,29%.

⚠️ El numerador excluye los rechazos marcados `excluido` (devoluciones por
trámite, refuerzos, mostrador) igual que el resto del tablero. Ese recorte es
justo el que hace el PBI, y por eso el numerador ya coincidía con el suyo antes
de este cambio: lo único que sobraba era el denominador.
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

# --- Criterio del PBI oficial de Quilmes ---------------------------------
# `denominador=reparto` mide contra lo que salio en CAMION PROPIO (columnas
# `*_reparto` de ventas_dia) en vez de contra toda la venta facturada. Es la
# unica forma de comparar el numero con el PBI: su "% HL Rechazados" se calcula
# sobre los HL del reparto, no sobre la facturacion. Validado contra el PBI en
# 01-15/05/2026: 66,8 HL / 3.232 HL = 2,07% (el PBI publica 2,08%).
DENOMINADORES = {"total": "", "reparto": "_reparto"}

# Motivos imputables a PREVENTA. Es la vista "VENDEDORES" del PBI, y es contra
# ella que se mide el objetivo del 1,29%. La lista se dedujo del PBI publicado
# (⏳ falta que Quilmes confirme la oficial). Los motivos llegan normalizados
# por el sync (sin el prefijo "BEES - ").
# 🚨 Lista BLANCA a proposito: un motivo nuevo cae en DISTRIBUCION, no en
# VENTAS. Es preferible subestimar lo imputable a preventa que atribuirle algo
# que nadie decidio.
MOTIVOS_VENTAS = {"SIN DINERO", "ERROR DE PREVENTA", "FECHA CORTA", "NO PEDIDO",
                  "PEDIDO DUPLICADO", "SIN ENVASES"}

# Objetivo del PBI para el % de rechazo (vista VENDEDORES). Viaja al frontend
# para dibujar la linea de referencia.
OBJETIVO_PCT = 1.29


def _where_rechazos(fuente, desde, hasta, supervisor, vendedor, motivo, vista="todos"):
    where, params = ["excluido = false", "fecha >= %s", "fecha <= %s"], [desde, hasta]
    if vista == "ventas":
        where.append("motivo = ANY(%s)")
        params.append(sorted(MOTIVOS_VENTAS))
    elif vista == "distribucion":
        where.append("NOT (motivo = ANY(%s))")
        params.append(sorted(MOTIVOS_VENTAS))
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


def _con_pct(fila, sufijo=""):
    """Agrega pct_bultos / pct_hl / pct_importe a una fila que ya trae ambos lados.

    `sufijo` elige el denominador: "" = toda la venta facturada, "_reparto" =
    solo lo despachado en camion propio (criterio del PBI). Las dos columnas
    viajan siempre en la respuesta, asi el frontend puede mostrar de donde sale
    el numero sin pedir de nuevo."""
    for clave, _col, vcol in UNIDADES:
        fila[f"pct_{clave}"] = _pct(fila.get(clave), fila.get(f"venta_{vcol}{sufijo}"))
    return fila


@router.get("/mensual")
def mensual(
    fuente: str = Query("TODO"),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    supervisor: Optional[str] = Query(None),
    vendedor: Optional[str] = Query(None),
    motivo: Optional[str] = Query(None),
    denominador: str = Query("reparto"),
    vista: str = Query("todos"),
):
    """Serie mensual del rechazo + desglose por motivo, en las tres unidades."""
    hoy = date.today()
    desde = fecha_desde or date(hoy.year, 1, 1).isoformat()
    hasta = fecha_hasta or hoy.isoformat()
    denominador = denominador if denominador in DENOMINADORES else "reparto"
    vista = vista if vista in ("todos", "ventas", "distribucion") else "todos"
    suf = DENOMINADORES[denominador]

    w_r, p_r = _where_rechazos(fuente, desde, hasta, supervisor, vendedor, motivo, vista)
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
                   COUNT(DISTINCT fecha) FILTER (WHERE hl_reparto > 0) AS dias_venta_reparto,
                   COALESCE(SUM(bultos), 0)  AS venta_bultos,
                   COALESCE(SUM(hl), 0)      AS venta_hl,
                   COALESCE(SUM(importe), 0) AS venta_importe,
                   COALESCE(SUM(bultos_reparto), 0)  AS venta_bultos_reparto,
                   COALESCE(SUM(hl_reparto), 0)      AS venta_hl_reparto,
                   COALESCE(SUM(importe_reparto), 0) AS venta_importe_reparto
            FROM ventas_dia{w_v}
            GROUP BY 1 ORDER BY 1""", p_v)
        venta_mes = {r["mes"]: r for r in cur.fetchall()}

        meses = []
        for m in sorted(set(rech_mes) | set(venta_mes)):
            r = rech_mes.get(m, {})
            v = venta_mes.get(m, {})
            # Cobertura: si el mes tiene menos días de denominador cargados que
            # días con rechazo, el % está sobreestimado (numerador completo
            # contra denominador parcial). El frontend lo marca en vez de mentir.
            # 🚨 Se cuentan los días del denominador ELEGIDO: las filas de venta
            # existen desde antes con `hl_reparto = 0`, así que mirar
            # `dias_venta` daría por completo un mes al que le falta el corte por
            # camión (un julio a medio backfillear llegó a mostrar 66%).
            dias_venta = v.get(f"dias_venta{'_reparto' if suf else ''}", 0)
            meses.append(_con_pct({
                "mes": m,
                "lineas": r.get("lineas", 0),
                "dias_venta": dias_venta,
                "dias_venta_total": v.get("dias_venta", 0),
                "dias_rechazo": r.get("dias_rechazo", 0),
                "parcial": bool(dias_venta) and dias_venta < r.get("dias_rechazo", 0),
                "clientes": r.get("clientes", 0),
                "bultos": r.get("bultos", 0),
                "hl": r.get("hl", 0),
                "importe": r.get("importe", 0),
                "venta_bultos": v.get("venta_bultos", 0),
                "venta_hl": v.get("venta_hl", 0),
                "venta_importe": v.get("venta_importe", 0),
                "venta_bultos_reparto": v.get("venta_bultos_reparto", 0),
                "venta_hl_reparto": v.get("venta_hl_reparto", 0),
                "venta_importe_reparto": v.get("venta_importe_reparto", 0),
            }, suf))

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
                   COALESCE(SUM(importe), 0) AS venta_importe,
                   COALESCE(SUM(bultos_reparto), 0)  AS venta_bultos_reparto,
                   COALESCE(SUM(hl_reparto), 0)      AS venta_hl_reparto,
                   COALESCE(SUM(importe_reparto), 0) AS venta_importe_reparto
            FROM ventas_dia{w_v}""", p_v)
        kpis.update(cur.fetchone())
        _con_pct(kpis, suf)

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
            for u in ("bultos", "hl", "importe"):
                r[f"venta_{u}"] = kpis[f"venta_{u}"]
                r[f"venta_{u}_reparto"] = kpis[f"venta_{u}_reparto"]
            r["imputable"] = "ventas" if r["motivo"] in MOTIVOS_VENTAS else "distribucion"
            por_motivo.append(_con_pct(r, suf))

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
        # `filas_reparto` distingue "no hubo reparto" de "todavia no se
        # re-sincronizo la venta con el corte por camion".
        cur.execute("""SELECT MIN(fecha) AS desde, MAX(fecha) AS hasta, COUNT(*) AS filas,
                              COUNT(*) FILTER (WHERE hl_reparto > 0) AS filas_reparto,
                              MAX(fecha) FILTER (WHERE hl_reparto > 0) AS hasta_reparto
                       FROM ventas_dia""")
        cobertura = cur.fetchone()

        return {
            "filtros": {"fuente": fuente, "fecha_desde": desde, "fecha_hasta": hasta,
                        "supervisor": supervisor, "vendedor": vendedor, "motivo": motivo,
                        "denominador": denominador, "vista": vista},
            "objetivo_pct": OBJETIVO_PCT,
            "motivos_ventas": sorted(MOTIVOS_VENTAS),
            "kpis": kpis,
            "meses": meses,
            "por_motivo": por_motivo,
            "motivos_mes": motivos_mes,
            "cobertura_venta": cobertura,
        }
    finally:
        conn.close()
