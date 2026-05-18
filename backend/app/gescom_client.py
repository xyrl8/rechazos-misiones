"""Cliente de GESCOM (OAuth2 password grant).

Importante: el parametro `fechahasta` de GESCOM es EXCLUSIVO — el dia indicado
NO se incluye. Para traer el dia D hay que pedir fechahasta = D + 1.
"""
import logging
import time
from datetime import date, timedelta
from typing import List, Optional

import requests

from app.config import settings

log = logging.getLogger("gescom")

MAX_RETRIES = 3
BACKOFF = 2
PAGE_SIZE = 200
MAX_PAGES = 5000


class GescomClient:
    def __init__(self):
        self.token: Optional[str] = None
        self.token_exp: float = 0

    def authenticate(self) -> str:
        if not settings.GESCOM_USER or not settings.GESCOM_PASS:
            raise RuntimeError("GESCOM_USER / GESCOM_PASS no configurados")
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.post(
                    settings.GESCOM_TOKEN_URL,
                    data={
                        "client_id": settings.GESCOM_CLIENT_ID,
                        "username": settings.GESCOM_USER,
                        "password": settings.GESCOM_PASS,
                        "grant_type": "password",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                self.token = data["access_token"]
                self.token_exp = time.time() + data.get("expires_in", 300) - 30
                log.info("GESCOM auth OK")
                return self.token
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                time.sleep(BACKOFF ** attempt)
        raise last_exc

    def _ensure(self):
        if not self.token or time.time() >= self.token_exp:
            self.authenticate()

    @property
    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def _get(self, path: str, params: Optional[dict] = None) -> list:
        self._ensure()
        url = settings.GESCOM_BASE_URL.rstrip("/") + path
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(url, params=params, headers=self._headers, timeout=90)
                if resp.status_code == 401:
                    self.authenticate()
                    continue
                if resp.status_code >= 400:
                    log.warning("GESCOM %s -> %d", path, resp.status_code)
                    return []
                data = resp.json()
                return data if isinstance(data, list) else []
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                time.sleep(BACKOFF ** attempt)
        if last_exc:
            log.error("GESCOM %s fallo tras %d reintentos: %s", path, MAX_RETRIES, last_exc)
        return []

    def get_ventas(self, desde: date, hasta: date) -> List[dict]:
        """Ventas en [desde, hasta] (ambos inclusive). Filtra por GESCOM_EMPRESA.

        `hasta` se traduce a fechahasta = hasta + 1 porque GESCOM la trata como
        exclusiva.
        """
        empresa = str(settings.GESCOM_EMPRESA)
        fhasta = (hasta + timedelta(days=1)).isoformat()
        out: List[dict] = []
        skip = 0
        while skip < MAX_PAGES:
            page = self._get("/ventas/api/v1/get", {
                "pagesize": PAGE_SIZE,
                "pagestoskip": skip,
                "pagestotake": 1,
                "fechadesde": desde.isoformat(),
                "fechahasta": fhasta,
            })
            if not page:
                break
            for v in page:
                if empresa and empresa not in ("0", "") and str(v.get("codigoEmpresa")) != empresa:
                    continue
                out.append(v)
            skip += 1
        log.info("GESCOM ventas %s..%s (empresa %s): %d", desde, hasta, empresa, len(out))
        return out

    def get_clientes(self) -> List[dict]:
        return self._get("/ventas/api/v1/get-clientes")

    def get_articulos(self) -> List[dict]:
        return self._get("/inventario/api/v2/get-articulos")
