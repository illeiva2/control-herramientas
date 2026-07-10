// Autocompletado liviano para trabajador y herramienta, sin dependencias.
function combobox({ input, hidden, panel, url, render, onPick }) {
  let items = [], idx = -1, timer;

  function cerrar() { panel.classList.remove("abierta"); idx = -1; }

  function pintar() {
    panel.innerHTML = "";
    items.forEach((it, i) => {
      const div = document.createElement("div");
      div.className = "item" + (i === idx ? " activo" : "");
      div.innerHTML = render(it);
      div.addEventListener("mousedown", (e) => { e.preventDefault(); elegir(i); });
      panel.appendChild(div);
    });
    panel.classList.toggle("abierta", items.length > 0);
  }

  function elegir(i) {
    const it = items[i];
    if (!it) return;
    hidden.value = it.id;
    input.value = it.nombre;
    cerrar();
    onPick && onPick(it);
  }

  input.addEventListener("input", () => {
    hidden.value = "";
    onPick && onPick(null);
    clearTimeout(timer);
    items = []; pintar();   // no dejar visibles sugerencias de la busqueda anterior
    const q = input.value.trim();
    if (!q) return;
    timer = setTimeout(async () => {
      const r = await fetch(url + "?q=" + encodeURIComponent(q));
      const data = await r.json();
      if (input.value.trim() !== q) return;   // llego tarde: el usuario ya siguio escribiendo
      items = data;
      idx = items.length ? 0 : -1;
      pintar();
    }, 120);
  });

  input.addEventListener("keydown", (e) => {
    if (!panel.classList.contains("abierta")) return;
    if (e.key === "ArrowDown") { idx = Math.min(idx + 1, items.length - 1); pintar(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { idx = Math.max(idx - 1, 0); pintar(); e.preventDefault(); }
    else if (e.key === "Enter") { if (idx >= 0) { elegir(idx); e.preventDefault(); } }
    else if (e.key === "Escape") cerrar();
  });

  input.addEventListener("blur", () => setTimeout(cerrar, 150));
}

// ------- aviso de actualizacion disponible -------
document.addEventListener("DOMContentLoaded", async () => {
  const badge = document.getElementById("update-badge");
  if (!badge) return;
  try {
    const est = await (await fetch("/api/update-estado")).json();
    if (!est.hay_update) return;
    badge.textContent = `⬆ Actualizar a v${est.ultima}`;
    badge.hidden = false;
    badge.addEventListener("click", async () => {
      if (!confirm(`Hay una versión nueva (v${est.ultima}). El programa se reinicia solo ` +
                   `y los datos no se tocan.\n\n¿Actualizar ahora?`)) return;
      badge.disabled = true;
      badge.textContent = "Actualizando…";
      const r = await (await fetch("/actualizar", { method: "POST" })).json();
      if (!r.ok) {
        alert(r.mensaje);
        badge.disabled = false;
        badge.textContent = `⬆ Actualizar a v${est.ultima}`;
        return;
      }
      // esperar a que el programa vuelva a levantar y recargar
      const reintentar = setInterval(async () => {
        try {
          const e2 = await (await fetch("/api/update-estado", { cache: "no-store" })).json();
          if (e2.actual !== est.actual || !e2.hay_update) {
            clearInterval(reintentar);
            window.location.reload();
          }
        } catch (_) { /* servidor reiniciando, seguir esperando */ }
      }, 2000);
    });
  } catch (_) { /* sin red o chequeo pendiente: no mostrar nada */ }
});

// ------- filtro en vivo de la pagina Herramientas -------
function normalizar(t) {
  return t.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

document.addEventListener("DOMContentLoaded", () => {
  const buscar = document.getElementById("buscar-hta");
  if (!buscar) return;
  const selModulo = document.getElementById("filtro-modulo");
  const soloPrestadas = document.getElementById("filtro-prestadas");
  const contador = document.getElementById("contador");
  const grupos = [...document.querySelectorAll("#tabla-htas .grupo")];

  function filtrar() {
    const q = normalizar(buscar.value.trim());
    const mod = selModulo.value;
    let visibles = 0;
    grupos.forEach((g) => {
      let enGrupo = 0;
      if (mod && g.dataset.modulo !== mod) {
        g.hidden = true;
        return;
      }
      g.querySelectorAll(".fila-hta").forEach((tr) => {
        const pasa = (!q || normalizar(tr.dataset.buscar).includes(q)) &&
                     (!soloPrestadas.checked || tr.dataset.prestadas === "1");
        tr.hidden = !pasa;
        if (pasa) enGrupo++;
      });
      g.querySelector(".grupo-n").textContent = `(${enGrupo})`;
      g.hidden = enGrupo === 0;
      visibles += enGrupo;
    });
    contador.textContent = visibles;
    document.getElementById("sin-resultados").hidden = visibles > 0;
  }

  buscar.addEventListener("input", filtrar);
  selModulo.addEventListener("change", filtrar);
  soloPrestadas.addEventListener("change", filtrar);
  if (buscar.value) filtrar();
});

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("form-registro");
  if (!form) return;

  const $ = (id) => document.getElementById(id);
  const infoHta = $("info-hta");
  const empHidden = $("empleado_id");
  const empInput = $("empleado-buscar");
  const htaInput = $("herramienta-buscar");
  const htaHidden = $("herramienta_id");
  const cantidad = $("cantidad");
  const condSelect = $("condicion_id");
  const btnRegistrar = $("btn-registrar");

  // ------- estado del lote -------
  let lote = [];      // {tipo, herramienta_id, codigo, nombre, cantidad, condicion_id, condicion, observacion}
  let htaElegida = null;

  function tipoActual() {
    return form.querySelector("input[name=tipo]:checked").value;
  }

  function mensaje(ok, texto) {
    const cajaOk = $("msg-ok"), cajaErr = $("msg-error");
    cajaOk.hidden = true; cajaErr.hidden = true;
    const caja = ok ? cajaOk : cajaErr;
    caja.innerHTML = texto;
    caja.hidden = false;
    caja.scrollIntoView({ block: "nearest" });
  }

  function pintarLote() {
    const body = $("lote-body");
    body.innerHTML = "";
    lote.forEach((ln, i) => {
      const tr = document.createElement("tr");
      const esEnt = ln.tipo === "ENTREGA";
      tr.innerHTML =
        `<td><span class="tag ${esEnt ? "ent" : "dev"}">${ln.tipo}</span></td>` +
        `<td>[${ln.codigo}] ${ln.nombre}</td>` +
        `<td class="der">${ln.cantidad}</td>` +
        `<td>${esEnt ? "" : (ln.condicion || "")}</td>` +
        `<td>${ln.observacion || ""}</td>` +
        `<td><button type="button" class="btn mini peligro" title="Quitar">✕</button></td>`;
      tr.querySelector("button").addEventListener("click", () => {
        lote.splice(i, 1);
        pintarLote();
      });
      body.appendChild(tr);
    });
    $("tabla-lote").hidden = lote.length === 0;
    $("lote-vacio").hidden = lote.length > 0;
    btnRegistrar.disabled = lote.length === 0;
    btnRegistrar.textContent = `Registrar todo (${lote.length})`;
  }

  function agregarLinea(tipo, hta, cant, condId, condNombre, obs) {
    lote.push({
      tipo, herramienta_id: hta.id, codigo: hta.codigo, nombre: hta.nombre,
      cantidad: cant, condicion_id: tipo === "DEVOLUCION" ? condId : null,
      condicion: tipo === "DEVOLUCION" ? condNombre : null,
      observacion: obs || null,
    });
    pintarLote();
  }

  function mostrarInfoHta(it) {
    htaElegida = it;
    if (!it) { infoHta.textContent = ""; return; }
    const partes = [];
    if (it.ubicacion) partes.push("📍 " + it.ubicacion);
    partes.push(`Inventario: ${it.cantidad} · Prestadas: ${it.pendiente} · Disponibles: ${it.disponible}`);
    infoHta.textContent = partes.join("  ·  ");
  }

  combobox({
    input: htaInput,
    hidden: htaHidden,
    panel: $("herramienta-sug"),
    url: "/api/herramientas",
    render: (it) =>
      `<div><b>[${it.codigo}]</b> ${it.nombre}</div>` +
      `<div class="sub">${it.ubicacion || ""} — disp. ${it.disponible}</div>`,
    onPick: (it) => { mostrarInfoHta(it); if (it) cantidad.focus(); },
  });

  async function cargarPendientes() {
    const box = $("pendientes-emp"), chips = $("chips-pendientes");
    const eid = empHidden.value;
    if (!eid) { box.hidden = true; return; }
    const r = await fetch("/api/pendientes?empleado_id=" + eid);
    const data = await r.json();
    chips.innerHTML = "";
    data.forEach((p) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = `[${p.codigo}] ${p.nombre} × ${p.pendiente}`;
      b.addEventListener("click", () => {
        agregarLinea("DEVOLUCION", p, p.pendiente,
          parseInt(condSelect.value || form.dataset.condicionDefecto, 10),
          condSelect.options[condSelect.selectedIndex]?.text, null);
      });
      chips.appendChild(b);
    });
    box.hidden = data.length === 0;
  }

  combobox({
    input: empInput,
    hidden: empHidden,
    panel: $("empleado-sug"),
    url: "/api/empleados",
    render: (it) => `<div>${it.nombre}</div><div class="sub">DNI ${it.dni || "—"}</div>`,
    onPick: cargarPendientes,
  });

  // alternar entrega/devolucion (para las proximas lineas)
  form.querySelectorAll("input[name=tipo]").forEach((radio) => {
    radio.addEventListener("change", () => {
      form.querySelectorAll(".tab").forEach((t) => t.classList.remove("on"));
      radio.closest(".tab").classList.add("on");
      form.querySelector(".solo-devolucion").hidden = tipoActual() !== "DEVOLUCION";
    });
  });

  // ------- agregar linea -------
  function agregarDesdeFormulario() {
    if (!htaHidden.value || !htaElegida) {
      mensaje(false, "Elegí la herramienta desde la lista de sugerencias.");
      htaInput.focus();
      return;
    }
    const cant = parseInt(cantidad.value, 10);
    if (!cant || cant < 1) {
      mensaje(false, "La cantidad debe ser 1 o más.");
      cantidad.focus();
      return;
    }
    $("msg-error").hidden = true;
    agregarLinea(tipoActual(), htaElegida, cant,
      parseInt(condSelect.value, 10),
      condSelect.options[condSelect.selectedIndex]?.text,
      $("observacion").value.trim());
    // listo para la siguiente linea
    htaInput.value = ""; htaHidden.value = ""; htaElegida = null;
    infoHta.textContent = ""; cantidad.value = 1; $("observacion").value = "";
    htaInput.focus();
  }

  $("btn-agregar").addEventListener("click", agregarDesdeFormulario);
  cantidad.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); agregarDesdeFormulario(); }
  });

  // ------- registrar todo -------
  btnRegistrar.addEventListener("click", async () => {
    if (!empHidden.value) {
      mensaje(false, "Elegí el trabajador desde la lista de sugerencias.");
      empInput.focus();
      return;
    }
    btnRegistrar.disabled = true;
    try {
      const r = await fetch("/api/registrar-lote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fecha: $("fecha").value,
          empleado_id: parseInt(empHidden.value, 10),
          almacenista_id: parseInt($("almacenista_id").value, 10) || null,
          forzar: $("forzar").checked,
          items: lote.map((ln) => ({
            tipo: ln.tipo, herramienta_id: ln.herramienta_id, cantidad: ln.cantidad,
            condicion_id: ln.condicion_id, observacion: ln.observacion,
          })),
        }),
      });
      const res = await r.json();
      if (res.ok) {
        lote = [];
        pintarLote();
        $("forzar").checked = false;
        mensaje(true, res.mensaje);
        cargarPendientes();   // refresca los chips
        empInput.focus();
      } else {
        mensaje(false, "<b>No se registró nada.</b><br>" + res.errores.join("<br>"));
        btnRegistrar.disabled = false;
      }
    } catch (err) {
      mensaje(false, "Error de conexión con el servidor: " + err);
      btnRegistrar.disabled = false;
    }
  });

  // si viene precargado el empleado (query param), buscar pendientes
  if (empHidden.value) cargarPendientes();
});
