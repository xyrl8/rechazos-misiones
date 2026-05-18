"""Sync por linea de comandos (uso local / backfill historico).

Ejemplos:
  python scripts/run_sync.py --referencias
  python scripts/run_sync.py --desde 2026-05-01 --hasta 2026-05-15
  python scripts/run_sync.py --desde 2026-05-15 --fuentes CHESS
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sync import sync_rango, sync_referencias  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--desde", default=(date.today() - timedelta(days=1)).isoformat())
    p.add_argument("--hasta", default=date.today().isoformat())
    p.add_argument("--fuentes", default="CHESS,GESCOM")
    p.add_argument("--referencias", action="store_true",
                   help="refrescar clientes/rutas/articulos antes del sync")
    p.add_argument("--solo-referencias", action="store_true")
    args = p.parse_args()

    if args.referencias or args.solo_referencias:
        print("Sincronizando referencias (clientes/rutas/articulos)...")
        print("  ", sync_referencias())
    if args.solo_referencias:
        return

    fuentes = [x.strip().upper() for x in args.fuentes.split(",") if x.strip()]
    print(f"Sincronizando rechazos {args.desde}..{args.hasta} fuentes={fuentes}")
    total = sync_rango(args.desde, args.hasta, fuentes)
    print("  Resultado:", total)


if __name__ == "__main__":
    main()
