"""Endpoints de consulta y segmentacion de rechazos."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from app.db import get_conn, dict_cursor

router = APIRouter(prefix="/api", tags=["rechazos"])


def _filtros(fuente, fecha_desde, fecha_hasta, supervisor, vendedor, ruta,
             cliente, articulo, motivo, dias_visita):
    """Construye la clausula WHERE parametrizada a partir de los filtros.

    Siempre excluye los rechazos marcados (`excluido`): el tablero solo muestra
    rechazos comerciales válidos.
    """
    where, params = ["excluido = false"], []
    if fecha_desde:
        where.append("fecha >= %s")
        params.append(fecha_desde)
    if fecha_hasta:
        where.append("fecha <= %s")
        params.append(fecha_hasta)
    if fuente and fuente.upper() != "TODO":
        where.append("fuente = %s")
        params.append(fuente.upper())
    if supervisor:
        where.append("supervisor = %s")
        params.append(supervisor)
    if vendedor:
        where.append("vendedor = %s")
        params.append(vendedor)
    if ruta:
        where.append("ruta = %s")
        params.append(ruta)
    if cliente:
        # Acepta el cliente como nombre, como código, o como "código - nombre".
        where.append("(cliente = %s OR id_cliente = %s "
                     "OR (COALESCE(id_cliente,'') || ' - ' || cliente) = %s)")
        params.extend([cliente, cliente, cliente])
    if articulo:
        where.append("(articulo = %s OR id_articulo = %s)")
        params.extend([articulo, articulo])
    if motivo:
        where.append("motivo = %s")
        params.append(motivo)
    if dias_visita:
        # `dias_visita` llega como códigos de día separados por coma (2=Lun …
        # 7=Sáb). Coincide si el cliente se visita en AL MENOS uno de ellos.
        codigos = [d.strip() for d in dias_visita.split(",") if d.strip()]
        if codigos:
            where.append("string_to_array(dias_visita, ',') && %s::text[]")
            params.append(codigos)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params


# Parametros comunes ----------------------------------------------------------
def _common(
    fuente: str = Query("TODO"),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    supervisor: Optional[str] = Query(None),
    vendedor: Optional[str] = Query(None),
    ruta: Optional[str] = Query(None),
    cliente: Optional[str] = Query(None),
    articulo: Optional[str] = Query(None),
    motivo: Optional[str] = Query(None),
    dias_visita: Optional[str] = Query(None),
):
    if not fecha_desde:
        fecha_desde = (date.today() - timedelta(days=30)).isoformat()
    if not fecha_hasta:
        fecha_hasta = date.today().isoformat()
    return dict(fuente=fuente, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                supervisor=supervisor, vendedor=vendedor, ruta=ruta,
                cliente=cliente, articulo=articulo, motivo=motivo,
                dias_visita=dias_visita)


@router.get("/resumen")
def resumen(
    fuente: str = Query("TODO"),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    supervisor: Optional[str] = Query(None),
    vendedor: Optional[str] = Query(None),
    ruta: Optional[str] = Query(None),
    cliente: Optional[str] = Query(None),
    articulo: Optional[str] = Query(None),
    motivo: Optional[str] = Query(None),
    dias_visita: Optional[str] = Query(None),
):
    """KPIs + cortes por supervisor / promotor / ruta / motivo / SKU / cliente."""
    f = _common(fuente, fecha_desde, fecha_hasta, supervisor, vendedor, ruta,
                cliente, articulo, motivo, dias_visita)
    clause, params = _filtros(**f)

    # Ventana de "clientes críticos": al menos los últimos 15 días. Si el
    # período seleccionado es mayor, se usa el período seleccionado.
    hoy = date.today()
    cc_desde = min(date.fromisoformat(f["fecha_desde"]), hoy - timedelta(days=15))
    cc_hasta = max(date.fromisoformat(f["fecha_hasta"]), hoy)
    clause_cc, params_cc = _filtros(**{**f, "fecha_desde": cc_desde.isoformat(),
                                       "fecha_hasta": cc_hasta.isoformat()})
    conn = get_conn()
    try:
        cur = dict_cursor(conn)

        cur.execute(f"""
            SELECT COUNT(*) lineas,
                   COALESCE(SUM(bultos_rechazados),0) bultos,
                   COALESCE(SUM(importe_rechazado),0) importe,
                   COUNT(DISTINCT id_cliente) clientes,
                   COUNT(DISTINCT comprobante) comprobantes
            FROM rechazos{clause}""", params)
        kpis = cur.fetchone()

        def corte(col, lim=None):
            sql = f"""
                SELECT {col} AS clave,
                       COUNT(*) lineas,
                       COALESCE(SUM(bultos_rechazados),0) bultos,
                       COALESCE(SUM(importe_rechazado),0) importe,
                       COUNT(DISTINCT id_cliente) clientes
                FROM rechazos{clause}
                GROUP BY {col}
                ORDER BY importe DESC, lineas DESC"""
            if lim:
                sql += f" LIMIT {lim}"
            cur.execute(sql, params)
            return cur.fetchall()

        por_fuente = corte("fuente")
        por_supervisor = corte("supervisor")
        por_vendedor = corte("vendedor", 25)
        por_ruta = corte("ruta", 25)
        por_motivo = corte("motivo")
        por_articulo = corte("articulo", 20)

        # "veces" = cantidad de dias distintos en que el cliente rechazo. Es el
        # criterio de criticidad (varios comprobantes el mismo dia cuentan 1).
        # Se calcula sobre la ventana cc (>= 30 dias), no el periodo del filtro.
        cur.execute(f"""
            SELECT id_cliente, cliente, ruta, vendedor, supervisor, localidad,
                   COUNT(DISTINCT fecha) veces,
                   COUNT(*) lineas,
                   COALESCE(SUM(bultos_rechazados),0) bultos,
                   COALESCE(SUM(importe_rechazado),0) importe,
                   MAX(fecha) ultima_fecha,
                   (ARRAY_AGG(motivo ORDER BY fecha DESC))[1] ultimo_motivo
            FROM rechazos{clause_cc}
            GROUP BY id_cliente, cliente, ruta, vendedor, supervisor, localidad
            ORDER BY veces DESC, importe DESC
            LIMIT 60""", params_cc)
        clientes_criticos = cur.fetchall()

        cur.execute(f"""
            SELECT fecha,
                   COUNT(*) lineas,
                   COALESCE(SUM(importe_rechazado),0) importe
            FROM rechazos{clause}
            GROUP BY fecha ORDER BY fecha""", params)
        tendencia = cur.fetchall()

        return {
            "filtros": f,
            "kpis": kpis,
            "por_fuente": por_fuente,
            "por_supervisor": por_supervisor,
            "por_vendedor": por_vendedor,
            "por_ruta": por_ruta,
            "por_motivo": por_motivo,
            "por_articulo": por_articulo,
            "clientes_criticos": clientes_criticos,
            "clientes_criticos_periodo": {"desde": cc_desde.isoformat(),
                                          "hasta": cc_hasta.isoformat()},
            "tendencia": tendencia,
        }
    finally:
        conn.close()


@router.get("/rechazos")
def listar(
    fuente: str = Query("TODO"),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    supervisor: Optional[str] = Query(None),
    vendedor: Optional[str] = Query(None),
    ruta: Optional[str] = Query(None),
    cliente: Optional[str] = Query(None),
    articulo: Optional[str] = Query(None),
    motivo: Optional[str] = Query(None),
    dias_visita: Optional[str] = Query(None),
    limit: int = Query(500, le=5000),
    offset: int = Query(0, ge=0),
):
    """Detalle linea por linea (para la tabla del tablero)."""
    f = _common(fuente, fecha_desde, fecha_hasta, supervisor, vendedor, ruta,
                cliente, articulo, motivo, dias_visita)
    clause, params = _filtros(**f)
    conn = get_conn()
    try:
        cur = dict_cursor(conn)
        cur.execute(f"SELECT COUNT(*) total FROM rechazos{clause}", params)
        total = cur.fetchone()["total"]
        cur.execute(f"""
            SELECT fuente, fecha, comprobante, ds_documento, motivo,
                   supervisor, vendedor, ruta, id_cliente, cliente, localidad,
                   id_articulo, articulo, canal, origen, transporte,
                   bultos_rechazados, importe_rechazado
            FROM rechazos{clause}
            ORDER BY fecha DESC, importe_rechazado DESC
            LIMIT %s OFFSET %s""", params + [limit, offset])
        return {"total": total, "rows": cur.fetchall()}
    finally:
        conn.close()


@router.get("/filtros")
def filtros(
    fuente: str = Query("TODO"),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
):
    """Valores distintos para poblar los selectores del tablero."""
    f = _common(fuente, fecha_desde, fecha_hasta,
                None, None, None, None, None, None, None)
    clause, params = _filtros(**f)  # clause siempre arranca con " WHERE "
    conn = get_conn()
    try:
        cur = conn.cursor()
        out = {}
        for campo in ("supervisor", "vendedor", "articulo", "motivo"):
            cur.execute(
                f"SELECT DISTINCT {campo} FROM rechazos{clause} "
                f"AND {campo} <> '' ORDER BY {campo}",
                params,
            )
            out[campo] = [r[0] for r in cur.fetchall()]
        # Cliente: formato "código - razón social".
        cur.execute(
            f"SELECT DISTINCT COALESCE(id_cliente,'') || ' - ' || cliente "
            f"FROM rechazos{clause} AND cliente <> '' ORDER BY 1",
            params,
        )
        out["cliente"] = [r[0] for r in cur.fetchall()]
        return out
    finally:
        conn.close()


@router.get("/sync/estado")
def sync_estado():
    """Ultima corrida de sync por fuente."""
    conn = get_conn()
    try:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT DISTINCT ON (fuente) fuente, fecha, filas, estado, detalle,
                   started_at, ended_at
            FROM sync_log
            ORDER BY fuente, started_at DESC""")
        ultimas = cur.fetchall()
        cur.execute("SELECT MAX(fecha) maxf, MIN(fecha) minf, COUNT(*) total FROM rechazos")
        cobertura = cur.fetchone()
        return {"ultimas_corridas": ultimas, "cobertura": cobertura}
    finally:
        conn.close()
