"""Sincronizacion de rechazos: Chess + GESCOM -> tabla `rechazos`.

Estrategia idempotente: por cada (fuente, dia) se borra y reinserta. Reejecutar
un dia no genera duplicados.

Definicion de "rechazo":
  - CHESS : linea de comprobante con `cantidadesRechazo` != 0 (motivo = dsRechazo).
  - GESCOM: venta con campo `motivo` no vacio; se explota una fila por item.
"""
import json
import logging
import re
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
    "bultos_rechazados", "hl_rechazados", "importe_rechazado", "raw", "linea_key",
]

VENTA_COLS = ["fuente", "fecha", "id_vendedor", "vendedor", "supervisor",
              "lineas", "bultos", "hl", "importe",
              "bultos_reparto", "hl_reparto", "importe_reparto"]

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

# Patente argentina: vieja (ABC123) o Mercosur (AB123CD). Chess las escribe con
# o sin espacio ("OJA 408", "AE591EV") y le agrega ".2" a la segunda vuelta del
# mismo camion.
_PATENTE_RE = re.compile(r"^(?:[A-Z]{3}\d{3}|[A-Z]{2}\d{3}[A-Z]{2})$")


def es_reparto_camion(transporte: str) -> bool:
    """¿Esa línea salió a la calle en un camión propio?

    Es el criterio del PBI de Quilmes para el denominador del % de rechazo: se
    mide contra lo que efectivamente subió a un camión nuestro. `dsFleteroCarga`
    trae la patente cuando el reparto es propio, y una etiqueta ("SEGUNDA
    VUELTA", "REFUERZO", "TRANSPORTE ALTERNATIVO") o nada cuando no lo es.

    Se exige que PAREZCA una patente en vez de descartar las etiquetas
    conocidas: así una etiqueta nueva queda afuera del denominador en vez de
    inflarlo en silencio. La segunda vuelta del mismo camión (sufijo ".2") SÍ
    cuenta — es el mismo camión saliendo otra vez, y el numerador también la
    incluye.
    """
    t = (transporte or "").strip().upper()
    if not t:
        return False
    t = t.split(".")[0]                       # "HJR 136.2" -> "HJR 136"
    return bool(_PATENTE_RE.match(re.sub(r"[^A-Z0-9]", "", t)))


def claves_refacturadas(comps: List[dict]) -> set:
    """Rechazos de un día que en realidad son una REFACTURACIÓN, no un rechazo.

    Cuando se factura mal, Chess emite una nota de crédito que anula la factura
    y vuelve a facturar lo mismo. La NC lleva `cantidadesRechazo`, así que entra
    como rechazo — pero la mercadería nunca volvió: el cliente se quedó con
    ella. Criterio de Enzo (2026-08-11): eso no es rechazo.

    🚨 Cómo se distingue de un rechazo de verdad. Los dos casos tienen una NC y
    una factura espejo del mismo importe: esa factura es, justamente, la que la
    NC anula. Lo que cambia es cuántas hay:

        rechazo real     NC −1 × $28.764  +  FACTURA +1 × $28.764        (neto 0)
        refacturación    NC −300 × $7,1M  +  FACTURA +300 × $7,1M
                                          +  FACTURA +300 × $7,1M        (neto +300)

    O sea: se exige **dos o más** líneas positivas con la misma cantidad y el
    mismo importe (al peso) para el mismo cliente y artículo del día. Una sola
    es el rechazo normal y NO se toca.

    Medido sobre 2026 completo: 170 casos, 71,8 HL = 7% del rechazo del año (el
    60% de eso cae en enero, casi todo un evento del 27/01).
    ⚠️ Puede haber falso positivo si un cliente compró dos veces el mismo
    artículo el mismo día por el mismo importe exacto y rechazó una. Por eso los
    rechazos se marcan `excluido` con razón 'refacturacion' y quedan guardados,
    en vez de descartarse.
    """
    positivas: Dict[tuple, List[dict]] = {}
    for c in comps:
        if _num(c.get("cantidadesTotal")) > 0 and not _num(c.get("cantidadesRechazo")):
            positivas.setdefault((_txt(c.get("idCliente")), _txt(c.get("idArticulo"))), []).append(c)
    out = set()
    for c in comps:
        crech = abs(_num(c.get("cantidadesRechazo")))
        neto = abs(_num(c.get("subtotalNeto")))
        if not crech or neto <= 0:
            continue
        espejos = [m for m in positivas.get((_txt(c.get("idCliente")), _txt(c.get("idArticulo"))), [])
                   if abs(_num(m.get("cantidadesTotal")) - crech) < 0.01
                   and abs(abs(_num(m.get("subtotalNeto"))) - neto) < 1]
        if len(espejos) >= 2:
            out.add(f"{_txt(c.get('idDocumento'))}-{_txt(c.get('letra'))}-{_txt(c.get('serie'))}"
                    f"-{_txt(c.get('nrodoc'))}-L{_txt(c.get('idLinea'))}")
    return out


def _normaliza_motivo(motivo: str) -> str:
    """Quita el prefijo de la app BEES ("BEES - XXX" -> "XXX").

    Es el mismo motivo de negocio aunque BEES lo etiquete con su prefijo: al
    sacarlo, se unifica con el mismo motivo cargado desde otros orígenes.
    """
    m = (motivo or "").strip()
    if m.upper().startswith("BEES"):
        resto = m[4:].lstrip()
        if resto.startswith("-"):
            resto = resto[1:].strip()
            if resto:
                m = resto
    return m


def _razon_exclusion(motivo: str, transporte: str, vendedor: str = "") -> str:
    """Devuelve la razón de exclusión ('' = no excluido).

    Los rechazos excluidos se guardan igual en la base, marcados con `excluido`
    y esta razón; los endpoints del tablero los filtran. Razones: 'motivo',
    'transporte', 'promotor' y 'refacturacion' (esta última no se decide acá:
    necesita el día completo, la resuelve `claves_refacturadas`).
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
    # Maestro HL/bulto (lo alimenta el sync de Chess). Lo consume GESCOM, que
    # se sincroniza en una pasada posterior: por eso viaja por la DB y no en
    # memoria.
    cur.execute("SELECT id_articulo, hl_bulto FROM ref_articulos "
                "WHERE fuente = 'CHESS' AND hl_bulto IS NOT NULL")
    hl_map = {a: float(h) for (a, h) in cur.fetchall()}
    return (clientes, articulos, vend_sup, chess_por_nombre, chess_por_codigo,
            manual_map, hl_map)


# --------------------------------------------------------------------------
# Normalizacion
# --------------------------------------------------------------------------
def _chess_rows(comprobantes: List[dict], clientes: dict, vend_sup: dict) -> List[dict]:
    out = []
    # Refacturaciones: se resuelve por día completo, mirando TODAS las líneas
    # (una refacturación se reconoce por las facturas espejo, no por la línea).
    refac = claves_refacturadas(comprobantes)
    for c in comprobantes:
        crech = _num(c.get("cantidadesRechazo"))
        motivo = _txt(c.get("dsRechazo"))
        if crech == 0:
            continue  # linea no rechazada
        transporte = _txt(c.get("dsFleteroCarga"))
        razon = _razon_exclusion(motivo, transporte, _txt(c.get("dsVendedor")))
        lkey = (f"{_txt(c.get('idDocumento'))}-{_txt(c.get('letra'))}-{_txt(c.get('serie'))}"
                f"-{_txt(c.get('nrodoc'))}-L{_txt(c.get('idLinea'))}")
        if not razon and lkey in refac:
            razon = "refacturacion"
        ctot = _num(c.get("cantidadesTotal"))
        sneto = abs(_num(c.get("subtotalNeto")))
        importe = sneto * abs(crech) / abs(ctot) if ctot else sneto
        # HL: `unimedtotal` es el hectolitraje de la línea (unidad de medida de
        # Chess). Se prorratea igual que el importe. Los combos vienen en 0.
        umtot = abs(_num(c.get("unimedtotal")))
        hl = umtot * abs(crech) / abs(ctot) if ctot else umtot
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
            "motivo": _normaliza_motivo(motivo) or "SIN MOTIVO",
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
            "hl_rechazados": round(hl, 5),
            "importe_rechazado": round(importe, 2),
            "raw": json.dumps(c, default=str, ensure_ascii=False),
            "linea_key": lkey,
        })
    return out


# --------------------------------------------------------------------------
# Venta del dia (denominador del % de rechazo)
# --------------------------------------------------------------------------
def _chess_ventas(comps: List[dict], fecha: str) -> List[dict]:
    """Agrega la VENTA del dia de Chess por promotor, para `ventas_dia`.

    Denominador = venta BRUTA facturada: las lineas de cantidad POSITIVA. Las
    negativas son notas de credito y devoluciones, es decir el rechazo mismo
    (que la factura original ya contabilizo). Criterio por signo y no por
    `dsDocumento` para que un tipo de comprobante nuevo no quede afuera en
    silencio.

    En la misma pasada se acumula la porcion despachada en CAMION PROPIO
    (`*_reparto`), que es el denominador con el criterio del PBI de Quilmes.
    """
    acc: Dict[tuple, dict] = {}
    for c in comps:
        ctot = _num(c.get("cantidadesTotal"))
        if ctot <= 0:
            continue
        idvend = _txt(c.get("idVendedor"))
        k = ("CHESS", idvend)
        a = acc.setdefault(k, {
            "fuente": "CHESS", "fecha": fecha, "id_vendedor": idvend,
            "vendedor": _txt(c.get("dsVendedor")) or "SIN PROMOTOR",
            "supervisor": _txt(c.get("dsSupervisor")) or "SIN SUPERVISOR",
            "lineas": 0, "bultos": 0.0, "hl": 0.0, "importe": 0.0,
            "bultos_reparto": 0.0, "hl_reparto": 0.0, "importe_reparto": 0.0,
        })
        hl = _num(c.get("unimedtotal"))
        imp = _num(c.get("subtotalNeto"))
        a["lineas"] += 1
        a["bultos"] += ctot
        a["hl"] += hl
        a["importe"] += imp
        if es_reparto_camion(_txt(c.get("dsFleteroCarga"))):
            a["bultos_reparto"] += ctot
            a["hl_reparto"] += hl
            a["importe_reparto"] += imp
    for a in acc.values():
        for col, dec in (("bultos", 4), ("hl", 5), ("importe", 2)):
            a[col] = round(a[col], dec)
            a[f"{col}_reparto"] = round(a[f"{col}_reparto"], dec)
    return list(acc.values())


def _hl_por_bulto(comps: List[dict]) -> Dict[str, float]:
    """Maestro HL/bulto por articulo, derivado de las lineas de venta de Chess.

    `unimedtotal / cantidadesTotal` es constante por SKU (verificado sobre un
    dia completo: 154 articulos, cero inconsistencias). Sirve para valorizar en
    HL los rechazos de GESCOM, que no traen la unidad de medida.
    """
    out: Dict[str, float] = {}
    for c in comps:
        ctot = _num(c.get("cantidadesTotal"))
        um = _num(c.get("unimedtotal"))
        idart = _txt(c.get("idArticulo"))
        if not idart or not ctot or not um:
            continue
        out[idart] = round(abs(um) / abs(ctot), 6)
    return out


def _gescom_ventas(ventas: List[dict], fecha: str, hl_map: Dict[str, float]) -> List[dict]:
    """Agrega la venta del dia de GESCOM (mostrador) por operador.

    Las columnas `*_reparto` quedan en 0 a proposito: GESCOM Misiones es
    mostrador, el cliente se lleva la mercaderia, no sale en camion propio. Por
    eso el denominador "reparto" es solo de Chess.
    """
    acc: Dict[tuple, dict] = {}
    for v in ventas:
        f = (_txt(v.get("fechaPedido")) or _txt(v.get("fechaEntrega")))[:10]
        if f != fecha:
            continue
        idvend = _txt(v.get("codigoVendedor"))
        k = ("GESCOM", idvend)
        a = acc.setdefault(k, {
            "fuente": "GESCOM", "fecha": fecha, "id_vendedor": idvend,
            "vendedor": f"MOSTRADOR {idvend}" if idvend else "MOSTRADOR (GESCOM)",
            "supervisor": "MOSTRADOR (GESCOM)",
            "lineas": 0, "bultos": 0.0, "hl": 0.0, "importe": 0.0,
            "bultos_reparto": 0.0, "hl_reparto": 0.0, "importe_reparto": 0.0,
        })
        for it in (v.get("items") or []):
            cant = _num(it.get("cantidad"))
            a["lineas"] += 1
            a["bultos"] += cant
            a["hl"] += cant * hl_map.get(_txt(it.get("codigoItem")), 0.0)
            a["importe"] += abs(_num(it.get("importeNeto")))
    for a in acc.values():
        a["bultos"] = round(a["bultos"], 4)
        a["hl"] = round(a["hl"], 5)
        a["importe"] = round(a["importe"], 2)
    return list(acc.values())


def _gescom_rows(ventas: List[dict], clientes: dict, articulos: dict,
                 vend_sup: dict, chess_por_nombre: dict, chess_por_codigo: dict,
                 manual_map: dict, hl_map: Dict[str, float] = None) -> List[dict]:
    hl_map = hl_map or {}
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
            # GESCOM no publica hectolitraje: se deriva del maestro HL/bulto de
            # Chess (los codigos de articulo son los mismos). SKU sin maestro
            # (combos, articulos que Chess no vendio) quedan en 0.
            cant_g = _num(it.get("cantidad"))
            out.append({
                "fuente": "GESCOM",
                "fecha": fecha,
                "comprobante": _txt(v.get("numeroComprobante") or v.get("id")),
                "ds_documento": _txt(v.get("codigoTipoVenta")),
                "id_pedido": _txt(v.get("id")),
                "motivo_codigo": _txt(v.get("codigoMotivoCambio")),
                "motivo": _normaliza_motivo(motivo),
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
                "bultos_rechazados": cant_g,
                "hl_rechazados": round(abs(cant_g) * hl_map.get(idart, 0.0), 5),
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


def _write_ventas(conn, fuente: str, fecha: str, filas: List[dict]):
    """Reescribe la venta del dia (denominador). Idempotente por (fuente, dia)."""
    cur = conn.cursor()
    cur.execute("DELETE FROM ventas_dia WHERE fuente = %s AND fecha = %s", (fuente, fecha))
    if filas:
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO ventas_dia ({','.join(VENTA_COLS)}) VALUES %s",
            [[f[c] for c in VENTA_COLS] for f in filas],
        )
    return len(filas)


def _upsert_hl_articulos(conn, comps: List[dict]):
    """Guarda el maestro HL/bulto + descripcion de los articulos de Chess."""
    hl = _hl_por_bulto(comps)
    if not hl:
        return 0
    desc = {_txt(c.get("idArticulo")): _txt(c.get("dsArticulo")) for c in comps}
    valores = [("CHESS", a, desc.get(a, ""), v) for a, v in hl.items()]
    psycopg2.extras.execute_values(
        conn.cursor(),
        """INSERT INTO ref_articulos (fuente, id_articulo, descripcion, hl_bulto)
           VALUES %s
           ON CONFLICT (fuente, id_articulo) DO UPDATE
             SET descripcion = EXCLUDED.descripcion,
                 hl_bulto = EXCLUDED.hl_bulto,
                 updated_at = now()""",
        valores,
    )
    return len(valores)


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
         chess_por_codigo, manual_map, hl_map) = _load_ref(conn)

        if "CHESS" in fuentes:
            sid = conn.cursor()
            sid.execute("INSERT INTO sync_log (fuente,fecha,estado) VALUES ('CHESS',%s,'corriendo') RETURNING id", (fecha,))
            log_id = sid.fetchone()[0]
            conn.commit()
            try:
                comps = ChessClient().get_ventas_detalladas(fecha)
                _upsert_supervisores(conn, comps)
                _upsert_hl_articulos(conn, comps)
                rows = _chess_rows(comps, clientes, vend_sup)
                n = _write(conn, "CHESS", fecha, rows)
                # Denominador del %: la venta del dia sale de los MISMOS
                # comprobantes, sin requests extra.
                _write_ventas(conn, "CHESS", fecha, _chess_ventas(comps, fecha))
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
                                    chess_por_nombre, chess_por_codigo,
                                    manual_map, hl_map)
                n = _write(conn, "GESCOM", fecha, rows)
                _write_ventas(conn, "GESCOM", fecha,
                              _gescom_ventas(ventas, fecha, hl_map))
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


def marcar_refacturaciones(desde: str, hasta: str) -> Dict[str, int]:
    """Marca como 'refacturacion' los rechazos del histórico que lo sean.

    Sólo hace UPDATE del flag `excluido` sobre las filas que ya están cargadas:
    NO borra ni reinserta `rechazos`, así que no puede mover ningún otro número
    ya publicado. Es idempotente y necesita volver a pedirle el día a Chess
    porque la detección mira las líneas de VENTA, que la tabla no guarda.

    Sólo marca; nunca desmarca. Un rechazo excluido por otra razón (mostrador,
    DEV X TRAM, transporte) se deja como está: su razón original es más
    específica.
    """
    d0 = datetime.strptime(desde, "%Y-%m-%d").date()
    d1 = datetime.strptime(hasta, "%Y-%m-%d").date()
    total = {"dias": 0, "detectados": 0, "marcados": 0}
    conn = get_conn()
    try:
        d = d0
        while d <= d1:
            fecha = d.isoformat()
            claves = claves_refacturadas(ChessClient().get_ventas_detalladas(fecha))
            total["dias"] += 1
            total["detectados"] += len(claves)
            if claves:
                cur = conn.cursor()
                cur.execute(
                    """UPDATE rechazos
                          SET excluido = true, motivo_exclusion = 'refacturacion'
                        WHERE fuente = 'CHESS' AND fecha = %s
                          AND linea_key = ANY(%s) AND excluido = false""",
                    (fecha, list(claves)))
                total["marcados"] += cur.rowcount
                conn.commit()
            log.info("Refacturaciones %s: %d detectadas (%s)", fecha, len(claves), total)
            d += timedelta(days=1)
        return total
    finally:
        conn.close()


def sync_ventas_rango(desde: str, hasta: str, fuentes: List[str] = None) -> Dict[str, int]:
    """Backfill del DENOMINADOR: solo `ventas_dia`, sin tocar `rechazos`.

    Para completar el histórico del % sin reescribir los rechazos ya cargados
    (el sync normal borra y reinserta el día: si Chess corrigió un comprobante
    viejo, los números publicados se moverían). El HL histórico de los rechazos
    se resuelve aparte, con `/api/sync/backfill-hl`, que lee el `raw` guardado.
    """
    fuentes = fuentes or ["CHESS", "GESCOM"]
    d0 = datetime.strptime(desde, "%Y-%m-%d").date()
    d1 = datetime.strptime(hasta, "%Y-%m-%d").date()
    total = {"dias": 0, "CHESS": 0, "GESCOM": 0}
    conn = get_conn()
    try:
        d = d0
        while d <= d1:
            fecha = d.isoformat()
            if "CHESS" in fuentes:
                comps = ChessClient().get_ventas_detalladas(fecha)
                _upsert_hl_articulos(conn, comps)
                total["CHESS"] += _write_ventas(conn, "CHESS", fecha,
                                                _chess_ventas(comps, fecha))
            if "GESCOM" in fuentes:
                cur = conn.cursor()
                cur.execute("SELECT id_articulo, hl_bulto FROM ref_articulos "
                            "WHERE fuente = 'CHESS' AND hl_bulto IS NOT NULL")
                hl_map = {a: float(h) for (a, h) in cur.fetchall()}
                ventas = GescomClient().get_ventas(d, d)
                total["GESCOM"] += _write_ventas(conn, "GESCOM", fecha,
                                                 _gescom_ventas(ventas, fecha, hl_map))
            conn.commit()
            total["dias"] += 1
            log.info("Ventas %s ok (%s)", fecha, total)
            d += timedelta(days=1)
        return total
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
