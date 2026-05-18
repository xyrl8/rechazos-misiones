"""Acceso a PostgreSQL via psycopg2."""
import psycopg2
from psycopg2.extras import RealDictCursor

from app.config import settings


def get_conn():
    """Devuelve una conexion nueva a la base configurada en DATABASE_URL."""
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL no esta configurada")
    return psycopg2.connect(settings.DATABASE_URL, connect_timeout=15)


def dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)
