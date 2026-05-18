"""Cliente de Chess ERP (instancia Mercosur Distribuciones / Misiones).

Chess usa certificados self-signed: la verificacion SSL se deshabilita a
proposito. El login devuelve un `sessionId` que viaja como header Cookie.
"""
import logging
import time
from typing import Any, Dict, List, Optional

import requests
from urllib3.exceptions import InsecureRequestWarning

from app.config import settings

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
log = logging.getLogger("chess")

API_PATH = "/web/api/chess/v1"
MAX_RETRIES = 5
BACKOFF = 2
# Pausa entre requests paginados (segundos): evita que Chess responda 403 por
# exceso de pedidos en rafaga.
LOTE_DELAY = 0.4


def _request(method: str, url: str, session_id: Optional[str] = None,
             params: Optional[dict] = None, json_body: Optional[dict] = None) -> requests.Response:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if session_id:
        headers["Cookie"] = session_id
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.request(method, url, headers=headers, params=params,
                                    json=json_body, verify=False, timeout=120)
            # 403/429 = rate limit / bloqueo temporal -> esperar y reintentar.
            if resp.status_code in (403, 429) and attempt < MAX_RETRIES - 1:
                wait = BACKOFF ** attempt + 3
                log.warning("Chess %s -> %d (rate limit?). Reintento %d/%d en %ds",
                            url, resp.status_code, attempt + 1, MAX_RETRIES, wait)
                time.sleep(wait)
                continue
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            wait = BACKOFF ** attempt
            log.warning("Chess %s %s fallo (%d/%d): %s. Reintento en %ds",
                        method, url, attempt + 1, MAX_RETRIES, exc, wait)
            time.sleep(wait)
    if last_exc:
        raise last_exc
    return resp


def _first_list(obj: Any) -> List[dict]:
    """Extrae recursivamente la primera lista de dicts de un JSON anidado."""
    if isinstance(obj, list):
        return obj if (obj and isinstance(obj[0], dict)) else []
    if isinstance(obj, dict):
        for v in obj.values():
            r = _first_list(v)
            if r:
                return r
    return []


class ChessClient:
    def __init__(self):
        self.base_url = settings.CHESS_BASE_URL.rstrip("/") + API_PATH
        self.usuario = settings.CHESS_USER
        self.password = settings.CHESS_PASS
        self.session_id: Optional[str] = None

    def login(self) -> str:
        if not self.usuario or not self.password:
            raise RuntimeError("CHESS_USER / CHESS_PASS no configurados")
        resp = _request("POST", f"{self.base_url}/auth/login",
                        json_body={"usuario": self.usuario, "password": self.password})
        resp.raise_for_status()
        data = resp.json()
        if "sessionId" not in data:
            raise RuntimeError(f"Login Chess sin sessionId: {str(data)[:200]}")
        self.session_id = data["sessionId"]
        log.info("Chess login OK")
        return self.session_id

    def _ensure(self):
        if not self.session_id:
            self.login()

    def get_ventas_detalladas(self, fecha: str) -> List[dict]:
        """Comprobantes detallados (linea por linea) de un dia (yyyy-MM-dd).

        El reporte detallado de `/ventas/` trae una fila por linea de articulo,
        con `idRechazo` / `dsRechazo` / `cantidadesRechazo` por linea.
        """
        self._ensure()
        rows: List[dict] = []
        lote = 1
        while lote <= 300:  # tope de seguridad
            resp = _request("GET", f"{self.base_url}/ventas/", session_id=self.session_id,
                            params={"fechaDesde": fecha, "fechaHasta": fecha,
                                    "detallado": "true", "nroLote": lote})
            if resp.status_code == 401:
                self.login()
                continue
            resp.raise_for_status()
            batch = (resp.json().get("dsReporteComprobantesApi") or {}).get("VentasResumen") or []
            if not batch:
                break
            rows.extend(batch)
            log.info("Chess ventas %s lote %d: %d lineas", fecha, lote, len(batch))
            lote += 1
            time.sleep(LOTE_DELAY)
        return rows

    def get_clientes(self) -> List[dict]:
        """Todos los clientes activos, paginado por nroLote (100/lote)."""
        self._ensure()
        clientes: List[dict] = []
        lote = 1
        while lote <= 1000:
            resp = _request("GET", f"{self.base_url}/clientes/", session_id=self.session_id,
                            params={"anulado": "false", "nroLote": lote})
            if resp.status_code == 401:
                self.login()
                continue
            resp.raise_for_status()
            batch = _first_list(resp.json())
            if not batch:
                break
            clientes.extend(batch)
            lote += 1
            time.sleep(LOTE_DELAY)
        log.info("Chess clientes: %d", len(clientes))
        return clientes

    def get_rutas(self) -> List[dict]:
        """Rutas de venta activas: idRuta -> desRuta."""
        self._ensure()
        resp = _request("GET", f"{self.base_url}/rutasVenta/", session_id=self.session_id,
                        params={"anulada": "false"})
        if resp.status_code == 401:
            self.login()
            return self.get_rutas()
        resp.raise_for_status()
        return _first_list(resp.json())
