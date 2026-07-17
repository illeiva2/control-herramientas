"""Corre en el servidor: crea el esquema en el Postgres local y migra
los datos desde panol.db (SQLite) + gondolas/estantes desde Supabase."""
import sqlite3
from pathlib import Path
from dotenv import dotenv_values
import psycopg

BASE = Path(r"C:\panol")
url_local = dotenv_values(BASE / ".env.local")["DATABASE_URL"]
url_supabase = dotenv_values(BASE / ".env")["DATABASE_URL"]

# 1) esquema: sacar lineas de comentario y separar por ';'
sql = (BASE / "schema_pg.sql").read_text(encoding="utf-8")
sin_comentarios = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
with psycopg.connect(url_local) as pg:
    for st in sin_comentarios.split(";"):
        if st.strip():
            pg.execute(st)
    pg.commit()
print("esquema creado")

# 2) gondolas y estantes desde Supabase (no existen en la base local del panol)
with psycopg.connect(url_supabase, prepare_threshold=None) as su, psycopg.connect(url_local) as pg:
    for t in ("gondolas", "estantes"):
        filas = su.execute(f"SELECT id, nombre, activo FROM {t} ORDER BY id").fetchall()
        pg.execute(f"DELETE FROM {t}")
        for f in filas:
            pg.execute(f"INSERT INTO {t} (id, nombre, activo) VALUES (%s,%s,%s)", f)
        print(f"{t}: {len(filas)} (desde Supabase)")
    pg.commit()

# 3) datos desde el SQLite fresco
lite = sqlite3.connect(BASE / "panol.db"); lite.row_factory = sqlite3.Row
ORDEN = ["empleados","almacenistas","condiciones","herramientas","cajas",
         "movimientos","caja_items","caja_eventos","caja_evento_items","transferencias"]
with psycopg.connect(url_local) as pg:
    with pg.cursor() as cur:
        def cols_pg(t):
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position", (t,))
            return [r[0] for r in cur.fetchall()]
        for t in reversed(ORDEN):
            cur.execute(f"DELETE FROM {t}")
        for t in ORDEN:
            filas = lite.execute(f"SELECT * FROM {t}").fetchall()
            if not filas:
                print(f"  {t:20} 0"); continue
            comunes = [c for c in filas[0].keys() if c in cols_pg(t)]
            ph = ", ".join(["%s"]*len(comunes))
            cur.executemany(f"INSERT INTO {t} ({', '.join(comunes)}) VALUES ({ph})",
                            [tuple(f[c] for c in comunes) for f in filas])
            print(f"  {t:20} {len(filas)}")
        for t in ORDEN + ["gondolas", "estantes"]:
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}','id'), COALESCE((SELECT MAX(id) FROM {t}),1), (SELECT COUNT(*) FROM {t})>0)")
    pg.commit()
    print("--- verificacion local:")
    print("movimientos:", pg.execute("SELECT COUNT(*), MAX(fecha) FROM movimientos").fetchone())
    print("herramientas:", pg.execute("SELECT COUNT(*) FROM herramientas").fetchone()[0])
    print("gondolas:", pg.execute("SELECT COUNT(*) FROM gondolas").fetchone()[0])
