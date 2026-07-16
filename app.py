import csv
import io
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, url_for, Response)
import psycopg

import updater
from version import VERSION

load_dotenv()

if getattr(sys, "frozen", False):
    # empaquetado con PyInstaller: recursos junto al bundle
    RES = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    BASE = Path(sys.executable).parent
else:
    RES = BASE = Path(__file__).parent

DATABASE_URL = os.environ.get("DATABASE_URL")   # cadena de conexion de Supabase (.env)

app = Flask(__name__,
            template_folder=str(RES / "templates"),
            static_folder=str(RES / "static"))
app.secret_key = "panol-local"  # solo para flash messages; sin login


# ---------------------------------------------------------------- base (Supabase / Postgres)
class _Row(dict):
    """Fila que imita a sqlite3.Row: acceso por nombre y por posicion, y dict(row)."""
    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._vals = list(values)

    def __getitem__(self, k):
        return self._vals[k] if isinstance(k, int) else super().__getitem__(k)


def _row_factory(cursor):
    cols = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: _Row(cols, values)


class _Conn:
    """Envuelve la conexion psycopg: traduce los placeholders ? -> %s para no
    tener que reescribir el SQL existente, y expone execute/commit/rollback/close."""
    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, params=()):
        return self._c.execute(sql.replace("?", "%s"), params)

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()


def db():
    if "db" not in g:
        # prepare_threshold=None: evita prepared statements (necesario con el pooler
        # de Supabase en modo transaccion / pgbouncer).
        g.db = _Conn(psycopg.connect(DATABASE_URL, row_factory=_row_factory,
                                     prepare_threshold=None))
    return g.db


@app.context_processor
def inyectar_globales():
    try:
        almacenistas_hdr = db().execute(
            "SELECT id, nombre FROM almacenistas WHERE activo=1 ORDER BY nombre"
        ).fetchall()
    except psycopg.Error:
        almacenistas_hdr = []
    return {"version_app": VERSION, "almacenistas_hdr": almacenistas_hdr}


@app.route("/api/update-estado")
def api_update_estado():
    return jsonify(updater.estado)


@app.route("/actualizar", methods=["POST"])
def actualizar():
    ok, mensaje = updater.aplicar()
    return jsonify({"ok": ok, "mensaje": mensaje})


@app.teardown_appcontext
def close_db(_exc):
    d = g.pop("db", None)
    if d:
        d.close()


# saldo pendiente por herramienta: entregas - devoluciones
SALDO_HTA = """
    SELECT herramienta_id,
           SUM(CASE WHEN tipo = 'ENTREGA' THEN cantidad ELSE -cantidad END) AS pendiente
    FROM movimientos GROUP BY herramienta_id
"""

# pendiente por empleado + herramienta
SALDO_EMP_HTA = """
    SELECT empleado_id, herramienta_id,
           SUM(CASE WHEN tipo = 'ENTREGA' THEN cantidad ELSE -cantidad END) AS pendiente
    FROM movimientos GROUP BY empleado_id, herramienta_id
"""


def ubicacion_texto(modulo, estante):
    """Texto legible de ubicacion a partir de la gondola (modulo) + estante.
    Mismo formato que el importador de Excel, para ser consistente con los datos ya cargados."""
    m = (modulo or "").strip()
    e = (estante or "").strip()
    if m.upper() == "PARED":
        return "Pared"
    if e.upper() == "P":
        return f"Puntera modulo {m}" if m else "Puntera"
    if m and e:
        return f"Gondola {m} - Estante {e}"
    return m or e or None


# ---------------------------------------------------------------- paginas

@app.route("/")
def index():
    c = db()
    stats = {
        "herramientas": c.execute("SELECT COUNT(*) FROM herramientas WHERE activo=1").fetchone()[0],
        "empleados": c.execute("SELECT COUNT(*) FROM empleados WHERE activo=1").fetchone()[0],
        "prestadas": c.execute(
            f"SELECT COALESCE(SUM(pendiente),0) FROM ({SALDO_HTA}) WHERE pendiente > 0"
        ).fetchone()[0],
        "mov_hoy": c.execute(
            "SELECT COUNT(*) FROM movimientos WHERE fecha = ?", (date.today().isoformat(),)
        ).fetchone()[0],
    }
    rows = c.execute(f"""
        SELECT e.id AS empleado_id, e.nombre AS empleado,
               h.codigo, h.nombre AS herramienta, s.pendiente,
               (SELECT MAX(m.fecha) FROM movimientos m
                 WHERE m.empleado_id = s.empleado_id
                   AND m.herramienta_id = s.herramienta_id
                   AND m.tipo = 'ENTREGA') AS ult_entrega
        FROM ({SALDO_EMP_HTA}) s
        JOIN empleados e ON e.id = s.empleado_id
        JOIN herramientas h ON h.id = s.herramienta_id
        WHERE s.pendiente <> 0
        ORDER BY e.nombre, h.nombre
    """).fetchall()
    pendientes = []
    for r in rows:
        p = dict(r)
        try:
            p["dias"] = (date.today() - date.fromisoformat(p["ult_entrega"])).days
        except (TypeError, ValueError):
            p["dias"] = None
        pendientes.append(p)
    # los mas atrasados primero
    pendientes.sort(key=lambda p: -(p["dias"] or 0))
    atrasados = sum(1 for p in pendientes if p["pendiente"] > 0 and (p["dias"] or 0) > 1)
    ultimos = c.execute("""
        SELECT m.*, e.nombre AS empleado, h.codigo, h.nombre AS herramienta
        FROM movimientos m
        JOIN empleados e ON e.id = m.empleado_id
        JOIN herramientas h ON h.id = m.herramienta_id
        ORDER BY m.id DESC LIMIT 10
    """).fetchall()
    return render_template("index.html", stats=stats, pendientes=pendientes,
                           atrasados=atrasados, ultimos=ultimos)


@app.route("/registrar")
def registrar():
    c = db()
    condiciones = c.execute("SELECT * FROM condiciones WHERE activo=1 ORDER BY nombre").fetchall()
    almacenistas = c.execute("SELECT * FROM almacenistas WHERE activo=1 ORDER BY nombre").fetchall()
    empleado = None
    if request.args.get("empleado_id"):
        empleado = c.execute("SELECT * FROM empleados WHERE id=?",
                             (request.args["empleado_id"],)).fetchone()
    return render_template("registrar.html",
                           tipo=request.args.get("tipo", "ENTREGA"),
                           fecha=request.args.get("fecha", date.today().isoformat()),
                           empleado=empleado,
                           almacenista_id=request.args.get("almacenista_id", ""),
                           condiciones=condiciones, almacenistas=almacenistas)


def nombre_modulo(m):
    if m is None or m == "":
        return "Sin ubicación"
    if str(m).upper() == "PARED":
        return "Pared"
    return f"Góndola {m}"


@app.route("/herramientas")
def herramientas():
    rows = db().execute(f"""
        SELECT h.*, COALESCE(s.pendiente, 0) AS pendiente,
               h.cantidad - COALESCE(s.pendiente, 0) AS disponible
        FROM herramientas h LEFT JOIN ({SALDO_HTA}) s ON s.herramienta_id = h.id
        WHERE h.activo = 1
    """).fetchall()

    def orden(h):
        m, e = h["modulo"], h["estante"]
        try:
            clave_mod = (0, float(m))
        except (TypeError, ValueError):
            clave_mod = (1, 0) if m else (2, 0)
        try:
            clave_cod = (0, float(h["codigo"]))
        except ValueError:
            clave_cod = (1, 0)
        return (clave_mod, str(e or "~"), clave_cod, h["codigo"])

    def etiqueta_estante(est):
        e = str(est or "").strip()
        if e.upper() == "P":
            return "Puntera"
        if e in ("", "0", "None"):
            return ""
        return f"Estante {e}"

    # dos niveles: gondola/modulo -> estantes
    grupos = []
    for h in sorted(rows, key=orden):
        mod = str(h["modulo"] or "")
        if not grupos or grupos[-1]["modulo"] != mod:
            grupos.append({"modulo": mod, "nombre": nombre_modulo(h["modulo"]),
                           "subgrupos": [], "total": 0})
        g = grupos[-1]
        etq = etiqueta_estante(h["estante"])
        if not g["subgrupos"] or g["subgrupos"][-1]["etiqueta"] != etq:
            g["subgrupos"].append({"etiqueta": etq, "items": []})
        g["subgrupos"][-1]["items"].append(h)
        g["total"] += 1

    modulos = [(g["modulo"], g["nombre"]) for g in grupos]
    return render_template("herramientas.html", grupos=grupos, modulos=modulos,
                           total=len(rows), q=request.args.get("q", "").strip())


@app.route("/herramientas/<int:hid>")
def herramienta(hid):
    c = db()
    h = c.execute(f"""
        SELECT h.*, COALESCE(s.pendiente,0) AS pendiente,
               h.cantidad - COALESCE(s.pendiente,0) AS disponible
        FROM herramientas h LEFT JOIN ({SALDO_HTA}) s ON s.herramienta_id = h.id
        WHERE h.id = ?
    """, (hid,)).fetchone()
    if not h:
        return redirect(url_for("herramientas"))
    quien = c.execute(f"""
        SELECT e.id, e.nombre, s.pendiente FROM ({SALDO_EMP_HTA}) s
        JOIN empleados e ON e.id = s.empleado_id
        WHERE s.herramienta_id = ? AND s.pendiente <> 0 ORDER BY e.nombre
    """, (hid,)).fetchall()
    historial = c.execute("""
        SELECT m.*, e.nombre AS empleado, c2.nombre AS condicion, a.nombre AS almacenista
        FROM movimientos m
        JOIN empleados e ON e.id = m.empleado_id
        LEFT JOIN condiciones c2 ON c2.id = m.condicion_id
        LEFT JOIN almacenistas a ON a.id = m.almacenista_id
        WHERE m.herramienta_id = ? ORDER BY m.fecha DESC, m.id DESC LIMIT 200
    """, (hid,)).fetchall()
    en_cajas = c.execute("""
        SELECT k.id, k.nombre, i.actual FROM caja_items i
        JOIN cajas k ON k.id = i.caja_id
        WHERE i.herramienta_id = ? AND i.actual > 0 ORDER BY k.nombre
    """, (hid,)).fetchall()
    return render_template("herramienta.html", h=h, quien=quien, historial=historial,
                           en_cajas=en_cajas)


@app.route("/empleados")
def empleados():
    rows = db().execute(f"""
        SELECT e.*, COALESCE(SUM(CASE WHEN s.pendiente > 0 THEN s.pendiente END), 0) AS pendientes
        FROM empleados e
        LEFT JOIN ({SALDO_EMP_HTA}) s ON s.empleado_id = e.id
        WHERE e.activo = 1
        GROUP BY e.id ORDER BY e.nombre
    """).fetchall()
    return render_template("empleados.html", rows=rows)


@app.route("/empleados/<int:eid>")
def empleado(eid):
    c = db()
    e = c.execute("SELECT * FROM empleados WHERE id = ?", (eid,)).fetchone()
    if not e:
        return redirect(url_for("empleados"))
    tiene = c.execute(f"""
        SELECT h.id, h.codigo, h.nombre, h.ubicacion, s.pendiente
        FROM ({SALDO_EMP_HTA}) s JOIN herramientas h ON h.id = s.herramienta_id
        WHERE s.empleado_id = ? AND s.pendiente <> 0 ORDER BY h.nombre
    """, (eid,)).fetchall()
    historial = c.execute("""
        SELECT m.*, h.codigo, h.nombre AS herramienta, c2.nombre AS condicion
        FROM movimientos m
        JOIN herramientas h ON h.id = m.herramienta_id
        LEFT JOIN condiciones c2 ON c2.id = m.condicion_id
        WHERE m.empleado_id = ? ORDER BY m.fecha DESC, m.id DESC LIMIT 200
    """, (eid,)).fetchall()
    return render_template("empleado.html", e=e, tiene=tiene, historial=historial)


@app.route("/movimientos")
def movimientos():
    q = request.args.get("q", "").strip()
    tipo = request.args.get("tipo", "")
    desde = request.args.get("desde", "")
    hasta = request.args.get("hasta", "")
    sql = """
        SELECT m.*, e.nombre AS empleado, h.codigo, h.nombre AS herramienta,
               c2.nombre AS condicion, a.nombre AS almacenista
        FROM movimientos m
        JOIN empleados e ON e.id = m.empleado_id
        JOIN herramientas h ON h.id = m.herramienta_id
        LEFT JOIN condiciones c2 ON c2.id = m.condicion_id
        LEFT JOIN almacenistas a ON a.id = m.almacenista_id
        WHERE 1=1
    """
    params = []
    if q:
        sql += " AND (e.nombre LIKE ? OR h.nombre LIKE ? OR h.codigo LIKE ?)"
        params += ["%" + q + "%", "%" + q + "%", q + "%"]
    if tipo in ("ENTREGA", "DEVOLUCION"):
        sql += " AND m.tipo = ?"
        params.append(tipo)
    if desde:
        sql += " AND m.fecha >= ?"
        params.append(desde)
    if hasta:
        sql += " AND m.fecha <= ?"
        params.append(hasta)
    sql += " ORDER BY m.fecha DESC, m.id DESC LIMIT 500"
    rows = db().execute(sql, params).fetchall()
    return render_template("movimientos.html", rows=rows, q=q, tipo=tipo, desde=desde, hasta=hasta)


@app.route("/movimientos/<int:mid>/eliminar", methods=["POST"])
def eliminar_movimiento(mid):
    c = db()
    c.execute("DELETE FROM movimientos WHERE id = ?", (mid,))
    c.commit()
    flash("Movimiento eliminado.", "ok")
    return redirect(request.referrer or url_for("movimientos"))


@app.route("/exportar/movimientos.csv")
def exportar_movimientos():
    rows = db().execute("""
        SELECT m.fecha, m.tipo, e.nombre AS trabajador, h.codigo, h.nombre AS herramienta,
               m.cantidad, c2.nombre AS condicion, a.nombre AS almacenista, m.observacion
        FROM movimientos m
        JOIN empleados e ON e.id = m.empleado_id
        JOIN herramientas h ON h.id = m.herramienta_id
        LEFT JOIN condiciones c2 ON c2.id = m.condicion_id
        LEFT JOIN almacenistas a ON a.id = m.almacenista_id
        ORDER BY m.fecha, m.id
    """).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["FECHA", "TIPO", "TRABAJADOR", "CODIGO", "HERRAMIENTA",
                "CANTIDAD", "CONDICION", "ALMACENISTA", "OBSERVACION"])
    for r in rows:
        w.writerow(list(r))
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=movimientos.csv"})


# ---------------------------------------------------------------- cajas

def estado_caja(c, caja_id):
    ev = c.execute("""SELECT tipo, fecha, destino FROM caja_eventos
                      WHERE caja_id = ? ORDER BY id DESC LIMIT 1""", (caja_id,)).fetchone()
    if ev and ev["tipo"] == "ENVIO":
        return {"en_campo": True, "texto": f"En el campo — {ev['destino'] or 'sin destino'} (desde {ev['fecha']})"}
    return {"en_campo": False, "texto": "En el pañol"}


@app.route("/cajas", methods=["GET", "POST"])
def cajas():
    c = db()
    if request.method == "POST":
        try:
            c.execute("INSERT INTO cajas (nombre, descripcion) VALUES (?,?)",
                      (request.form["nombre"].strip(),
                       request.form.get("descripcion", "").strip() or None))
            c.commit()
            flash("Caja creada. Ahora cargale su dotación de herramientas.", "ok")
        except psycopg.errors.UniqueViolation:
            c.rollback()
            flash("Ya existe una caja con ese nombre.", "error")
        return redirect(url_for("cajas"))
    filas = c.execute("""
        SELECT k.*, COUNT(i.id) AS items,
               COALESCE(SUM(i.dotacion), 0) AS dotacion,
               COALESCE(SUM(i.actual), 0) AS actual,
               COALESCE(SUM(CASE WHEN i.actual < i.dotacion THEN i.dotacion - i.actual END), 0) AS faltantes
        FROM cajas k LEFT JOIN caja_items i ON i.caja_id = k.id
        WHERE k.activo = 1 GROUP BY k.id ORDER BY k.nombre
    """).fetchall()
    # una caja "vacía" (0/0 ahora) se puede eliminar, aunque tenga historial
    lista = [dict(f, vacia=(f["dotacion"] == 0 and f["actual"] == 0), **estado_caja(c, f["id"]))
             for f in filas]
    return render_template("cajas.html", cajas=lista)


@app.route("/cajas/<int:kid>/eliminar", methods=["POST"])
def caja_eliminar(kid):
    c = db()
    tiene = c.execute("SELECT 1 FROM caja_items WHERE caja_id=? AND (dotacion>0 OR actual>0) LIMIT 1",
                      (kid,)).fetchone()
    if tiene:
        flash("No se puede eliminar: la caja todavía tiene herramientas. "
              "Vaciala primero (devolver al stock o dar de baja).", "error")
        return redirect(url_for("caja", kid=kid))
    # borrar la caja y todo su historial asociado (envíos/retornos y transferencias)
    c.execute("""DELETE FROM caja_evento_items
                 WHERE evento_id IN (SELECT id FROM caja_eventos WHERE caja_id=?)""", (kid,))
    c.execute("DELETE FROM caja_eventos WHERE caja_id=?", (kid,))
    c.execute("DELETE FROM transferencias WHERE caja_id=?", (kid,))
    c.execute("DELETE FROM caja_items WHERE caja_id=?", (kid,))
    c.execute("DELETE FROM cajas WHERE id=?", (kid,))
    c.commit()
    flash("Caja eliminada.", "ok")
    return redirect(url_for("cajas"))


@app.route("/cajas/<int:kid>")
def caja(kid):
    c = db()
    k = c.execute("SELECT * FROM cajas WHERE id = ?", (kid,)).fetchone()
    if not k:
        return redirect(url_for("cajas"))
    items = c.execute("""
        SELECT i.*, h.codigo, h.nombre, h.cantidad AS stock_panol
        FROM caja_items i JOIN herramientas h ON h.id = i.herramienta_id
        WHERE i.caja_id = ? AND (i.dotacion > 0 OR i.actual > 0) ORDER BY h.nombre
    """, (kid,)).fetchall()
    eventos = c.execute("""
        SELECT e.*, emp.nombre AS responsable,
               (SELECT COUNT(*) FROM caja_evento_items x
                 WHERE x.evento_id = e.id AND x.cantidad_real < x.cantidad_esperada) AS con_faltantes
        FROM caja_eventos e LEFT JOIN empleados emp ON emp.id = e.empleado_id
        WHERE e.caja_id = ? ORDER BY e.id DESC LIMIT 30
    """, (kid,)).fetchall()
    return render_template("caja.html", k=k, items=items, eventos=eventos,
                           estado=estado_caja(c, kid))


@app.route("/cajas/<int:kid>/transferir", methods=["POST"])
def caja_transferir(kid):
    """Todas las operaciones de contenido de la caja, en una transaccion:
    agregar (desde stock o alta), reponer faltante, pasar a stock, dar de baja.
    Solo se permite mientras la caja esta en el panol (no en el campo)."""
    c = db()
    if estado_caja(c, kid)["en_campo"]:
        flash("La caja está en el campo. Registrá el retorno para modificar su contenido.", "error")
        return redirect(url_for("caja", kid=kid))
    accion = request.form["accion"]
    hid = request.form.get("herramienta_id", type=int)
    cant = request.form.get("cantidad", type=int) or 0
    if not hid or cant < 1:
        flash("Elegí la herramienta y una cantidad válida.", "error")
        return redirect(url_for("caja", kid=kid))

    hta = c.execute("SELECT * FROM herramientas WHERE id = ?", (hid,)).fetchone()
    item = c.execute("SELECT * FROM caja_items WHERE caja_id = ? AND herramienta_id = ?",
                     (kid, hid)).fetchone()
    hoy = date.today().isoformat()

    def asegurar_item():
        if item is None:
            c.execute("""INSERT INTO caja_items (caja_id, herramienta_id, dotacion, actual)
                         VALUES (?,?,0,0)""", (kid, hid))

    error = None
    if accion in ("agregar_stock", "reponer"):
        # sale del stock fisico del panol
        pend = c.execute(f"SELECT pendiente FROM ({SALDO_HTA}) WHERE herramienta_id=?",
                         (hid,)).fetchone()
        disponible = hta["cantidad"] - (pend["pendiente"] if pend else 0)
        if cant > disponible:
            error = f"En el pañol hay {max(disponible,0)} disponible(s) de [{hta['codigo']}] {hta['nombre']}."
    if accion == "reponer" and not error:
        faltante = (item["dotacion"] - item["actual"]) if item else 0
        if cant > faltante:
            error = f"El faltante de esa herramienta es {max(faltante,0)}."
    if accion == "a_stock" and (not item or cant > item["actual"]):
        error = "La caja no tiene esa cantidad para pasar al stock."
    if accion == "baja" and (not item or cant > item["actual"]):
        error = "La caja no tiene esa cantidad para dar de baja."

    if error:
        flash(error, "error")
        return redirect(url_for("caja", kid=kid))

    asegurar_item()
    if accion == "agregar_stock":
        c.execute("UPDATE herramientas SET cantidad = cantidad - ? WHERE id = ?", (cant, hid))
        c.execute("""UPDATE caja_items SET dotacion = dotacion + ?, actual = actual + ?
                     WHERE caja_id = ? AND herramienta_id = ?""", (cant, cant, kid, hid))
        direccion, msj = "DESDE_STOCK", "Agregada a la caja desde el stock del pañol."
    elif accion == "agregar_alta":
        c.execute("""UPDATE caja_items SET dotacion = dotacion + ?, actual = actual + ?
                     WHERE caja_id = ? AND herramienta_id = ?""", (cant, cant, kid, hid))
        direccion, msj = "ALTA", "Agregada a la caja (sin tocar el stock del pañol)."
    elif accion == "reponer":
        c.execute("UPDATE herramientas SET cantidad = cantidad - ? WHERE id = ?", (cant, hid))
        c.execute("""UPDATE caja_items SET actual = actual + ?
                     WHERE caja_id = ? AND herramienta_id = ?""", (cant, kid, hid))
        direccion, msj = "DESDE_STOCK", "Faltante repuesto desde el stock del pañol."
    elif accion == "a_stock":
        c.execute("UPDATE herramientas SET cantidad = cantidad + ? WHERE id = ?", (cant, hid))
        c.execute("""UPDATE caja_items SET dotacion = MAX(dotacion - ?, 0), actual = actual - ?
                     WHERE caja_id = ? AND herramienta_id = ?""", (cant, cant, kid, hid))
        direccion, msj = "A_STOCK", "Pasada de la caja al stock del pañol."
    else:  # baja
        c.execute("""UPDATE caja_items SET dotacion = MAX(dotacion - ?, 0), actual = actual - ?
                     WHERE caja_id = ? AND herramienta_id = ?""", (cant, cant, kid, hid))
        direccion, msj = "BAJA", "Dada de baja de la caja."
    c.execute("""INSERT INTO transferencias (fecha, caja_id, herramienta_id, cantidad, direccion, observacion)
                 VALUES (?,?,?,?,?,?)""",
              (hoy, kid, hid, cant, direccion, request.form.get("observacion", "").strip() or None))
    c.commit()
    flash(f"{msj} ({cant} × [{hta['codigo']}] {hta['nombre']})", "ok")
    return redirect(url_for("caja", kid=kid))


@app.route("/cajas/<int:kid>/evento/<tipo>", methods=["GET", "POST"])
def caja_evento(kid, tipo):
    tipo = tipo.upper()
    if tipo not in ("ENVIO", "RETORNO"):
        return redirect(url_for("caja", kid=kid))
    c = db()
    k = c.execute("SELECT * FROM cajas WHERE id = ?", (kid,)).fetchone()
    if not k:
        return redirect(url_for("cajas"))
    items = c.execute("""
        SELECT i.*, h.codigo, h.nombre FROM caja_items i
        JOIN herramientas h ON h.id = i.herramienta_id
        WHERE i.caja_id = ? AND (i.dotacion > 0 OR i.actual > 0) ORDER BY h.nombre
    """, (kid,)).fetchall()

    if request.method == "POST":
        # herramienta "extra" que volvió y no estaba en la caja (solo retorno)
        extra_hid = request.form.get("extra_herramienta_id", type=int) if tipo == "RETORNO" else None
        extra_cant = request.form.get("extra_cantidad", type=int) if tipo == "RETORNO" else None
        hay_extra = bool(extra_hid and extra_cant and extra_cant > 0)
        if not items and not hay_extra:
            flash("La caja no tiene dotación cargada.", "error")
            return redirect(url_for("caja", kid=kid))
        fecha = request.form.get("fecha") or date.today().isoformat()
        cur = c.execute("""INSERT INTO caja_eventos (caja_id, tipo, fecha, empleado_id, destino, observacion)
                           VALUES (?,?,?,?,?,?) RETURNING id""",
                        (kid, tipo, fecha, request.form.get("empleado_id", type=int) or None,
                         request.form.get("destino", "").strip() or None,
                         request.form.get("observacion", "").strip() or None))
        evento_id = cur.fetchone()["id"]
        faltantes = 0
        for i in items:
            esperada = i["dotacion"] if tipo == "ENVIO" else \
                c.execute("""SELECT cantidad_real FROM caja_evento_items x
                             JOIN caja_eventos e ON e.id = x.evento_id
                             WHERE e.caja_id=? AND e.tipo='ENVIO' AND x.herramienta_id=?
                             ORDER BY e.id DESC LIMIT 1""", (kid, i["herramienta_id"])).fetchone()
            if tipo == "RETORNO":
                esperada = esperada["cantidad_real"] if esperada else i["dotacion"]
            real = request.form.get(f"real_{i['herramienta_id']}", type=int)
            real = i["dotacion" if tipo == "ENVIO" else "actual"] if real is None else max(real, 0)
            cond = request.form.get(f"cond_{i['herramienta_id']}", type=int) if tipo == "RETORNO" else None
            obs = request.form.get(f"obs_{i['herramienta_id']}", "").strip() or None
            c.execute("""INSERT INTO caja_evento_items
                         (evento_id, herramienta_id, cantidad_esperada, cantidad_real, condicion_id, observacion)
                         VALUES (?,?,?,?,?,?)""",
                      (evento_id, i["herramienta_id"], esperada, real, cond, obs))
            if real < esperada:
                faltantes += esperada - real
            if tipo == "RETORNO":
                # lo que la caja tiene ahora es lo que volvio
                c.execute("""UPDATE caja_items SET actual = ?
                             WHERE caja_id = ? AND herramienta_id = ?""",
                          (real, kid, i["herramienta_id"]))
        # RETORNO: volvió algo que no estaba en la caja -> se suma al contenido
        if hay_extra:
            existe_hta = c.execute("SELECT 1 FROM herramientas WHERE id=?", (extra_hid,)).fetchone()
            en_checklist = any(i["herramienta_id"] == extra_hid for i in items)
            if not existe_hta:
                flash("La herramienta que se cargó como «volvió» no existe.", "error")
            elif en_checklist:
                flash("Esa herramienta ya estaba en la lista de arriba; ajustá su cantidad ahí.", "error")
            else:
                ya = c.execute("SELECT 1 FROM caja_items WHERE caja_id=? AND herramienta_id=?",
                               (kid, extra_hid)).fetchone()
                if ya:   # ya figuraba (p.ej. había quedado en 0/0): se le suma
                    c.execute("""UPDATE caja_items SET dotacion = dotacion + ?, actual = actual + ?
                                 WHERE caja_id = ? AND herramienta_id = ?""",
                              (extra_cant, extra_cant, kid, extra_hid))
                else:
                    c.execute("""INSERT INTO caja_items (caja_id, herramienta_id, dotacion, actual)
                                 VALUES (?,?,?,?)""", (kid, extra_hid, extra_cant, extra_cant))
                c.execute("""INSERT INTO caja_evento_items
                             (evento_id, herramienta_id, cantidad_esperada, cantidad_real, condicion_id, observacion)
                             VALUES (?,?,0,?,?,?)""",
                          (evento_id, extra_hid, extra_cant, None, "Volvió sin haber salido"))
        c.commit()
        verbo = "Envío" if tipo == "ENVIO" else "Retorno"
        if faltantes:
            flash(f"{verbo} registrado con {faltantes} faltante(s). "
                  "Los faltantes quedan marcados en la dotación de la caja.", "error")
        else:
            flash(f"{verbo} registrado: la caja está completa. ✔", "ok")
        return redirect(url_for("caja", kid=kid))

    # esperado en el retorno: lo que salio en el ultimo envio (si existe)
    esperados = {}
    if tipo == "RETORNO":
        for i in items:
            r = c.execute("""SELECT x.cantidad_real FROM caja_evento_items x
                             JOIN caja_eventos e ON e.id = x.evento_id
                             WHERE e.caja_id=? AND e.tipo='ENVIO' AND x.herramienta_id=?
                             ORDER BY e.id DESC LIMIT 1""", (kid, i["herramienta_id"])).fetchone()
            esperados[i["herramienta_id"]] = r["cantidad_real"] if r else i["dotacion"]
    condiciones = c.execute("SELECT * FROM condiciones WHERE activo=1 ORDER BY nombre").fetchall()
    empleados_l = c.execute("SELECT * FROM empleados WHERE activo=1 ORDER BY nombre").fetchall()
    return render_template("caja_evento.html", k=k, tipo=tipo, items=items,
                           esperados=esperados, condiciones=condiciones,
                           empleados=empleados_l, fecha=date.today().isoformat())


@app.route("/herramientas/<int:hid>/editar", methods=["GET", "POST"])
def herramienta_editar(hid):
    c = db()
    h = c.execute("SELECT * FROM herramientas WHERE id = ?", (hid,)).fetchone()
    if not h:
        return redirect(url_for("herramientas"))
    if request.method == "POST":
        mod = request.form.get("modulo", "").strip() or None
        est = request.form.get("estante", "").strip() or None
        try:
            c.execute("""UPDATE herramientas SET codigo=?, nombre=?, detalle=?, cantidad=?,
                         modulo=?, estante=?, ubicacion=?, activo=? WHERE id=?""",
                      (request.form["codigo"].strip(), request.form["nombre"].strip(),
                       request.form.get("detalle", "").strip() or None,
                       request.form.get("cantidad", type=int) or 0,
                       mod, est, ubicacion_texto(mod, est),
                       1 if request.form.get("activo") else 0, hid))
            c.commit()
            flash("Herramienta actualizada.", "ok")
            return redirect(url_for("herramienta", hid=hid))
        except psycopg.errors.UniqueViolation:
            c.rollback()
            flash("Ya existe otra herramienta con ese código.", "error")
    gondolas = c.execute("SELECT * FROM gondolas WHERE activo=1 ORDER BY nombre").fetchall()
    estantes = c.execute("SELECT * FROM estantes WHERE activo=1 ORDER BY nombre").fetchall()
    return render_template("herramienta_editar.html", h=h, gondolas=gondolas, estantes=estantes)


# ---------------------------------------------------------------- maestros

@app.route("/maestros", methods=["GET", "POST"])
def maestros():
    c = db()
    if request.method == "POST":
        que = request.form["que"]
        rid = request.form.get("id", type=int)   # si viene, es edicion
        try:
            if que == "herramienta":
                codigo = request.form["codigo"].strip()
                nombre = request.form["nombre"].strip()
                detalle = request.form.get("detalle", "").strip() or None
                cantidad = request.form.get("cantidad", type=int) or 0
                mod = request.form.get("modulo", "").strip() or None
                est = request.form.get("estante", "").strip() or None
                ubic = ubicacion_texto(mod, est)   # se arma sola desde gondola + estante
                if rid:
                    c.execute("""UPDATE herramientas SET codigo=?, nombre=?, detalle=?, cantidad=?,
                                 modulo=?, estante=?, ubicacion=? WHERE id=?""",
                              (codigo, nombre, detalle, cantidad, mod, est, ubic, rid))
                else:
                    c.execute("""INSERT INTO herramientas (codigo, nombre, detalle, cantidad, modulo, estante, ubicacion)
                                 VALUES (?,?,?,?,?,?,?)""",
                              (codigo, nombre, detalle, cantidad, mod, est, ubic))
            elif que in ("empleado", "almacenista"):
                tabla = "empleados" if que == "empleado" else "almacenistas"
                nombre = request.form["nombre"].strip()
                dni = request.form.get("dni", "").strip() or None
                if rid:
                    c.execute(f"UPDATE {tabla} SET dni=?, nombre=? WHERE id=?", (dni, nombre, rid))
                else:
                    c.execute(f"INSERT INTO {tabla} (dni, nombre) VALUES (?,?)", (dni, nombre))
            elif que in ("condicion", "gondola", "estante"):
                tabla = {"condicion": "condiciones", "gondola": "gondolas", "estante": "estantes"}[que]
                nombre = request.form["nombre"].strip()
                if rid:
                    c.execute(f"UPDATE {tabla} SET nombre=? WHERE id=?", (nombre, rid))
                else:
                    c.execute(f"INSERT INTO {tabla} (nombre) VALUES (?)", (nombre,))
            c.commit()
            flash("Actualizado correctamente." if rid else "Agregado correctamente.", "ok")
        except psycopg.errors.UniqueViolation:
            c.rollback()
            flash("Ya existe un registro con ese código/nombre.", "error")
        tab_por_que = {"herramienta": "herramientas", "empleado": "trabajadores",
                       "almacenista": "almacenistas", "condicion": "condiciones",
                       "gondola": "gondolas", "estante": "estantes"}
        return redirect(url_for("maestros", tab=tab_por_que.get(que, "herramientas")))
    tab = request.args.get("tab", "herramientas")
    if tab not in ("herramientas", "trabajadores", "almacenistas", "condiciones",
                   "gondolas", "estantes"):
        tab = "herramientas"
    # registro a editar (edicion en el formulario de la izquierda)
    editando = None
    edit_id = request.args.get("editar", type=int)
    tabla_de_tab = {"herramientas": "herramientas", "trabajadores": "empleados",
                    "almacenistas": "almacenistas", "condiciones": "condiciones",
                    "gondolas": "gondolas", "estantes": "estantes"}
    if edit_id and tab in tabla_de_tab:
        editando = c.execute(f"SELECT * FROM {tabla_de_tab[tab]} WHERE id=?", (edit_id,)).fetchone()
    proximo_codigo = (c.execute(
        "SELECT MAX(CASE WHEN codigo ~ '^[0-9]+$' THEN codigo::int END) FROM herramientas"
    ).fetchone()[0] or 0) + 1
    herramientas = c.execute("SELECT * FROM herramientas ORDER BY codigo").fetchall()
    empleados = c.execute("SELECT * FROM empleados ORDER BY nombre").fetchall()
    almacenistas = c.execute("SELECT * FROM almacenistas ORDER BY nombre").fetchall()
    condiciones = c.execute("SELECT * FROM condiciones ORDER BY nombre").fetchall()
    gondolas = c.execute("SELECT * FROM gondolas ORDER BY nombre").fetchall()
    estantes = c.execute("SELECT * FROM estantes ORDER BY nombre").fetchall()

    # ids/valores "en uso" -> esos NO se pueden eliminar definitivamente (solo dar de baja)
    def _vals(*consultas):
        s = set()
        for q in consultas:
            s.update(r[0] for r in c.execute(q).fetchall() if r[0] is not None)
        return s
    mods = _vals("SELECT modulo FROM herramientas")
    ests = _vals("SELECT estante FROM herramientas")
    usados = {
        "herramientas": _vals("SELECT herramienta_id FROM movimientos",
                              "SELECT herramienta_id FROM caja_items",
                              "SELECT herramienta_id FROM caja_evento_items",
                              "SELECT herramienta_id FROM transferencias"),
        "empleados": _vals("SELECT empleado_id FROM movimientos",
                           "SELECT empleado_id FROM caja_eventos"),
        "almacenistas": _vals("SELECT almacenista_id FROM movimientos"),
        "condiciones": _vals("SELECT condicion_id FROM movimientos",
                             "SELECT condicion_id FROM caja_evento_items"),
        "gondolas": {g["id"] for g in gondolas if g["nombre"] in mods},
        "estantes": {e["id"] for e in estantes if e["nombre"] in ests},
    }
    return render_template("maestros.html", tab=tab, editando=editando,
                           proximo_codigo=proximo_codigo, herramientas=herramientas,
                           empleados=empleados, almacenistas=almacenistas,
                           condiciones=condiciones, gondolas=gondolas, estantes=estantes,
                           usados=usados)


@app.route("/maestros/baja", methods=["POST"])
def maestros_baja():
    tabla = request.form["tabla"]
    if tabla not in ("empleados", "almacenistas", "herramientas", "gondolas", "estantes", "condiciones"):
        return redirect(url_for("maestros"))
    c = db()
    c.execute(f"UPDATE {tabla} SET activo = 1 - activo WHERE id = ?", (request.form["id"],))
    c.commit()
    tab_por_tabla = {"empleados": "trabajadores", "almacenistas": "almacenistas",
                     "herramientas": "herramientas", "gondolas": "gondolas",
                     "estantes": "estantes", "condiciones": "condiciones"}
    return redirect(url_for("maestros", tab=tab_por_tabla.get(tabla, "herramientas")))


def maestro_en_uso(c, tabla, rid):
    """True si el registro tiene algo asociado (entonces NO se puede eliminar; solo dar de baja)."""
    refs = {
        "herramientas": [("movimientos", "herramienta_id"), ("caja_items", "herramienta_id"),
                         ("caja_evento_items", "herramienta_id"), ("transferencias", "herramienta_id")],
        "empleados": [("movimientos", "empleado_id"), ("caja_eventos", "empleado_id")],
        "almacenistas": [("movimientos", "almacenista_id")],
        "condiciones": [("movimientos", "condicion_id"), ("caja_evento_items", "condicion_id")],
    }
    if tabla in refs:
        for t, col in refs[tabla]:
            if c.execute(f"SELECT 1 FROM {t} WHERE {col}=? LIMIT 1", (rid,)).fetchone():
                return True
        return False
    if tabla in ("gondolas", "estantes"):
        col = "modulo" if tabla == "gondolas" else "estante"
        row = c.execute(f"SELECT nombre FROM {tabla} WHERE id=?", (rid,)).fetchone()
        if not row:
            return False
        return bool(c.execute(f"SELECT 1 FROM herramientas WHERE {col}=? LIMIT 1", (row[0],)).fetchone())
    return True   # tabla desconocida: por las dudas, no permitir borrar


@app.route("/maestros/eliminar", methods=["POST"])
def maestros_eliminar():
    tabla = request.form["tabla"]
    if tabla not in ("empleados", "almacenistas", "herramientas", "gondolas", "estantes", "condiciones"):
        return redirect(url_for("maestros"))
    rid = request.form.get("id", type=int)
    tab_por_tabla = {"empleados": "trabajadores", "almacenistas": "almacenistas",
                     "herramientas": "herramientas", "gondolas": "gondolas",
                     "estantes": "estantes", "condiciones": "condiciones"}
    tab = tab_por_tabla.get(tabla, "herramientas")
    c = db()
    if maestro_en_uso(c, tabla, rid):
        flash("No se puede eliminar: tiene datos asociados. Podés darlo de baja.", "error")
    else:
        c.execute(f"DELETE FROM {tabla} WHERE id=?", (rid,))
        c.commit()
        flash("Eliminado definitivamente.", "ok")
    return redirect(url_for("maestros", tab=tab))


@app.route("/api/registrar-lote", methods=["POST"])
def api_registrar_lote():
    """Registra varias entregas y/o devoluciones de un trabajador en una sola
    transaccion: si alguna linea no valida, no se guarda ninguna."""
    d = request.get_json(silent=True) or {}
    fecha = (d.get("fecha") or date.today().isoformat())[:10]
    empleado_id = d.get("empleado_id")
    almacenista_id = d.get("almacenista_id") or None
    forzar = bool(d.get("forzar"))
    items = d.get("items") or []
    c = db()

    errores = []
    if not empleado_id or not c.execute("SELECT 1 FROM empleados WHERE id=?", (empleado_id,)).fetchone():
        errores.append("Elegí un trabajador de la lista.")
    if not items:
        errores.append("La lista está vacía: agregá al menos una línea.")

    # validacion linea por linea, simulando el efecto acumulado del lote
    delta_global = {}   # herramienta_id -> variacion del pendiente total
    delta_emp = {}      # herramienta_id -> variacion del pendiente del trabajador
    lineas = []
    for i, it in enumerate(items, 1):
        tipo = it.get("tipo")
        hid = it.get("herramienta_id")
        cant = it.get("cantidad")
        if tipo not in ("ENTREGA", "DEVOLUCION"):
            errores.append(f"Línea {i}: tipo inválido.")
            continue
        if not isinstance(cant, int) or cant < 1:
            errores.append(f"Línea {i}: la cantidad debe ser 1 o más.")
            continue
        hta = c.execute("SELECT id, codigo, nombre, cantidad FROM herramientas WHERE id=?",
                        (hid,)).fetchone()
        if not hta:
            errores.append(f"Línea {i}: herramienta inexistente.")
            continue

        if not forzar and empleado_id:
            row = c.execute(f"SELECT pendiente FROM ({SALDO_HTA}) WHERE herramienta_id=?",
                            (hid,)).fetchone()
            pend_global = (row["pendiente"] if row else 0) + delta_global.get(hid, 0)
            row = c.execute(f"""SELECT pendiente FROM ({SALDO_EMP_HTA})
                                WHERE empleado_id=? AND herramienta_id=?""",
                            (empleado_id, hid)).fetchone()
            pend_emp = (row["pendiente"] if row else 0) + delta_emp.get(hid, 0)
            if tipo == "ENTREGA":
                disp = hta["cantidad"] - pend_global
                if cant > disp:
                    errores.append(f"Línea {i} — [{hta['codigo']}] {hta['nombre']}: "
                                   f"quedan {max(disp, 0)} disponible(s).")
            else:
                if cant > pend_emp:
                    errores.append(f"Línea {i} — [{hta['codigo']}] {hta['nombre']}: "
                                   f"el trabajador tiene {max(pend_emp, 0)} pendiente(s).")

        signo = 1 if tipo == "ENTREGA" else -1
        delta_global[hid] = delta_global.get(hid, 0) + signo * cant
        delta_emp[hid] = delta_emp.get(hid, 0) + signo * cant
        lineas.append({
            "tipo": tipo, "herramienta_id": hid, "cantidad": cant,
            "condicion_id": it.get("condicion_id") if tipo == "DEVOLUCION" else None,
            "observacion": (it.get("observacion") or "").strip() or None,
        })

    if errores:
        return jsonify({"ok": False, "errores": errores})

    try:
        for ln in lineas:
            c.execute("""
                INSERT INTO movimientos (tipo, fecha, empleado_id, herramienta_id, cantidad,
                                         condicion_id, almacenista_id, observacion)
                VALUES (?,?,?,?,?,?,?,?)
            """, (ln["tipo"], fecha, empleado_id, ln["herramienta_id"], ln["cantidad"],
                  ln["condicion_id"], almacenista_id, ln["observacion"]))
        c.commit()
    except psycopg.Error as e:
        c.rollback()
        return jsonify({"ok": False, "errores": [f"Error al guardar: {e}. No se registró nada."]})

    ent = sum(1 for ln in lineas if ln["tipo"] == "ENTREGA")
    dev = len(lineas) - ent
    partes = []
    if ent:
        partes.append(f"{ent} entrega(s)")
    if dev:
        partes.append(f"{dev} devolución(es)")
    return jsonify({"ok": True, "n": len(lineas), "mensaje": "Registrado: " + " y ".join(partes) + "."})


# ---------------------------------------------------------------- API autocompletar

@app.route("/api/herramientas")
def api_herramientas():
    q = request.args.get("q", "").strip()
    rows = db().execute(f"""
        SELECT h.id, h.codigo, h.nombre, h.ubicacion, h.cantidad,
               COALESCE(s.pendiente, 0) AS pendiente,
               h.cantidad - COALESCE(s.pendiente, 0) AS disponible
        FROM herramientas h LEFT JOIN ({SALDO_HTA}) s ON s.herramienta_id = h.id
        WHERE h.activo = 1 AND (h.codigo LIKE ? OR h.nombre LIKE ?)
        ORDER BY CASE WHEN h.codigo = ? THEN 0 WHEN h.codigo LIKE ? THEN 1 ELSE 2 END,
                 h.nombre LIMIT 15
    """, (q + "%", "%" + q + "%", q, q + "%")).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/empleados")
def api_empleados():
    q = request.args.get("q", "").strip()
    rows = db().execute("""
        SELECT id, dni, nombre FROM empleados
        WHERE activo = 1 AND (nombre LIKE ? OR dni LIKE ?)
        ORDER BY nombre LIMIT 15
    """, ("%" + q + "%", q + "%")).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/pendientes")
def api_pendientes():
    eid = request.args.get("empleado_id", type=int)
    if not eid:
        return jsonify([])
    rows = db().execute(f"""
        SELECT h.id, h.codigo, h.nombre, s.pendiente
        FROM ({SALDO_EMP_HTA}) s JOIN herramientas h ON h.id = s.herramienta_id
        WHERE s.empleado_id = ? AND s.pendiente > 0 ORDER BY h.nombre
    """, (eid,)).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    app.run(debug=True, port=8177)
