# HANDOFF — Dashboard de Rechazos Comerciales (Misiones)

Última actualización: 2026-05-18

## Estado: deployado y funcionando en producción.

- Frontend: **https://rechazos-misiones.vercel.app**
- Backend: **https://rechazos-misiones-api.vercel.app**
- Datos: 1.962 rechazos (abril–mayo 2026), referencias completas (2.573
  clientes Chess + 4.780 GESCOM + 396 artículos).

### Hecho

- [x] Backend FastAPI con sync propio Chess + GESCOM → PostgreSQL.
- [x] Esquema `rechazos` unificado + tablas de referencia.
- [x] Normalización Chess (línea con `cantidadesRechazo`) y GESCOM (venta con
      `motivo`, una fila por item).
- [x] Endpoints: `resumen`, `rechazos`, `filtros`, `sync/estado`, `sync`,
      `sync/referencias`, `sync/cron`, `sync/init-db`, `sync/run`.
- [x] Frontend React: toggle CHESS/GESCOM/TODO, filtros (supervisor, promotor,
      ruta, cliente, SKU, motivo + rango de fechas), KPIs, paneles de
      segmentación clickeables, clientes críticos, tendencia, tabla de detalle.
- [x] **Deploy a Vercel** (2 proyectos) en la cuenta empresa `mercosurdrp`.
- [x] Base productiva Neon provisionada + schema aplicado.
- [x] Backfill abril–mayo 2026 sincronizado y verificado.

### Pendiente

- [ ] Backfill histórico (hay Excel de Chess ene–mar 2026 en `../` que se
      podrían importar; el sync sólo trae desde la API).
- [ ] (Opcional) Cargar `ref_vendedor_supervisor` para los rechazos de GESCOM
      que no matchean por nombre contra los supervisores de Chess.

## Datos de prueba (local)

- DB local: `postgresql://postgres:postgres@127.0.0.1:5433/rechazos_dev`.
- Backend dev: `./venv/bin/uvicorn app.main:app --reload --port 8000`.
- Frontend dev: `npm run dev` (proxy `/api` → :8000).

## Infraestructura de producción

- **GitHub**: `mercosurdrp/rechazos-misiones` (monorepo). Cuenta empresa
  `mercosurdrp`.
- **Vercel**: team `mercosurdrps-projects`. Dos proyectos sobre el mismo repo:
  - `rechazos-misiones` — rootDir `frontend`, framework Vite.
  - `rechazos-misiones-api` — rootDir `backend`.
- ⚠️ Monorepo: cada proyecto necesita su `rootDirectory`. Importar la raíz →
  404 NOT_FOUND en todo.

### Backend — región y timeout (CRÍTICO)

🚨 La función del backend corre en la región **`gru1` (São Paulo)**. Desde la
default `iad1` (Virginia) las llamadas a Chess ERP son tan lentas que el sync de
referencias supera los 800s y muere por `FUNCTION_INVOCATION_TIMEOUT`. Está
configurado en el `resourceConfig` del proyecto:
`functionDefaultRegions=["gru1"]`, `functionDefaultTimeout=800`.

### Base de datos

- PostgreSQL de **Neon**, conectada vía Storage de Vercel al proyecto del
  backend. Inyecta `DATABASE_URL` (como integration-secret: sólo existe en
  runtime, no se lee por API ni `vercel env pull`).
- El esquema se aplica con `POST /api/sync/init-db` (header `x-sync-secret`) —
  idempotente, no necesita acceso directo a la DB.

### Env vars del backend

- `DATABASE_URL` (la inyecta Neon).
- `CHESS_BASE_URL`, `CHESS_USER`, `CHESS_PASS`
- `GESCOM_TOKEN_URL`, `GESCOM_BASE_URL`, `GESCOM_CLIENT_ID`, `GESCOM_USER`,
  `GESCOM_PASS`, `GESCOM_EMPRESA=99`
- `SYNC_SECRET` (valor aleatorio largo)
- `CRON_SECRET` = **mismo valor** que `SYNC_SECRET` (lo usa el cron de Vercel)
- `CORS_ORIGINS` = URL del frontend

### Env var del frontend

- `VITE_API_URL` = `https://rechazos-misiones-api.vercel.app` (alias estable).

### Sync inicial / backfill

El cron diario está en `backend/vercel.json` (`/api/sync/cron`, 22:00 UTC =
19:00 ARG). Para un backfill manual usar el endpoint con streaming (las
respuestas no-streaming de Vercel se cortan a ~300s):
`curl -X POST "https://rechazos-misiones-api.vercel.app/api/sync/run?referencias=true&desde=2026-04-01&hasta=<hoy>" -H "x-sync-secret: <SYNC_SECRET>"`

> Las funciones de Vercel terminan server-side aunque el cliente HTTP corte la
> conexión: se puede disparar un sync largo y verificar el resultado después con
> `GET /api/sync/estado` (devuelve cobertura + conteo de referencias).

### Backfill de la solapa 2 (hectolitros + % de rechazo)

Dos backfills distintos, en este orden:

1. `POST /api/sync/init-db` — aplica los `ALTER` nuevos (`hl_rechazados`,
   `ref_articulos.hl_bulto`, tabla `ventas_dia`). **Hacerlo apenas se deploya el
   backend**: hasta que corra, el sync del día falla por columna inexistente.
2. `POST /api/sync/backfill-hl` — HL histórico de los rechazos. Segundos: lee el
   `unimedtotal` del `raw` ya guardado, no vuelve a consultar Chess.
3. `POST /api/sync/ventas?desde=&hasta=` — denominador del %. Sí baja de Chess,
   ~5s por día desde `gru1`: conviene ir por tramos de ~12 días (la función corta
   a 800s). **No toca `rechazos`**, así que no reescribe lo publicado.
   El año 2026 completo son ~18 tramos, unos 20 minutos.

Mientras un mes tenga la venta cargada a medias, `/api/mensual` lo devuelve con
`parcial: true` y el tablero lo muestra atenuado y con asterisco: el % de ese mes
está sobreestimado (rechazo completo ÷ venta parcial).

### Denominador "reparto en camión" (criterio PBI) — backfill

Las columnas `ventas_dia.*_reparto` son el denominador por defecto de la solapa
2 (ver `CLAUDE.md`). Para poblarlas en el histórico:

1. `POST /api/sync/init-db` — agrega las tres columnas (idempotente).
2. `POST /api/sync/ventas?desde=&hasta=&fuentes=CHESS` — re-escribe `ventas_dia`
   de Chess con el corte por camión. **Sólo CHESS**: GESCOM es mostrador y
   siempre aporta 0 al reparto, así que pedirlo sólo alarga la corrida.
   Tramos de ~15 días (la función corta a 800 s). No toca `rechazos`.

## Notas de negocio

- `fechahasta` de GESCOM es exclusivo (se compensa con `D+1` en el código).
- GESCOM Misiones es canal de mostrador: sus rechazos no tienen jerarquía
  promotor/ruta/supervisor real (ver `CLAUDE.md`).
- Motivos más frecuentes observados: SIN DINERO, CERRADO, DEV X TRAMITES
  INTERNOS, BEES - NO PEDIDO, ERROR DE PREVENTA/DISTRIBUCIÓN.
