-- Dashboard Rechazos Comerciales — Misiones
-- Esquema unificado para rechazos de Chess ERP + GESCOM.

CREATE TABLE IF NOT EXISTS rechazos (
    id                BIGSERIAL PRIMARY KEY,
    fuente            TEXT NOT NULL CHECK (fuente IN ('CHESS', 'GESCOM')),
    fecha             DATE NOT NULL,
    comprobante       TEXT,
    ds_documento      TEXT,
    id_pedido         TEXT,
    motivo_codigo     TEXT,
    motivo            TEXT NOT NULL DEFAULT 'SIN MOTIVO',
    id_supervisor     TEXT,
    supervisor        TEXT NOT NULL DEFAULT 'SIN SUPERVISOR',
    id_vendedor       TEXT,
    vendedor          TEXT NOT NULL DEFAULT 'SIN PROMOTOR',
    id_ruta           TEXT,
    ruta              TEXT NOT NULL DEFAULT 'SIN RUTA',
    dias_visita       TEXT NOT NULL DEFAULT '',
    id_cliente        TEXT,
    cliente           TEXT NOT NULL DEFAULT 'SIN CLIENTE',
    localidad         TEXT,
    domicilio         TEXT,
    id_articulo       TEXT,
    articulo          TEXT NOT NULL DEFAULT 'SIN ARTICULO',
    canal             TEXT,
    origen            TEXT,
    transporte        TEXT,
    excluido          BOOLEAN NOT NULL DEFAULT false,
    motivo_exclusion  TEXT NOT NULL DEFAULT '',
    bultos_rechazados NUMERIC NOT NULL DEFAULT 0,
    importe_rechazado NUMERIC NOT NULL DEFAULT 0,
    raw               JSONB,
    linea_key         TEXT NOT NULL,
    synced_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fuente, fecha, linea_key)
);

CREATE INDEX IF NOT EXISTS idx_rechazos_fecha       ON rechazos (fecha);
CREATE INDEX IF NOT EXISTS idx_rechazos_fuente_fec  ON rechazos (fuente, fecha);
CREATE INDEX IF NOT EXISTS idx_rechazos_supervisor  ON rechazos (supervisor);
CREATE INDEX IF NOT EXISTS idx_rechazos_vendedor    ON rechazos (vendedor);
CREATE INDEX IF NOT EXISTS idx_rechazos_ruta        ON rechazos (ruta);
CREATE INDEX IF NOT EXISTS idx_rechazos_cliente     ON rechazos (id_cliente);
CREATE INDEX IF NOT EXISTS idx_rechazos_articulo    ON rechazos (id_articulo);
CREATE INDEX IF NOT EXISTS idx_rechazos_excluido    ON rechazos (excluido);

-- Referencia: cliente -> ruta / promotor / localidad.
-- Resuelve las dimensiones "ruta" y "promotor". Para GESCOM es imprescindible:
-- el codigoVendedor de la venta es el operador de mostrador, NO el promotor
-- real del cliente, que se toma de su ruta de preventa.
CREATE TABLE IF NOT EXISTS ref_clientes (
    fuente      TEXT NOT NULL,
    id_cliente  TEXT NOT NULL,
    nombre      TEXT,
    id_ruta     TEXT,
    ds_ruta     TEXT,
    dias_visita TEXT NOT NULL DEFAULT '',
    id_promotor TEXT,
    localidad   TEXT,
    direccion   TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (fuente, id_cliente)
);

-- Atención del cliente en Chess (supervisor + promotor), indexada por nombre
-- normalizado. Se arma con los comprobantes de Chess (que traen cliente +
-- supervisor + vendedor) y sirve para asignar supervisor y promotor a los
-- rechazos de GESCOM matcheando el cliente por nombre.
CREATE TABLE IF NOT EXISTS ref_cliente_supervisor (
    nombre_norm  TEXT PRIMARY KEY,
    supervisor   TEXT NOT NULL,
    vendedor     TEXT,
    id_cliente   TEXT,
    ultima_fecha DATE,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Referencia: articulos (necesario para los nombres de SKU de GESCOM).
CREATE TABLE IF NOT EXISTS ref_articulos (
    fuente      TEXT NOT NULL,
    id_articulo TEXT NOT NULL,
    descripcion TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (fuente, id_articulo)
);

-- Mapeo manual vendedor -> supervisor. GESCOM no expone el supervisor en su
-- API; un admin puede cargar filas aca para que el sync resuelva GESCOM.
CREATE TABLE IF NOT EXISTS ref_vendedor_supervisor (
    fuente      TEXT NOT NULL,
    id_vendedor TEXT NOT NULL,
    supervisor  TEXT NOT NULL,
    PRIMARY KEY (fuente, id_vendedor)
);

-- Mapeo manual cliente -> supervisor (apartado de administracion del tablero).
-- Tiene prioridad sobre la resolucion automatica. Sirve para asignar el
-- supervisor a rechazos de GESCOM cuyo cliente no matchea con el listado Chess.
CREATE TABLE IF NOT EXISTS cliente_supervisor_manual (
    nombre_norm TEXT PRIMARY KEY,
    cliente     TEXT NOT NULL,
    vendedor    TEXT NOT NULL DEFAULT '',
    supervisor  TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Comentarios sobre rechazos (estilo HILO). Un "hilo" es un evento de rechazo
-- tal como se muestra en el detalle del tablero: fecha + fuente + cliente.
-- La clave `thread_key` (= "fecha|fuente|id_cliente") es ESTABLE entre syncs:
-- el sync borra y reinserta los `rechazos` del día (cambia su `id` BIGSERIAL),
-- pero fecha/fuente/cliente del evento se conservan, así que el hilo no se
-- huerfaniza. Los comentarios son INMUTABLES (no hay borrado): a lo sumo el
-- hilo se marca como resuelto (y se puede reabrir).
CREATE TABLE IF NOT EXISTS rechazo_hilos (
    thread_key   TEXT PRIMARY KEY,
    fecha        DATE,
    fuente       TEXT,
    id_cliente   TEXT,
    cliente      TEXT NOT NULL DEFAULT '',
    resuelto     BOOLEAN NOT NULL DEFAULT false,
    resuelto_at  TIMESTAMPTZ,
    resuelto_por TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rechazo_hilos_fecha ON rechazo_hilos (fecha);

CREATE TABLE IF NOT EXISTS rechazo_comentarios (
    id         BIGSERIAL PRIMARY KEY,
    thread_key TEXT NOT NULL REFERENCES rechazo_hilos(thread_key) ON DELETE CASCADE,
    comentario TEXT NOT NULL,
    autor      TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rechazo_coment_thread ON rechazo_comentarios (thread_key);

-- Hectolitros rechazados. Chess publica el HL de cada linea en `unimedtotal`
-- (validado: ratio unimedtotal/cantidadesTotal constante por SKU, ej. 4x6x473cc
-- = 0,1135 HL/bulto). Se prorratea igual que el importe. GESCOM no trae HL: se
-- deriva multiplicando los bultos por `ref_articulos.hl_bulto` (maestro Chess).
ALTER TABLE rechazos      ADD COLUMN IF NOT EXISTS hl_rechazados NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE ref_articulos ADD COLUMN IF NOT EXISTS hl_bulto      NUMERIC;

-- Refacturacion: la NC anula una factura que se volvio a emitir, asi que la
-- mercaderia nunca volvio (ver `claves_refacturadas` en sync.py).
-- 🚨 Columna PROPIA y no `excluido` a proposito: `excluido` lo filtran TODOS los
-- endpoints, y eso sacaba estos eventos tambien del detalle operativo de la
-- solapa 1, que es para ir a hablar con el cliente. Un problema de facturacion
-- ahi sigue siendo algo que el vendedor quiere ver. Solo el % de la solapa 2 lo
-- descuenta.
ALTER TABLE rechazos ADD COLUMN IF NOT EXISTS refacturacion BOOLEAN NOT NULL DEFAULT false;

-- Migracion (2026-08-11): las primeras refacturaciones se marcaron con
-- `excluido`; se pasan a la columna propia. Idempotente: despues de correr no
-- queda ninguna fila con esa razon.
UPDATE rechazos
   SET refacturacion = true, excluido = false, motivo_exclusion = ''
 WHERE motivo_exclusion = 'refacturacion';

-- Denominador del % de rechazo: la VENTA del dia (bruta, antes de la nota de
-- credito). Sale de las mismas lineas que ya baja el sync (las de cantidad
-- positiva); las negativas son NC / devoluciones, o sea el propio rechazo.
-- Granularidad (fuente, fecha, vendedor) para poder abrir el % por promotor y
-- por supervisor sin mezclar numerador filtrado con denominador total.
CREATE TABLE IF NOT EXISTS ventas_dia (
    fuente      TEXT NOT NULL,
    fecha       DATE NOT NULL,
    id_vendedor TEXT NOT NULL DEFAULT '',
    vendedor    TEXT NOT NULL DEFAULT 'SIN PROMOTOR',
    supervisor  TEXT NOT NULL DEFAULT 'SIN SUPERVISOR',
    lineas      INTEGER NOT NULL DEFAULT 0,
    bultos      NUMERIC NOT NULL DEFAULT 0,
    hl          NUMERIC NOT NULL DEFAULT 0,
    importe     NUMERIC NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (fuente, fecha, id_vendedor)
);

CREATE INDEX IF NOT EXISTS idx_ventas_dia_fecha ON ventas_dia (fecha);

-- Denominador ALTERNATIVO: la porcion de esa venta que salio a la calle en
-- CAMION PROPIO (`dsFleteroCarga` = patente). Es el criterio del PBI oficial de
-- Quilmes ("% HL Rechazados" = rechazado / HL del reparto) y deja afuera lo que
-- nunca subio a un camion nuestro: mostrador (GESCOM), retiro, fleteros,
-- refuerzos y transporte alternativo. Medido 01-15/05/2026: 3.232 HL contra los
-- 13.005 HL de la venta total -> el % pasa de 0,79% a 2,07% (PBI: 2,08%).
-- Se guarda como columnas de la misma fila y no como tabla aparte porque sale
-- de las MISMAS lineas, en la misma pasada del sync.
ALTER TABLE ventas_dia ADD COLUMN IF NOT EXISTS bultos_reparto  NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE ventas_dia ADD COLUMN IF NOT EXISTS hl_reparto      NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE ventas_dia ADD COLUMN IF NOT EXISTS importe_reparto NUMERIC NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS sync_log (
    id         BIGSERIAL PRIMARY KEY,
    fuente     TEXT,
    fecha      DATE,
    filas      INTEGER DEFAULT 0,
    estado     TEXT,
    detalle    TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    ended_at   TIMESTAMPTZ
);
