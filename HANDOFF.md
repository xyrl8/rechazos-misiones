# HANDOFF — Dashboard de Rechazos Comerciales (Misiones)

Última actualización: 2026-05-16

## Estado: v1 funcional, verificado end-to-end en local. Falta deploy.

### Hecho

- [x] Backend FastAPI con sync propio Chess + GESCOM → PostgreSQL.
- [x] Esquema `rechazos` unificado + tablas de referencia.
- [x] Normalización Chess (línea con `cantidadesRechazo`) y GESCOM (venta con
      `motivo`, una fila por item).
- [x] Endpoints: `resumen`, `rechazos`, `filtros`, `sync/estado`, `sync`,
      `sync/referencias`, `sync/cron`.
- [x] Frontend React: toggle CHESS/GESCOM/TODO, filtros (supervisor, promotor,
      ruta, cliente, SKU, motivo + rango de fechas), KPIs, paneles de
      segmentación clickeables, clientes críticos, tendencia, tabla de detalle.
- [x] Verificado contra datos reales: ~1 mes sincronizado (1.133 rechazos
      Chess + 63 GESCOM, abril–mayo 2026).

### Pendiente

- [ ] **Deploy a Vercel** (backend + frontend) en la cuenta de Enzo.
- [ ] Provisionar la base productiva (Neon recomendado).
- [ ] Backfill histórico (hay Excel de Chess ene–mar 2026 en `../` que se
      podrían importar; v1 sólo trae desde la API).
- [ ] (Opcional) Cargar `ref_vendedor_supervisor` para asignar supervisor a los
      rechazos de GESCOM (hoy quedan como `MOSTRADOR (GESCOM)`).

## Datos de prueba (local)

- DB local: `postgresql://postgres:postgres@127.0.0.1:5433/rechazos_dev`.
- Backend dev: `./venv/bin/uvicorn app.main:app --reload --port 8000`.
- Frontend dev: `npm run dev` (proxy `/api` → :8000).

## Deploy a Vercel — checklist

> Cuenta de **Enzo** (`enzoorsetti27-stars-projects`). NO usar `mercosurdrp`.

### 1. Base de datos
- Crear una Postgres (Neon vía Marketplace de Vercel, o externa).
- Aplicar el esquema: `python scripts/init_db.py` con `DATABASE_URL` apuntando
  a la base productiva.
- ⚠️ En Neon sobre Vercel, la env var puede llamarse `DATABASE_URL`. El backend
  ya cae a `DATABASE_PUBLIC_URL` si `DATABASE_URL` no está.

### 2. Backend (proyecto Vercel #1, root = `backend/`)
Env vars:
- `DATABASE_URL`
- `CHESS_BASE_URL`, `CHESS_USER`, `CHESS_PASS`
- `GESCOM_TOKEN_URL`, `GESCOM_BASE_URL`, `GESCOM_CLIENT_ID`, `GESCOM_USER`,
  `GESCOM_PASS`, `GESCOM_EMPRESA=99`
- `SYNC_SECRET` (valor aleatorio largo)
- `CRON_SECRET` = **mismo valor** que `SYNC_SECRET` (lo usa el cron de Vercel)
- `CORS_ORIGINS` = URL del frontend (no dejar `*` en prod)

El cron diario ya está en `backend/vercel.json` (`/api/sync/cron` 22:00 UTC =
19:00 ARG). Tras el primer deploy, correr un sync inicial
con referencias:
`curl -X POST "https://<backend>/api/sync?referencias=true&desde=2026-04-01&hasta=2026-05-16" -H "x-sync-secret: <SYNC_SECRET>"`

### 3. Frontend (proyecto Vercel #2, root = `frontend/`)
Env var:
- `VITE_API_URL` = alias **estable** del backend (`https://<backend>.vercel.app`),
  no una URL de deploy puntual.

### 4. Post-deploy
- Verificar `GET /api/health` y `GET /api/sync/estado`.
- Confirmar que el cron corre (Vercel → proyecto backend → Crons).
- Si Vercel deja el deploy en `BLOCKED` por autor del commit, firmar el commit
  como el dueño del proyecto.

## Notas de negocio

- `fechahasta` de GESCOM es exclusivo (se compensa con `D+1` en el código).
- GESCOM Misiones es canal de mostrador: sus rechazos no tienen jerarquía
  promotor/ruta/supervisor real (ver `CLAUDE.md`).
- Motivos más frecuentes observados: SIN DINERO, CERRADO, DEV X TRAMITES
  INTERNOS, BEES - NO PEDIDO, ERROR DE PREVENTA/DISTRIBUCIÓN.
