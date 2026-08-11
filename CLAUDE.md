# CLAUDE.md — Dashboard de Rechazos Comerciales (Misiones)

Leer antes de tocar el código. Documenta el stack, las decisiones tomadas y las
trampas conocidas.

## Qué es

Tablero para la **matinal de ventas** de Mercosur Distribuciones (Misiones):
rechazos de productos de **Chess ERP + GESCOM**, segmentables por supervisor,
promotor, cliente, ruta y SKU, con toggle CHESS / GESCOM / TODO. El foco es
detectar **clientes y rutas críticas** para encarar al cliente.

Proyecto de **Misiones** (stakeholder operativo: **Enzo Orsetti**). Deployado en
la cuenta empresa **`mercosurdrp`**: GitHub `mercosurdrp/rechazos-misiones`,
Vercel team `mercosurdrps-projects`. Ver `HANDOFF.md`.

## Stack

- Backend: FastAPI + psycopg2, Python 3.12. Entrypoint Vercel: `api/index.py`.
- Frontend: React + Vite, CSS propio (sin Tailwind ni libs de UI).
- DB: PostgreSQL. Esquema en `backend/app/schema.sql`.

## Modelo de datos

Tabla única `rechazos` (esquema unificado Chess + GESCOM). Tablas de referencia
`ref_clientes`, `ref_articulos`, `ref_vendedor_supervisor`, y `sync_log`.

El sync es **idempotente por (fuente, día)**: borra y reinserta el día. Reejecutar
no duplica.

### Hectolitros y el denominador del %

- `rechazos.hl_rechazados`: Chess publica el hectolitraje de cada línea en
  **`unimedtotal`** (no hay que derivarlo del nombre del SKU). Se prorratea por
  `cantidadesRechazo / cantidadesTotal`, igual que el importe. El ratio
  `unimedtotal / cantidadesTotal` es **constante por SKU** (verificado sobre un
  día completo: 154 artículos, cero inconsistencias; 4×6×473 cc = 0,1135 HL/bulto).
  ⚠️ Los **combos** vienen con `unimedtotal = 0` → suman 0 HL (subconteo menor,
  mismo patrón que `reference_wqi_skus_sin_maestro_hl` en el almacén).
- `ref_articulos.hl_bulto`: maestro HL/bulto que arma el sync de Chess. GESCOM no
  publica unidad de medida, así que su HL se calcula `bultos × hl_bulto`
  matcheando por código de artículo (los códigos son los mismos: 121 de 154
  matchean en un día típico).
- `ventas_dia (fuente, fecha, id_vendedor)`: la **venta bruta facturada** del día,
  denominador del % de rechazo. Sale de las **mismas líneas** que ya baja el sync
  (las de `cantidadesTotal > 0`; las negativas son las NC/devoluciones, o sea el
  rechazo mismo), sin requests extra. Se guarda abierta por promotor + supervisor
  para poder mostrar el % por promotor sin cruzar numerador filtrado con
  denominador total.
  ⚠️ El numerador **excluye** los rechazos marcados `excluido`.
  ⚠️ El rechazo se emite como NC **1-2 días después** de la factura, así que en el
  corte de mes hay algo de desfase (se diluye en el mensual).

### 🚨 El denominador por defecto es el REPARTO EN CAMIÓN, no la facturación

`ventas_dia` guarda además `bultos_reparto` / `hl_reparto` / `importe_reparto`:
la porción de esa misma venta cuyo `dsFleteroCarga` **es una patente**
(`es_reparto_camion()` en `sync.py`). Es el criterio del **PBI oficial de
Quilmes**, que mide el rechazo contra los HL del reparto y no contra la
facturación, y es el que pidió el usuario (2026-08-11).

Medido en **01–15/05/2026** (el tramo que publica el PBI):

| Denominador | HL | % con 66,8 HL rechazados |
|---|---|---|
| Venta total facturada (lectura vieja) | 13.005 | 0,79 % |
| **Reparto en camión propio** | **3.232** | **2,07 %** |
| PBI de Quilmes | ~3.146 | 2,08 % |

- 🚨 **El que sobraba era el denominador**: GESCOM (mostrador) aportaba el
  **70 % del volumen** y no sube a ningún camión.
- 🚨 **Con `denominador=reparto` el NUMERADOR también se acota al camión
  propio** (`SQL_REPARTO_CAMION` en `mensual.py`, la versión SQL de
  `es_reparto_camion`). Si no, los rechazos de mostrador se cuentan contra un
  denominador que no los tiene y el % se infla: 01–15/05 daba **3,20 %** en vez
  de 2,07 %. No hace falta re-sync: se resuelve sobre la columna `transporte`,
  que ya está cargada. Los rechazos de GESCOM no tienen patente y quedan afuera
  solos.
- La **segunda vuelta del mismo camión** (patente con sufijo `.2`) SÍ cuenta, de
  los dos lados. "SEGUNDA VUELTA" como etiqueta de transporte, no.
- `es_reparto_camion` exige que el transporte **parezca patente** (vieja o
  Mercosur) en vez de descartar etiquetas conocidas: una etiqueta nueva queda
  afuera del denominador en lugar de inflarlo en silencio.
- GESCOM escribe siempre 0 en `*_reparto`: es mostrador, el cliente se lleva la
  mercadería.
- Con la lista de motivos imputables a preventa (`MOTIVOS_VENTAS`, la vista
  VENDEDORES del PBI) el mismo tramo da **1,52 %** contra el **1,55 %** que
  publica el PBI, y ahí aplica el objetivo de **1,29 %**.
- ⚠️ Las columnas `*_reparto` se llenan **re-sincronizando la venta**
  (`POST /api/sync/ventas?fuentes=CHESS`). Hasta que corra para un período, ese
  denominador está vacío y el tablero lo avisa (no muestra 0).

## APIs origen — cómo se obtienen los rechazos

### Chess ERP (Misiones, AR1121)
- Endpoint: `GET /ventas/?fechaDesde=&fechaHasta=&detallado=true&nroLote=`
- El reporte **detallado** devuelve una fila por línea de artículo, con
  `idRechazo` / `dsRechazo` / `cantidadesRechazo` por línea.
- Rechazo = línea con `cantidadesRechazo != 0`. La fecha es `fechaComprobate`.
- `importe_rechazado` = `subtotalNeto` prorrateado por `cantidadesRechazo /
  cantidadesTotal`.
- Login self-signed → `verify=False` a propósito.

### GESCOM
- Endpoint: `GET /ventas/api/v1/get` (OAuth2 password grant).
- Rechazo = venta con campo `motivo` no vacío; se explota **una fila por item**.
- `fechahasta` de GESCOM es **EXCLUSIVO** → para el día D se pide `D+1`.
- Se filtra por `codigoEmpresa = GESCOM_EMPRESA` (99 = Misiones).
- La fecha del rechazo se toma de **`fechaPedido`** (GESCOM filtra por esa
  fecha; su `fechaEntrega` es poco confiable, a veces anterior al pedido).

## Trampas conocidas / decisiones

1. **GESCOM Misiones es canal de mostrador.** `codigoVendedor` / `codigoRuta`
   de la venta son códigos de mostrador (100/200), y la preventa del cliente
   también. NO hay jerarquía promotor/ruta real en GESCOM → se etiqueta
   `MOSTRADOR {código}` y supervisor `MOSTRADOR (GESCOM)`. No inventar promotores.
2. **Supervisor de GESCOM.** GESCOM no lo expone. Se resuelve en 3 niveles:
   (a) mapeo manual `cliente_supervisor_manual`; (b) match por nombre de cliente
   contra `ref_cliente_supervisor` (armado con los comprobantes de Chess, que
   traen cliente+supervisor — sin requests extra); (c) `MOSTRADOR (GESCOM)`.
3. **Exclusiones** (centralizadas en `sync.py`, se aplican en el sync):
   - Motivo que empiece con `DEV X TRAM` (devolución por trámites internos).
   - Transporte que no sea patente: contiene `ALTERNATIVO`, `REFUERZO`,
     `GESTION` o `SEGUNDA VUELTA`.
   - Cliente de GESCOM cuyo nombre contiene `ESPECIAL`.
   - Promotor en `PROMOTOR_EXCLUIR` (mostrador / cuentas no-preventa): VI ELDO,
     MOSTRADOR IGUAZU, MOSTRADOR ELDORADO, MOSTRADOR 100, VI PEOPLE. Nota: en
     GESCOM el vendedor es `MOSTRADOR {código}`, así que excluir `MOSTRADOR 100`
     descarta los rechazos de mostrador de GESCOM.
4. **Sync de referencias** (`ref_clientes` de Chess) pagina ~2.500 clientes →
   tarda ~3 min. Correrlo a parte (`--referencias` o `--solo-referencias`),
   no en cada sync de día.
5. La dimensión **ruta** de Chess se resuelve vía `ref_clientes` (la ruta de
   preventa del cliente, de `eClifuerza.idRuta`). Si falta → `SIN RUTA`.
5b. **Días de visita** (`dias_visita`): de `eClifuerza.diasVisita` de la fuerza
   de **PREVENTA VIGENTE** (`idModoAtencion == 'PRE'`). ⚠️ Chess conserva TODO
   el histórico de fuerzas en `eClifuerza` (todas con `anulado=false`), así que
   NO sirve tomar la primera del array (es la más vieja): se elige la que cubre
   la fecha de hoy entre `fechaInicioFuerza` y `fechaFinFuerza` (la vigente
   termina en `9999-12-31`). Viene como string de códigos de día separados por
   coma (`1`=Dom … `7`=Sáb), ej. `"3,6"`. Se guarda en `ref_clientes` y se
   desnormaliza en `rechazos`. Los rechazos de GESCOM toman los días del
   cliente Chess equivalente (por código).
6. **Apartado de mapeo** (`/api/mapeo`, modal en el frontend): el admin asigna
   supervisor a un cliente. Tiene prioridad y actualiza al instante los
   rechazos ya cargados. Endpoints sin auth en v1 → proteger el deploy a nivel
   Vercel.
7. Credenciales **solo por env vars** (`.env` gitignored / env de Vercel).
   Nunca hardcodear en el código.
8. **Comentarios estilo HILO** (`rechazo_hilos` + `rechazo_comentarios`,
   `routers/comentarios.py`, columna "Coment." a la derecha de Importe en el
   detalle). Un hilo se ancla a un EVENTO de rechazo tal como se agrupa en la
   tabla: fecha + fuente + cliente. La clave `thread_key = "fecha|fuente|
   id_cliente"` es deliberadamente independiente del `id` de `rechazos` (que el
   sync recrea al borrar/reinsertar el día), así el hilo no se huerfaniza. Los
   comentarios son **inmutables** (no hay borrado): a lo sumo el hilo se marca
   `resuelto` (y se puede reabrir). El frontend calcula la misma clave en
   `lib/format.js` (`threadKey`) — si se cambia una, cambiar la otra.

## Sync

- CLI: `python scripts/run_sync.py --referencias --desde Y-M-D --hasta Y-M-D`
- HTTP: `POST /api/sync` (header `x-sync-secret`) — disparo manual.
- Cron Vercel: `GET /api/sync/cron` — ventana móvil de N días (default 5,
  porque un rechazo puede registrarse días después del pedido). Autentica con
  `Authorization: Bearer <CRON_SECRET>`; setear `CRON_SECRET == SYNC_SECRET`.
- Botón "Sincronizar" de la UI: `POST /api/sync/refrescar` — ventana de 7 días,
  sin referencias. SIN secreto (mismo criterio que `/api/mapeo`): se protege a
  nivel Vercel.

## Endpoints API

- `GET /api/health`
- `GET /api/resumen` — KPIs + cortes por cada dimensión + clientes críticos + tendencia.
- `GET /api/mensual` — **solapa 2**: serie mensual (bultos / HL / valorizado +
  el % de cada uno sobre la venta), desglose por motivo y motivo×mes. Filtros:
  `fuente`, `fecha_desde`, `fecha_hasta`, `supervisor`, `vendedor`, `motivo`,
  `denominador`, `vista`.
  El filtro de `motivo` aplica **solo al numerador** (la venta no tiene motivo).
  `pct_* = null` significa "sin denominador cargado", no 0.
  - `denominador=reparto` (**default**) mide contra `ventas_dia.*_reparto`;
    `total`, contra toda la venta facturada. Las dos columnas viajan siempre en
    la respuesta.
  - `vista=todos|ventas|distribucion` es el switch VENTAS/DISTRIBUCIÓN del PBI:
    filtra los MOTIVOS del numerador con la lista blanca `MOTIVOS_VENTAS`.
  - `objetivo_pct` = 1,29 (el del PBI, definido en HL contra el reparto).
- `POST /api/sync/backfill-hl` — rellena `hl_rechazados` del histórico leyendo el
  `raw` ya guardado (no vuelve a consultar Chess) y arma `ref_articulos.hl_bulto`.
  Protegido por `SYNC_SECRET`. Idempotente. **No** completa `ventas_dia`: para el
  denominador histórico hay que correr el sync del período.
- `GET /api/rechazos` — detalle paginado.
- `GET /api/filtros` — valores distintos para los selectores.
- `GET /api/sync/estado` — última corrida, cobertura de datos y conteo de
  `ref_clientes`/`ref_articulos`.
- `POST /api/sync`, `POST /api/sync/referencias`, `GET /api/sync/cron`,
  `POST /api/sync/refrescar`.
- `POST /api/sync/init-db` — aplica `schema.sql` (idempotente). Inicializa la
  base productiva tras el primer deploy. Protegido por `SYNC_SECRET`.
- `POST /api/sync/run` — sync con respuesta en **streaming** (emite heartbeats):
  Vercel corta las respuestas no-streaming a ~300s; este endpoint mantiene viva
  la conexión hasta el límite de 800s de la función. Acepta `referencias`,
  `desde`, `hasta`, `fuentes`.
- `GET/POST/DELETE /api/mapeo` — mapeo manual cliente→supervisor.
- `GET /api/comentarios?fecha_desde=&fecha_hasta=` — hilos de comentarios del
  período, indexados por `thread_key`, con conteo y estado (para el badge del
  detalle). `GET /api/comentarios/hilo?thread_key=` — un hilo completo.
  `POST /api/comentarios` — agrega un comentario (crea el hilo si no existe).
  `POST /api/comentarios/resolver` — marca el hilo resuelto / lo reabre. Sin
  auth en v1 (igual que `/api/mapeo`).

Filtros comunes: `fuente` (CHESS/GESCOM/TODO), `fecha_desde`, `fecha_hasta`,
`supervisor`, `vendedor`, `dias_visita`, `ruta`, `cliente`, `articulo`,
`motivo`.

## Deploy

Backend y frontend son proyectos Vercel separados, ambos en el team
`mercosurdrps-projects` (cuenta empresa `mercosurdrp`), desde el repo
`mercosurdrp/rechazos-misiones`:

- frontend `rechazos-misiones` → `https://rechazos-misiones.vercel.app` (rootDir
  `frontend`, framework Vite).
- backend `rechazos-misiones-api` → `https://rechazos-misiones-api.vercel.app`
  (rootDir `backend`).

🚨 **El backend DEBE correr en la región `gru1` (São Paulo).** Desde la default
`iad1` (Virginia) las llamadas a Chess ERP son lentísimas y el sync de
referencias muere por `FUNCTION_INVOCATION_TIMEOUT`. Configurado en el
`resourceConfig` del proyecto: `functionDefaultRegions=["gru1"]`,
`functionDefaultTimeout=800`.

DB: PostgreSQL de **Neon**, conectada vía Storage de Vercel. `DATABASE_URL` se
inyecta como integration-secret (solo existe en runtime: no se puede leer por la
API de Vercel ni por `vercel env pull`).

Ver `HANDOFF.md` para el checklist completo (env vars, CRON_SECRET, CORS,
`VITE_API_URL` al alias estable del backend).
