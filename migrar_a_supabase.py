"""Migra los datos de la base local SQLite (data/panol.db) a Supabase (Postgres).

Pasos previos:
  1. Crear las tablas en Supabase ejecutando `schema_pg.sql` en el SQL Editor.
  2. Instalar dependencias:  pip install "psycopg[binary]" python-dotenv
  3. Poner la cadena de conexión de Supabase en la variable DATABASE_URL
     (Project Settings -> Database -> Connection string -> URI). Se puede
     dejar en un archivo .env  (DATABASE_URL=postgresql://...).

Uso:
    python migrar_a_supabase.py

Es REPETIBLE: usa ON CONFLICT DO NOTHING, así que no duplica si se corre de nuevo.
No borra nada de la base local; solo lee.
"""
import os
import sys
import sqlite3
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import psycopg

BASE = Path(__file__).parent
SQLITE_DB = BASE / "data" / "panol.db"

# orden que respeta las foreign keys (padres antes que hijos)
TABLAS = [
    "empleados", "almacenistas", "condiciones", "gondolas", "estantes", "herramientas",
    "cajas", "movimientos", "caja_items", "caja_eventos", "caja_evento_items", "transferencias",
]


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Falta DATABASE_URL (la cadena de conexión de Supabase). "
                 "Ponela en una variable de entorno o en un archivo .env")
    if not SQLITE_DB.exists():
        sys.exit(f"No se encuentra la base local: {SQLITE_DB}")

    lite = sqlite3.connect(SQLITE_DB)
    lite.row_factory = sqlite3.Row
    total = {}

    with psycopg.connect(url) as pg:
        with pg.cursor() as cur:
            for tabla in TABLAS:
                filas = lite.execute(f"SELECT * FROM {tabla}").fetchall()
                total[tabla] = len(filas)
                if not filas:
                    continue
                cols = list(filas[0].keys())
                collist = ", ".join(cols)
                ph = ", ".join(["%s"] * len(cols))
                sql = f"INSERT INTO {tabla} ({collist}) VALUES ({ph}) ON CONFLICT DO NOTHING"
                cur.executemany(sql, [tuple(f[c] for c in cols) for f in filas])

            # dejar las secuencias de id en max(id)+1 para las próximas altas
            for tabla in TABLAS:
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {tabla}), 1), "
                    f"(SELECT COUNT(*) FROM {tabla}) > 0)"
                )
        pg.commit()

    lite.close()
    print("Migración terminada. Filas leídas de la base local por tabla:")
    for t in TABLAS:
        print(f"  {t:18} {total.get(t, 0)}")
    print("\nListo. Revisá en Supabase que los conteos coincidan.")


if __name__ == "__main__":
    main()
