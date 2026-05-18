"""Configuracion leida desde variables de entorno.

NO se hardcodean credenciales en el codigo. En desarrollo se cargan desde un
archivo `.env` (gitignored); en produccion (Vercel) desde las env vars del
proyecto. Ver `.env.example`.
"""
import os
from pathlib import Path

# Carga .env si existe (solo dev). En Vercel las vars ya estan en el entorno.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # pragma: no cover
    pass


def _req(name: str) -> str:
    val = os.getenv(name, "")
    return val.strip()


class Settings:
    # --- Base de datos ---
    DATABASE_URL = _req("DATABASE_URL") or _req("DATABASE_PUBLIC_URL")

    # --- Chess ERP (Mercosur Distribuciones / Misiones, AR1121) ---
    CHESS_BASE_URL = _req("CHESS_BASE_URL") or "https://mercosurdistribuciones.chesserp.com/AR1121"
    CHESS_USER = _req("CHESS_USER")
    CHESS_PASS = _req("CHESS_PASS")

    # --- GESCOM ---
    GESCOM_TOKEN_URL = _req("GESCOM_TOKEN_URL") or (
        "https://auth.gescom.online/realms/gcw-mercosur/protocol/openid-connect/token"
    )
    GESCOM_BASE_URL = _req("GESCOM_BASE_URL") or "https://mercosur.gescom.online/data/cmd"
    GESCOM_CLIENT_ID = _req("GESCOM_CLIENT_ID") or "gcw-web-api"
    GESCOM_USER = _req("GESCOM_USER")
    GESCOM_PASS = _req("GESCOM_PASS")
    # Empresa GESCOM de Misiones (segun memoria del operador: 99).
    GESCOM_EMPRESA = _req("GESCOM_EMPRESA") or "99"

    # --- Seguridad ---
    # Secreto que protege POST /api/sync (cron + disparo manual).
    SYNC_SECRET = _req("SYNC_SECRET")
    # Origenes permitidos para CORS, separados por coma. "*" en dev.
    CORS_ORIGINS = _req("CORS_ORIGINS") or "*"

    @classmethod
    def cors_list(cls):
        if cls.CORS_ORIGINS == "*":
            return ["*"]
        return [o.strip() for o in cls.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
