import csv
import io
import sqlite3
import sys
from datetime import date
from pathlib import Path

from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, url_for, Response)

import updater
from version import VERSION

if getattr(sys, "frozen", False):
    # empaquetado con PyInstaller: recursos junto al bundle, datos junto al exe
    RES = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    BASE = Path(sys.executable).parent
else:
    RES = BASE = Path(__file__).parent

DB = BASE / "data" / "panol.db"

app = Flask(__name__,
            template_folder=str(RES / "templates"),
            static_folder=str(RES / "static"))
app.secret_key = "panol-local"  # app local en una sola PC, sin exposicion externa


def init_db():
    """Crea la base vacia si no existe (instalacion nueva)."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript((RES / "schema.sql").read_text(encoding="utf-8"))
    con.commit()
    con.close()


init_db()


@app.context_processor
def inyectar_version():
    return {"version_app": VERSION}


@app.route("/api/update-estado")
def api_update_estado():
    return jsonify(updater.estado)


@app.route("/actualizar", methods=["POST"])
def actualizar():
    ok, mensaje = updater.aplicar()
    return jsonify({"ok": ok, "mensaje": mensaje})


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


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
    condiciones = c.execute("SELECT * FROM condiciones ORDER BY nombre").fetchall()
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

    grupos = []
    for h in sorted(rows, key=orden):
        etiqueta = h["ubicacion"] or "Sin ubicación"
        mod = str(h["modulo"] or "")
        if not grupos or grupos[-1]["etiqueta"] != etiqueta:
            grupos.append({"etiqueta": etiqueta, "modulo": mod, "items": []})
        grupos[-1]["items"].append(h)

    modulos = []  # para el selector: [(valor, nombre)]
    for g in grupos:
        par = (g["modulo"], nombre_modulo(g["modulo"] or None))
        if par not in modulos:
            modulos.append(par)

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
        except sqlite3.IntegrityError:
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
    lista = [dict(f, **estado_caja(c, f["id"])) for f in filas]
    return render_template("cajas.html", cajas=lista)


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
    agregar (desde stock o alta), reponer faltante, pasar a stock, dar de baja."""
    c = db()
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
        if not items:
            flash("La caja no tiene dotación cargada.", "error")
            return redirect(url_for("caja", kid=kid))
        fecha = request.form.get("fecha") or date.today().isoformat()
        cur = c.execute("""INSERT INTO caja_eventos (caja_id, tipo, fecha, empleado_id, destino, observacion)
                           VALUES (?,?,?,?,?,?)""",
                        (kid, tipo, fecha, request.form.get("empleado_id", type=int) or None,
                         request.form.get("destino", "").strip() or None,
                         request.form.get("observacion", "").strip() or None))
        evento_id = cur.lastrowid
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
    condiciones = c.execute("SELECT * FROM condiciones ORDER BY nombre").fetchall()
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
        try:
            c.execute("""UPDATE herramientas SET codigo=?, nombre=?, detalle=?, cantidad=?,
                         modulo=?, estante=?, ubicacion=?, activo=? WHERE id=?""",
                      (request.form["codigo"].strip(), request.form["nombre"].strip(),
                       request.form.get("detalle", "").strip() or None,
                       request.form.get("cantidad", type=int) or 0,
                       request.form.get("modulo", "").strip() or None,
                       request.form.get("estante", "").strip() or None,
                       request.form.get("ubicacion", "").strip() or None,
                       1 if request.form.get("activo") else 0, hid))
            c.commit()
            flash("Herramienta actualizada.", "ok")
            return redirect(url_for("herramienta", hid=hid))
        except sqlite3.IntegrityError:
            flash("Ya existe otra herramienta con ese código.", "error")
    return render_template("herramienta_editar.html", h=h)


# ---------------------------------------------------------------- maestros

@app.route("/maestros", methods=["GET", "POST"])
def maestros():
    c = db()
    if request.method == "POST":
        que = request.form["que"]
        try:
            if que == "herramienta":
                mod, est = request.form.get("modulo", "").strip(), request.form.get("estante", "").strip()
                ubic = request.form.get("ubicacion", "").strip()
                c.execute("""INSERT INTO herramientas (codigo, nombre, detalle, cantidad, modulo, estante, ubicacion)
                             VALUES (?,?,?,?,?,?,?)""",
                          (request.form["codigo"].strip(), request.form["nombre"].strip(),
                           request.form.get("detalle", "").strip() or None,
                           request.form.get("cantidad", type=int) or 0, mod or None, est or None,
                           ubic or None))
            elif que == "empleado":
                c.execute("INSERT INTO empleados (dni, nombre) VALUES (?,?)",
                          (request.form.get("dni", "").strip() or None, request.form["nombre"].strip()))
            elif que == "almacenista":
                c.execute("INSERT INTO almacenistas (dni, nombre) VALUES (?,?)",
                          (request.form.get("dni", "").strip() or None, request.form["nombre"].strip()))
            elif que == "condicion":
                c.execute("INSERT INTO condiciones (nombre) VALUES (?)",
                          (request.form["nombre"].strip(),))
            c.commit()
            flash("Agregado correctamente.", "ok")
        except sqlite3.IntegrityError:
            flash("Ya existe un registro con ese código/nombre.", "error")
        return redirect(url_for("maestros"))
    datos = {
        "almacenistas": c.execute("SELECT * FROM almacenistas ORDER BY nombre").fetchall(),
        "condiciones": c.execute("SELECT * FROM condiciones ORDER BY nombre").fetchall(),
    }
    return render_template("maestros.html", **datos)


@app.route("/maestros/baja", methods=["POST"])
def maestros_baja():
    tabla = request.form["tabla"]
    if tabla not in ("empleados", "almacenistas", "herramientas"):
        return redirect(url_for("maestros"))
    c = db()
    c.execute(f"UPDATE {tabla} SET activo = 1 - activo WHERE id = ?", (request.form["id"],))
    c.commit()
    return redirect(request.referrer or url_for("maestros"))


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
    except sqlite3.Error as e:
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
