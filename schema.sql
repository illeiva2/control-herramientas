PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS empleados (
    id      INTEGER PRIMARY KEY,
    dni     TEXT,
    nombre  TEXT NOT NULL UNIQUE,
    activo  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS almacenistas (
    id      INTEGER PRIMARY KEY,
    dni     TEXT,
    nombre  TEXT NOT NULL UNIQUE,
    activo  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS condiciones (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS herramientas (
    id        INTEGER PRIMARY KEY,
    codigo    TEXT NOT NULL UNIQUE,
    nombre    TEXT NOT NULL,
    detalle   TEXT,
    cantidad  INTEGER NOT NULL DEFAULT 0,   -- stock fisico segun inventario
    modulo    TEXT,
    estante   TEXT,
    ubicacion TEXT,                          -- texto legible: "Gondola 3 - Estante A"
    activo    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS movimientos (
    id             INTEGER PRIMARY KEY,
    tipo           TEXT NOT NULL CHECK (tipo IN ('ENTREGA', 'DEVOLUCION')),
    fecha          TEXT NOT NULL,            -- YYYY-MM-DD
    empleado_id    INTEGER NOT NULL REFERENCES empleados(id),
    herramienta_id INTEGER NOT NULL REFERENCES herramientas(id),
    cantidad       INTEGER NOT NULL CHECK (cantidad > 0),
    condicion_id   INTEGER REFERENCES condiciones(id),
    almacenista_id INTEGER REFERENCES almacenistas(id),
    observacion    TEXT,
    creado         TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_mov_empleado    ON movimientos(empleado_id);
CREATE INDEX IF NOT EXISTS idx_mov_herramienta ON movimientos(herramienta_id);
CREATE INDEX IF NOT EXISTS idx_mov_fecha       ON movimientos(fecha);

-- ---- cajas de herramientas que van al campo ----

CREATE TABLE IF NOT EXISTS cajas (
    id          INTEGER PRIMARY KEY,
    nombre      TEXT NOT NULL UNIQUE,
    descripcion TEXT,
    activo      INTEGER NOT NULL DEFAULT 1
);

-- dotacion: lo que la caja DEBE tener y lo que TIENE ahora
CREATE TABLE IF NOT EXISTS caja_items (
    id             INTEGER PRIMARY KEY,
    caja_id        INTEGER NOT NULL REFERENCES cajas(id),
    herramienta_id INTEGER NOT NULL REFERENCES herramientas(id),
    dotacion       INTEGER NOT NULL DEFAULT 1 CHECK (dotacion >= 0),
    actual         INTEGER NOT NULL DEFAULT 1 CHECK (actual >= 0),
    UNIQUE (caja_id, herramienta_id)
);

-- envios al campo y retornos, con checklist de contenido
CREATE TABLE IF NOT EXISTS caja_eventos (
    id          INTEGER PRIMARY KEY,
    caja_id     INTEGER NOT NULL REFERENCES cajas(id),
    tipo        TEXT NOT NULL CHECK (tipo IN ('ENVIO', 'RETORNO')),
    fecha       TEXT NOT NULL,
    empleado_id INTEGER REFERENCES empleados(id),
    destino     TEXT,
    observacion TEXT,
    creado      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS caja_evento_items (
    id                INTEGER PRIMARY KEY,
    evento_id         INTEGER NOT NULL REFERENCES caja_eventos(id),
    herramienta_id    INTEGER NOT NULL REFERENCES herramientas(id),
    cantidad_esperada INTEGER NOT NULL,
    cantidad_real     INTEGER NOT NULL,
    condicion_id      INTEGER REFERENCES condiciones(id),
    observacion       TEXT
);

-- auditoria de movimientos caja <-> stock del panol
CREATE TABLE IF NOT EXISTS transferencias (
    id             INTEGER PRIMARY KEY,
    fecha          TEXT NOT NULL,
    caja_id        INTEGER NOT NULL REFERENCES cajas(id),
    herramienta_id INTEGER NOT NULL REFERENCES herramientas(id),
    cantidad       INTEGER NOT NULL CHECK (cantidad > 0),
    direccion      TEXT NOT NULL CHECK (direccion IN
                     ('DESDE_STOCK',   -- sale del stock del panol y entra a la caja
                      'A_STOCK',       -- sale de la caja y vuelve al stock
                      'ALTA',          -- entra a la caja sin tocar el stock
                      'BAJA')),        -- sale de la caja sin tocar el stock (perdida/rota)
    observacion    TEXT,
    creado         TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_cev_caja   ON caja_eventos(caja_id);
CREATE INDEX IF NOT EXISTS idx_cevi_ev    ON caja_evento_items(evento_id);
CREATE INDEX IF NOT EXISTS idx_transf_caja ON transferencias(caja_id);
