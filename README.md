# Dashboard de Rechazos Comerciales — Misiones

Tablero para repasar en la **matinal de ventas** los rechazos de productos de
Mercosur Distribuciones (Misiones), cruzando **Chess ERP** y **GESCOM**. Permite
ver rutas y clientes críticos del día para encarar al cliente y consultar por
qué rechazó su último pedido.

Segmenta por **supervisor de ventas, promotor, cliente, ruta y SKU**, con un
toggle **CHESS / GESCOM / TODO**.

## Stack

- **Backend**: FastAPI + psycopg2 (Python 3.12). Sync propio contra las APIs de
  Chess y GESCOM hacia PostgreSQL.
- **Frontend**: React + Vite (sin dependencias de UI extra, CSS propio).
- **DB**: PostgreSQL.
- **Deploy**: Vercel (backend y frontend como proyectos separados).

## Estructura

```
Dashboard/
  backend/    API FastAPI + sync (Chess/GESCOM -> Postgres)
  frontend/   SPA React/Vite
  CLAUDE.md   Notas para sesiones de Claude Code
  HANDOFF.md  Estado del proyecto y pasos de deploy
```

## Desarrollo local

### Backend

```bash
cd backend
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env          # completar credenciales + DATABASE_URL
./venv/bin/python scripts/init_db.py
./venv/bin/python scripts/run_sync.py --referencias --desde 2026-05-01 --hasta 2026-05-16
./venv/bin/uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxea /api -> :8000)
```

Ver `HANDOFF.md` para el deploy en Vercel.
