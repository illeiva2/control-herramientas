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
