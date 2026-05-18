"""Sincronizacion de rechazos: Chess + GESCOM -> tabla `rechazos`.

Estrategia idempotente: por cada (fuente, dia) se borra y reinserta. Reejecutar
un dia no genera duplicados.

Definicion de "rechazo":
  - CHESS : linea de comprobante con `cantidadesRechazo` != 0 (motivo = dsRechazo).
  - GESCOM: venta con campo `motivo` no vacio; se explota una fila por item.
"""
import json
import logging
import unicodedata
from datetime import date, datetime, timedelta
from typing import Dict, List

import psycopg2.extras

from app.chess_client import ChessClient
from app.gescom_client import GescomClient
from app.db import get_conn

log = logging.getLogger("sync")

RECHAZO_COLS = [
    "fuente", "fecha", "comprobante", "ds_documento", "id_pedido",
    "motivo_codigo", "motivo", "id_supervisor", "supervisor",
    "id_vendedor", "vendedor", "id_ruta", "ruta", "dias_visita",
    "id_cliente", "cliente",
    "localidad", "domicilio", "id_articulo", "articulo", "canal", "origen",
    "transporte", "excluido", "motivo_exclusion",
    "bultos_rechazados", "importe_rechazado", "raw", "linea_key",
]

# --- Reglas de exclusion (no son rechazos comerciales a repasar) ---
# Motivos que se descartan (devoluciones por tramites internos, no del cliente).
MOTIVO_EXCLUIR_PREFIJOS = ("DEV X TRAM",)
# Transportes que NO son patentes: se descartan los rechazos afectados a ellos.
TRANSPORTE_EXCLUIR_KEYWORDS = ("ALTERNATIVO", "REFUERZO", "GESTION", "SEGUNDA VUELTA")
# Clientes de GESCOM cuyo nombre contiene estas palabras: se ignoran por completo.
GESCOM_CLIENTE_EXCLUIR_KEYWORDS = ("ESPECIAL",)
# Promotores que NO son de preventa (mostrador / cuentas especiales): se
# descartan sus rechazos y, con ellos, los clientes afectados.
PROMOTOR_EXCLUIR = {"VI ELDO", "MOSTRADOR IGUAZU", "MOSTRADOR ELDORADO",
                    "MOSTRADOR 100", "VI PEOPLE", "VI MD"}


def _razon_exclusion(motivo: str, transporte: str, vendedor: str = "") -> str:
    """Devuelve la razón de exclusión ('' = no excluido).

    Los rechazos excluidos se guardan igual en la base, marcados con `excluido`
    y esta razón; los endpoints del tablero los filtran. Razones: 'motivo',
    'transporte', 'promotor'.
    """
    m = (motivo or "").strip().upper()
    if any(m.startswith(p) for p in MOTIVO_EXCLUIR_PREFIJOS):
        return "motivo"
    t = (transporte or "").strip().upper()
    if t and any(k in t for k in TRANSPORTE_EXCLUIR_KEYWORDS):
        return "transporte"
    if _norm(vendedor) in PROMOTOR_EXCLUIR:
        return "promotor"
    return ""


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _txt(v) -> str:
    return "" if v is None else str(v).strip()


def _norm(s) -> str:
    """Normaliza un nombre para comparar: mayúsculas, sin acentos, sin espacios extra."""
    s = (s or "").strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


# --------------------------------------------------------------------------
# Referencias (rutas, clientes, articulos)
# --------------------------------------------------------------------------
def sync_referencias() -> Dict[str, int]:
    """Refresca ref_clientes / ref_articulos para Chess y GESCOM."""
    resumen = {}
    conn = get_conn()
    try:
        cur = conn.cursor()

        # --- Chess: rutas + clientes ---
        chess = ChessClient()
        rutas = {}
        for r in chess.get_rutas():
            rutas[_txt(r.get("idRuta"))] = _txt(r.get("desRuta"))

        clientes_chess = chess.get_clientes()
        hoy_iso = date.today().isoformat()  # para elegir la fuerza PRE vigente
        rows = []
        for c in clientes_chess:
            idcli = _txt(c.get("idCliente"))
            if not idcli:
                continue
            # ruta: primera eClifuerza activa con idRuta
            id_ruta, ds_ruta = "", ""
            for f in (c.get("eClifuerza") or []):
                if not f.get("anulado") and f.get("idRuta"):
                    id_ruta = _txt(f.get("idRuta"))
                    ds_ruta = rutas.get(id_ruta, "")
                    break
            # dias de visita: de la fuerza de PREVENTA VIGENTE. Chess conserva
            # TODO el historico de fuerzas en `eClifuerza` (todas con
            # anulado=false), asi que NO sirve tomar la primera del array: hay
            # que elegir la que cubre la fecha de hoy (la vigente termina en
            # 9999-12-31). Fallback: la de fechaInicio mas reciente.
            dias_visita = ""
            fuerza_vig = None  # fuerza PRE cuyo rango cubre hoy
            fuerza_ult = None  # fuerza PRE con fechaInicio mas reciente
            for f in (c.get("eClifuerza") or []):
                if f.get("anulado") or (f.get("idModoAtencion") or "").upper() != "PRE":
                    continue
                ini = _txt(f.get("fechaInicioFuerza"))
                fin = _txt(f.get("fechaFinFuerza"))
                if ini and fin and ini <= hoy_iso <= fin:
                    fuerza_vig = f
                if fuerza_ult is None or ini >= _txt(fuerza_ult.get("fechaInicioFuerza")):
                    fuerza_ult = f
            fuerza = fuerza_vig or fuerza_ult
            if fuerza:
                dias_visita = _txt(fuerza.get("diasVisita"))
            # nombre: alias vigente
            nombre = ""
            for a in (c.get("eClialias") or []):
                if not a.get("anulado"):
                    nombre = _txt(a.get("razonSocial") or a.get("fantasiaSocial"))
                    if nombre:
                        break
            # Chess toma el promotor del propio comprobante; aca queda vacio.
            rows.append(("CHESS", idcli, nombre, id_ruta, ds_ruta, dias_visita,
                         "", "", ""))
        cur.execute("DELETE FROM ref_clientes WHERE fuente = 'CHESS'")
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO ref_clientes (fuente,id_cliente,nombre,id_ruta,ds_ruta,dias_visita,id_promotor,localidad,direccion) VALUES %s",
            rows,
        )
        resumen["clientes_chess"] = len(rows)

        # --- GESCOM: clientes + articulos ---
        gescom = GescomClient()
        g_clientes = gescom.get_clientes()
        grows = []
        for c in g_clientes:
            idcli = _txt(c.get("codigo"))
            if not idcli:
                continue
            # Ruta + promotor reales: de la ruta de preventa del cliente.
            id_ruta, id_promotor = "", ""
            for rp in (c.get("rutasPreventa") or []):
                if rp.get("codigoRuta") is not None:
                    id_ruta = _txt(rp.get("codigoRuta"))
                    id_promotor = _txt(rp.get("codigoVendedor"))
                    break
            # GESCOM (mostrador) no expone dias de visita: queda vacio. El
            # rechazo de GESCOM toma los dias del cliente Chess equivalente.
            grows.append((
                "GESCOM", idcli,
                _txt(c.get("razonSocial") or c.get("nombre")),
                id_ruta, f"RUTA {id_ruta}" if id_ruta else "", "", id_promotor,
                _txt(c.get("localidad")), _txt(c.get("direccionEntrega")),
            ))
        cur.execute("DELETE FROM ref_clientes WHERE fuente = 'GESCOM'")
        if grows:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO ref_clientes (fuente,id_cliente,nombre,id_ruta,ds_ruta,dias_visita,id_promotor,localidad,direccion) VALUES %s",
                grows,
            )
        resumen["clientes_gescom"] = len(grows)

        g_articulos = gescom.get_articulos()
        arows = [("GESCOM", _txt(a.get("codigo")), _txt(a.get("descripcion")))
                 for a in g_articulos if a.get("codigo") is not None]
        cur.execute("DELETE FROM ref_articulos WHERE fuente = 'GESCOM'")
        if arows:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO ref_articulos (fuente,id_articulo,descripcion) VALUES %s", arows)
        resumen["articulos_gescom"] = len(arows)

        conn.commit()
        log.info("Referencias sincronizadas: %s", resumen)
        return resumen
    finally:
        conn.close()


def _load_ref(conn):
    """Carga los mapas de referencia a memoria para el normalizado."""
    cur = conn.cursor()
    cur.execute("SELECT fuente,id_cliente,nombre,id_ruta,ds_ruta,dias_visita,id_promotor,localidad,direccion FROM ref_clientes")
    clientes = {(f, c): {"nombre": n, "id_ruta": ir, "ds_ruta": dr,
                         "dias_visita": dv, "id_promotor": ip,
                         "localidad": loc, "direccion": d}
                for (f, c, n, ir, dr, dv, ip, loc, d) in cur.fetchall()}
    cur.execute("SELECT fuente,id_articulo,descripcion FROM ref_articulos")
    articulos = {(f, a): d for (f, a, d) in cur.fetchall()}
    cur.execute("SELECT fuente,id_vendedor,supervisor FROM ref_vendedor_supervisor")
    vend_sup = {(f, v): s for (f, v, s) in cur.fetchall()}
    # Atención del cliente en Chess (armada con sus comprobantes). Se indexa
    # por nombre normalizado y por código de cliente; GESCOM resuelve por código.
    cur.execute("SELECT nombre_norm, supervisor, vendedor, id_cliente FROM ref_cliente_supervisor")
    chess_por_nombre = {n: {"supervisor": s, "vendedor": v, "id_cliente": idc}
                        for (n, s, v, idc) in cur.fetchall()}
    chess_por_codigo = {d["id_cliente"]: d for d in chess_por_nombre.values()
                        if d.get("id_cliente")}
    # Mapeo manual cliente -> {vendedor, supervisor} (prioridad sobre lo auto).
    cur.execute("SELECT nombre_norm, supervisor, vendedor FROM cliente_supervisor_manual")
    manual_map = {n: {"supervisor": s, "vendedor": v}
                  for (n, s, v) in cur.fetchall()}
    return clientes, articulos, vend_sup, chess_por_nombre, chess_por_codigo, manual_map


# --------------------------------------------------------------------------
# Normalizacion
# --------------------------------------------------------------------------
def _chess_rows(comprobantes: List[dict], clientes: dict, vend_sup: dict) -> List[dict]:
    out = []
    for c in comprobantes:
        crech = _num(c.get("cantidadesRechazo"))
        motivo = _txt(c.get("dsRechazo"))
        if crech == 0:
            continue  # linea no rechazada
        transporte = _txt(c.get("dsFleteroCarga"))
        razon = _razon_exclusion(motivo, transporte, _txt(c.get("dsVendedor")))
        ctot = _num(c.get("cantidadesTotal"))
        sneto = abs(_num(c.get("subtotalNeto")))
        importe = sneto * abs(crech) / abs(ctot) if ctot else sneto
        idcli = _txt(c.get("idCliente"))
        ref = clientes.get(("CHESS", idcli), {})
        idvend = _txt(c.get("idVendedor"))
        supervisor = _txt(c.get("dsSupervisor")) or vend_sup.get(("CHESS", idvend)) or "SIN SUPERVISOR"
        out.append({
            "fuente": "CHESS",
            "fecha": c.get("fechaComprobate"),
            "comprobante": f"{_txt(c.get('dsDocumento'))} {_txt(c.get('letra'))}-{_txt(c.get('serie'))}-{_txt(c.get('nrodoc'))}".strip(),
            "ds_documento": _txt(c.get("dsDocumento")),
            "id_pedido": _txt(c.get("idPedido")),
            "motivo_codigo": _txt(c.get("idRechazo")),
            "motivo": motivo or "SIN MOTIVO",
            "id_supervisor": _txt(c.get("idSupervisor")),
            "supervisor": supervisor,
            "id_vendedor": idvend,
            "vendedor": _txt(c.get("dsVendedor")) or "SIN PROMOTOR",
            "id_ruta": ref.get("id_ruta") or "",
            "ruta": ref.get("ds_ruta") or "SIN RUTA",
            "dias_visita": ref.get("dias_visita") or "",
            "id_cliente": idcli,
            "cliente": _txt(c.get("nombreCliente")) or ref.get("nombre") or "SIN CLIENTE",
            "localidad": _txt(c.get("dsLocalidad")),
            "domicilio": _txt(c.get("domicilioCliente")),
            "id_articulo": _txt(c.get("idArticulo")),
            "articulo": _txt(c.get("dsArticulo")) or "SIN ARTICULO",
            "canal": _txt(c.get("dsCanalMkt")),
            "origen": _txt(c.get("origen")),
            "transporte": transporte,
            "excluido": bool(razon),
            "motivo_exclusion": razon,
            "bultos_rechazados": abs(crech),
            "importe_rechazado": round(importe, 2),
            "raw": json.dumps(c, default=str, ensure_ascii=False),
            "linea_key": f"{_txt(c.get('idDocumento'))}-{_txt(c.get('letra'))}-{_txt(c.get('serie'))}"
                         f"-{_txt(c.get('nrodoc'))}-L{_txt(c.get('idLinea'))}",
        })
    return out


def _gescom_rows(ventas: List[dict], clientes: dict, articulos: dict,
                 vend_sup: dict, chess_por_nombre: dict, chess_por_codigo: dict,
                 manual_map: dict) -> List[dict]:
    out = []
    for v in ventas:
        motivo = _txt(v.get("motivo"))
        if not motivo:
            continue  # venta sin rechazo
        gcod = _txt(v.get("codigoCliente"))
        # GESCOM usa el mismo código de cliente que Chess con un "100" antepuesto.
        chess_code = gcod[3:] if (gcod.startswith("100") and len(gcod) > 3) else gcod
        ref_g = clientes.get(("GESCOM", gcod), {})
        # El nombre se toma de GESCOM (el maestro de Chess tiene alias viejos).
        nombre_cli = ref_g.get("nombre") or f"CLIENTE {chess_code}"
        nn = _norm(nombre_cli)
        # Clientes "ESPECIAL" de GESCOM: se descartan por completo.
        if any(k in nn for k in GESCOM_CLIENTE_EXCLUIR_KEYWORDS):
            continue
        idvend = _txt(v.get("codigoVendedor"))
        idruta = _txt(v.get("codigoRuta"))
        # Promotor y supervisor: 1) mapeo manual  2) match por código Chess
        # 3) match por nombre  4) MOSTRADOR (sin resolver). Un mapeo manual con
        # promotor real rescata al cliente de la exclusión por mostrador.
        manual = manual_map.get(nn) or {}
        match = chess_por_codigo.get(chess_code) or chess_por_nombre.get(nn) or {}
        vendedor = (manual.get("vendedor") or match.get("vendedor")
                    or (f"MOSTRADOR {idvend}" if idvend else "MOSTRADOR (GESCOM)"))
        supervisor = (manual.get("supervisor") or match.get("supervisor")
                      or vend_sup.get(("GESCOM", idvend)) or "MOSTRADOR (GESCOM)")
        razon = _razon_exclusion(motivo, "", vendedor)
        # Código de cliente: el de Chess (GESCOM sin el "100" antepuesto).
        id_cliente = chess_code
        # Días de visita: del cliente Chess equivalente (GESCOM no los expone).
        dias_visita = clientes.get(("CHESS", chess_code), {}).get("dias_visita") or ""
        # GESCOM filtra por fechaPedido; su fechaEntrega es poco confiable
        # (a veces anterior al pedido). Se usa fechaPedido como fecha del rechazo.
        fecha = (_txt(v.get("fechaPedido")) or _txt(v.get("fechaEntrega")))[:10] or None
        for it in (v.get("items") or []):
            idart = _txt(it.get("codigoItem"))
            out.append({
                "fuente": "GESCOM",
                "fecha": fecha,
                "comprobante": _txt(v.get("numeroComprobante") or v.get("id")),
                "ds_documento": _txt(v.get("codigoTipoVenta")),
                "id_pedido": _txt(v.get("id")),
                "motivo_codigo": _txt(v.get("codigoMotivoCambio")),
                "motivo": motivo,
                "id_supervisor": "",
                "supervisor": supervisor,
                "id_vendedor": idvend,
                "vendedor": vendedor,
                "id_ruta": idruta,
                "ruta": f"MOSTRADOR {idruta}" if idruta else "SIN RUTA",
                "dias_visita": dias_visita,
                "id_cliente": id_cliente,
                "cliente": nombre_cli,
                "localidad": ref_g.get("localidad") or "",
                "domicilio": ref_g.get("direccion") or "",
                "id_articulo": idart,
                "articulo": articulos.get(("GESCOM", idart)) or f"ARTICULO {idart}",
                "canal": "",
                "origen": _txt(v.get("origen")),
                "transporte": "",
                "excluido": bool(razon),
                "motivo_exclusion": razon,
                "bultos_rechazados": _num(it.get("cantidad")),
                "importe_rechazado": round(abs(_num(it.get("importeNeto"))), 2),
                "raw": json.dumps({**v, "items": None, "_item": it}, default=str, ensure_ascii=False),
                "linea_key": f"{_txt(v.get('id'))}-I{idart}-{_txt(it.get('orden'))}",
            })
    return out


# --------------------------------------------------------------------------
# Sync de un dia
# --------------------------------------------------------------------------
def _write(conn, fuente: str, fecha: str, rows: List[dict]):
    cur = conn.cursor()
    cur.execute("DELETE FROM rechazos WHERE fuente = %s AND fecha = %s", (fuente, fecha))
    if rows:
        # deduplicar linea_key dentro del lote
        seen, dedup = set(), []
        for r in rows:
            k = (r["fuente"], r["fecha"], r["linea_key"])
            if k in seen:
                continue
            seen.add(k)
            dedup.append(r)
        values = [[r[c] for c in RECHAZO_COLS] for r in dedup]
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO rechazos ({','.join(RECHAZO_COLS)}) VALUES %s",
            values,
        )
        return len(dedup)
    return 0


def _upsert_supervisores(conn, comps: List[dict]):
    """Actualiza ref_cliente_supervisor con los comprobantes Chess del día.

    Cada comprobante trae nombreCliente + dsSupervisor + dsVendedor. Este mapa
    (por nombre normalizado) se usa luego para asignar supervisor y promotor a
    los rechazos de GESCOM, matcheando el cliente por nombre. Gana el
    comprobante más reciente. Se ignoran los comprobantes de promotores de
    mostrador para que el mapa refleje la preventa real del cliente.
    """
    mapa = {}  # nombre_norm -> (supervisor, vendedor, id_cliente, fecha)
    for c in comps:
        vend = _txt(c.get("dsVendedor"))
        if _norm(vend) in PROMOTOR_EXCLUIR:
            continue  # mostrador: no define la atención de preventa del cliente
        sup = _txt(c.get("dsSupervisor"))
        nom = _txt(c.get("nombreCliente"))
        f = _txt(c.get("fechaComprobate"))
        if not sup or not nom or not f:
            continue
        nn = _norm(nom)
        prev = mapa.get(nn)
        if not prev or f >= prev[3]:
            mapa[nn] = (sup, vend, _txt(c.get("idCliente")), f)
    if not mapa:
        return
    valores = [(nn, s, vd, idc, f) for nn, (s, vd, idc, f) in mapa.items()]
    psycopg2.extras.execute_values(
        conn.cursor(),
        """INSERT INTO ref_cliente_supervisor
               (nombre_norm, supervisor, vendedor, id_cliente, ultima_fecha)
           VALUES %s
           ON CONFLICT (nombre_norm) DO UPDATE
             SET supervisor = EXCLUDED.supervisor,
                 vendedor = EXCLUDED.vendedor,
                 id_cliente = EXCLUDED.id_cliente,
                 ultima_fecha = EXCLUDED.ultima_fecha,
                 updated_at = now()
           WHERE EXCLUDED.ultima_fecha >= ref_cliente_supervisor.ultima_fecha""",
        valores,
    )


def sync_dia(fecha: str, fuentes: List[str] = None) -> Dict[str, int]:
    """Sincroniza los rechazos de un dia (yyyy-MM-dd) para las fuentes dadas."""
    fuentes = fuentes or ["CHESS", "GESCOM"]
    d = datetime.strptime(fecha, "%Y-%m-%d").date()
    resultado = {}
    conn = get_conn()
    try:
        (clientes, articulos, vend_sup, chess_por_nombre,
         chess_por_codigo, manual_map) = _load_ref(conn)

        if "CHESS" in fuentes:
            sid = conn.cursor()
            sid.execute("INSERT INTO sync_log (fuente,fecha,estado) VALUES ('CHESS',%s,'corriendo') RETURNING id", (fecha,))
            log_id = sid.fetchone()[0]
            conn.commit()
            try:
                comps = ChessClient().get_ventas_detalladas(fecha)
                _upsert_supervisores(conn, comps)
                rows = _chess_rows(comps, clientes, vend_sup)
                n = _write(conn, "CHESS", fecha, rows)
                conn.cursor().execute(
                    "UPDATE sync_log SET filas=%s,estado='ok',ended_at=now() WHERE id=%s", (n, log_id))
                conn.commit()
                resultado["CHESS"] = n
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                conn.cursor().execute(
                    "UPDATE sync_log SET estado='error',detalle=%s,ended_at=now() WHERE id=%s",
                    (str(exc)[:500], log_id))
                conn.commit()
                raise

        if "GESCOM" in fuentes:
            sid = conn.cursor()
            sid.execute("INSERT INTO sync_log (fuente,fecha,estado) VALUES ('GESCOM',%s,'corriendo') RETURNING id", (fecha,))
            log_id = sid.fetchone()[0]
            conn.commit()
            try:
                ventas = GescomClient().get_ventas(d, d)
                rows = _gescom_rows(ventas, clientes, articulos, vend_sup,
                                    chess_por_nombre, chess_por_codigo, manual_map)
                n = _write(conn, "GESCOM", fecha, rows)
                conn.cursor().execute(
                    "UPDATE sync_log SET filas=%s,estado='ok',ended_at=now() WHERE id=%s", (n, log_id))
                conn.commit()
                resultado["GESCOM"] = n
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                conn.cursor().execute(
                    "UPDATE sync_log SET estado='error',detalle=%s,ended_at=now() WHERE id=%s",
                    (str(exc)[:500], log_id))
                conn.commit()
                raise

        return resultado
    finally:
        conn.close()


def sync_rango(desde: str, hasta: str, fuentes: List[str] = None) -> Dict[str, int]:
    """Sincroniza un rango de fechas inclusive.

    Procesa CHESS de todo el rango antes que GESCOM, porque GESCOM necesita el
    mapa de supervisores (ref_cliente_supervisor) que arma el sync de Chess.
    """
    fuentes = fuentes or ["CHESS", "GESCOM"]
    d0 = datetime.strptime(desde, "%Y-%m-%d").date()
    d1 = datetime.strptime(hasta, "%Y-%m-%d").date()
    total = {}
    for fuente in [f for f in ("CHESS", "GESCOM") if f in fuentes]:
        d = d0
        while d <= d1:
            r = sync_dia(d.isoformat(), [fuente])
            total[fuente] = total.get(fuente, 0) + r.get(fuente, 0)
            d += timedelta(days=1)
    return total
