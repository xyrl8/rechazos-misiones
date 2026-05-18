"""Aplica schema.sql a la base configurada en DATABASE_URL.

Uso:  python scripts/init_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_conn  # noqa: E402

SCHEMA = Path(__file__).resolve().parents[1] / "app" / "schema.sql"


def main():
    sql = SCHEMA.read_text(encoding="utf-8")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        print("Schema aplicado OK")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
