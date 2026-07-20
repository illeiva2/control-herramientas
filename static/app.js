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
      let intentos = 0;
      const reintentar = setInterval(async () => {
        intentos++;
        if (intentos > 60) {   // ~2 minutos: algo se trabó, avisar en vez de esperar infinito
          clearInterval(reintentar);
          alert("La actualización está tardando más de lo normal.\n\n" +
                "1. Cerrá esta pestaña.\n" +
                "2. Abrí el programa de nuevo desde el acceso directo (si no abre, esperá un minuto y reintentá).\n" +
                "3. Si sigue sin abrir, reinstalá con el Setup desde GitHub: los datos no se pierden.");
          window.location.reload();
          return;
        }
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

// ------- almacenista activo (selector del header, persistido local) -------
document.addEventListener("DOMContentLoaded", () => {
  const KEY = "panol-almacenista";
  const hdr = document.getElementById("almacenista-activo");
  const regSel = document.getElementById("almacenista_id");
  const guardado = localStorage.getItem(KEY) || "";
  const tiene = (sel, val) => sel && val && sel.querySelector('option[value="' + val + '"]');

  // header: aplicar el guardado si existe; si no, queda el primero (nunca vacío)
  if (tiene(hdr, guardado)) hdr.value = guardado;
  const activo = hdr ? hdr.value : guardado;
  // persistir el activo efectivo para que quede fijo entre páginas/reinicios
  if (hdr && activo && activo !== guardado) localStorage.setItem(KEY, activo);

  // en Registrar: usar el almacenista activo por defecto, salvo que la URL fije uno
  if (regSel) {
    const urlAlm = new URLSearchParams(location.search).get("almacenista_id");
    if (!urlAlm && tiene(regSel, activo)) regSel.value = activo;
  }

  if (hdr) {
    hdr.addEventListener("change", () => {
      localStorage.setItem(KEY, hdr.value);
      if (tiene(regSel, hdr.value)) regSel.value = hdr.value;
    });
  }
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
  const btnExpandir = document.getElementById("btn-expandir");
  const gondolas = [...document.querySelectorAll("#catalogo .gondola")];

  function filtrar() {
    const q = normalizar(buscar.value.trim());
    const mod = selModulo.value;
    const filtrando = q || mod || soloPrestadas.checked;
    let visibles = 0;
    gondolas.forEach((g) => {
      if (mod && g.dataset.modulo !== mod) {
        g.hidden = true;
        return;
      }
      let enGondola = 0;
      g.querySelectorAll(".seccion").forEach((s) => {
        let enSeccion = 0;
        s.querySelectorAll(".fila-hta").forEach((tr) => {
          const pasa = (!q || normalizar(tr.dataset.buscar).includes(q)) &&
                       (!soloPrestadas.checked || tr.dataset.prestadas === "1");
          tr.hidden = !pasa;
          if (pasa) enSeccion++;
        });
        const n = s.querySelector(".grupo-n");
        if (n) n.textContent = `${enSeccion}`;
        s.hidden = enSeccion === 0;
        if (s.tagName === "DETAILS") s.open = filtrando ? enSeccion > 0 : false;
        enGondola += enSeccion;
      });
      const gn = g.querySelector(".g-titulo .grupo-n");
      if (gn) gn.textContent = `${enGondola} ítems`;
      g.hidden = enGondola === 0;
      visibles += enGondola;
    });
    contador.textContent = visibles;
    document.getElementById("sin-resultados").hidden = visibles > 0;
  }

  let expandido = false;
  btnExpandir.addEventListener("click", () => {
    expandido = !expandido;
    gondolas.forEach((g) => {
      if (g.hidden) return;
      g.querySelectorAll("details.seccion").forEach((s) => { if (!s.hidden) s.open = expandido; });
    });
    btnExpandir.textContent = expandido ? "Colapsar todo" : "Expandir todo";
  });

  buscar.addEventListener("input", filtrar);
  selModulo.addEventListener("change", filtrar);
  soloPrestadas.addEventListener("change", filtrar);
  if (buscar.value) filtrar();
});

// ------- autocompletado para agregar herramientas a una caja -------
document.addEventListener("DOMContentLoaded", () => {
  const panelCaja = document.getElementById("form-agregar-caja");
  if (!panelCaja) return;
  const infoHta = document.getElementById("info-hta");
  const hidden = document.getElementById("herramienta_id");
  const inputHta = document.getElementById("herramienta-buscar");
  const cantidad = document.getElementById("caja-cantidad");
  const origen = document.getElementById("caja-origen");
  const btnGuardar = document.getElementById("caja-btn-guardar");
  let htaElegida = null;
  let lote = [];

  combobox({
    input: inputHta,
    hidden,
    panel: document.getElementById("herramienta-sug"),
    url: "/api/herramientas",
    render: (it) =>
      `<div><b>[${it.codigo}]</b> ${it.nombre}</div>` +
      `<div class="sub">${it.ubicacion || ""} — disp. en pañol: ${it.disponible}</div>`,
    onPick: (it) => {
      htaElegida = it;
      infoHta.textContent = it
        ? `Stock pañol: ${it.cantidad} · Disponibles: ${it.disponible}` : "";
      if (it) cantidad.focus();
    },
  });

  function pintarLoteCaja() {
    const body = document.getElementById("caja-lote-body");
    body.innerHTML = "";
    lote.forEach((ln, i) => {
      const tr = document.createElement("tr");
      const esAlta = ln.accion === "agregar_alta";
      tr.innerHTML =
        `<td><span class="code">${ln.codigo}</span> ${ln.nombre}</td>` +
        `<td class="centro num-cell">${ln.cantidad}</td>` +
        `<td><span class="${esAlta ? "badge-ok" : "badge-info"}">${esAlta ? "Propia de la caja" : "Del stock"}</span></td>` +
        `<td class="der"><button type="button" class="btn mini peligro" title="Quitar">✕</button></td>`;
      tr.querySelector("button").addEventListener("click", () => {
        lote.splice(i, 1);
        pintarLoteCaja();
      });
      body.appendChild(tr);
    });
    document.getElementById("caja-lote-tabla").hidden = lote.length === 0;
    btnGuardar.disabled = lote.length === 0;
    btnGuardar.textContent = `Guardar en la caja (${lote.length})`;
    const delStock = lote.filter((l) => l.accion === "agregar_stock").length;
    document.getElementById("caja-lote-resumen").textContent =
      delStock ? `${delStock} línea(s) descuentan del stock del pañol` : "";
  }

  function agregarLineaCaja() {
    if (!hidden.value || !htaElegida) {
      alert("Elegí la herramienta desde la lista de sugerencias.");
      inputHta.focus();
      return;
    }
    const cant = parseInt(cantidad.value, 10);
    if (!cant || cant < 1) {
      alert("La cantidad debe ser 1 o más.");
      return;
    }
    lote.push({
      herramienta_id: htaElegida.id, codigo: htaElegida.codigo, nombre: htaElegida.nombre,
      cantidad: cant, accion: origen.value,
    });
    pintarLoteCaja();
    inputHta.value = ""; hidden.value = ""; htaElegida = null;
    infoHta.textContent = ""; cantidad.value = 1;
    inputHta.focus();
  }

  document.getElementById("caja-btn-agregar").addEventListener("click", agregarLineaCaja);
  cantidad.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); agregarLineaCaja(); }
  });

  document.getElementById("form-caja-lote").addEventListener("submit", (e) => {
    if (!lote.length) { e.preventDefault(); return; }
    document.getElementById("caja-items-json").value = JSON.stringify(
      lote.map((l) => ({ herramienta_id: l.herramienta_id, cantidad: l.cantidad, accion: l.accion }))
    );
  });
});

// ------- autocompletado del "volvió algo que no estaba" (retorno de caja) -------
document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("extra-buscar");
  if (!input) return;
  combobox({
    input,
    hidden: document.getElementById("extra_herramienta_id"),
    panel: document.getElementById("extra-sug"),
    url: "/api/herramientas",
    render: (it) =>
      `<div><b>[${it.codigo}]</b> ${it.nombre}</div>` +
      `<div class="sub">${it.ubicacion || ""}</div>`,
  });
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

  const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));

  function lineaExcede(ln) {
    if (ln.tipo === "ENTREGA") return ln.disp != null && ln.cantidad > ln.disp;
    return ln.pend != null && ln.cantidad > ln.pend;
  }

  function pintarLote() {
    const body = $("lote-body");
    body.innerHTML = "";
    lote.forEach((ln, i) => {
      const tr = document.createElement("tr");
      tr.className = "lote-row";
      const esEnt = ln.tipo === "ENTREGA";
      const sub = [];
      if (!esEnt && ln.condicion) sub.push(esc(ln.condicion));
      if (ln.observacion) sub.push(esc(ln.observacion));
      const over = lineaExcede(ln)
        ? `<span class="lote-over">⚠ Supera lo disponible (${esEnt ? ln.disp : ln.pend})</span>` : "";
      tr.innerHTML =
        `<td><span class="tag ${esEnt ? "ent" : "dev"}">${esEnt ? "Entrega" : "Devol."}</span></td>` +
        `<td><span class="code">${esc(ln.codigo)}</span>` +
          `<span style="display:block">${esc(ln.nombre)}</span>` +
          (sub.length ? `<span class="detalle">${sub.join(" · ")}</span>` : "") + over + `</td>` +
        `<td><span class="stepper"><button type="button" data-a="dec">−</button>` +
          `<span class="val">${ln.cantidad}</span><button type="button" data-a="inc">+</button></span></td>` +
        `<td class="der"><button type="button" class="btn-icon" title="Quitar">` +
          `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/></svg></button></td>`;
      tr.querySelector('[data-a=dec]').addEventListener("click", () => {
        if (ln.cantidad > 1) { ln.cantidad--; pintarLote(); }
      });
      tr.querySelector('[data-a=inc]').addEventListener("click", () => { ln.cantidad++; pintarLote(); });
      tr.querySelector(".btn-icon").addEventListener("click", () => { lote.splice(i, 1); pintarLote(); });
      body.appendChild(tr);
    });
    $("tabla-lote").hidden = lote.length === 0;
    $("lote-vacio").hidden = lote.length > 0;
    const cc = $("cart-count"); if (cc) cc.textContent = lote.length;
    btnRegistrar.disabled = lote.length === 0;
    btnRegistrar.textContent = `Registrar todo (${lote.length})`;
    pintarResumen();
  }

  function pintarResumen() {
    const set = (id, v) => { const el = $(id); if (el) el.textContent = v; };
    set("sum-worker", empHidden.value ? empInput.value : "—");
    set("sum-ent", lote.filter((l) => l.tipo === "ENTREGA").length);
    set("sum-dev", lote.filter((l) => l.tipo === "DEVOLUCION").length);
    set("sum-units", lote.reduce((a, l) => a + l.cantidad, 0));
    const over = $("sum-over");
    if (over) over.hidden = !lote.some(lineaExcede);
  }

  function agregarLinea(tipo, hta, cant, condId, condNombre, obs) {
    lote.push({
      tipo, herramienta_id: hta.id, codigo: hta.codigo, nombre: hta.nombre,
      cantidad: cant, condicion_id: tipo === "DEVOLUCION" ? condId : null,
      condicion: tipo === "DEVOLUCION" ? condNombre : null,
      observacion: obs || null,
      disp: hta.disponible != null ? hta.disponible : null,
      pend: hta.pendiente != null ? hta.pendiente : null,
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
    if (!eid) { box.hidden = true; pintarResumen(); return; }
    const r = await fetch("/api/pendientes?empleado_id=" + eid);
    const data = await r.json();
    chips.innerHTML = "";
    data.forEach((p) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = `[${p.codigo}] ${p.nombre} × ${p.pendiente}`;
      b.addEventListener("click", () => {
        // prellenar el formulario del paso 2 en modo devolucion; el usuario
        // revisa condicion/observacion y toca "Agregar a la lista"
        const radio = form.querySelector('input[name=tipo][value="DEVOLUCION"]');
        radio.checked = true;
        radio.dispatchEvent(new Event("change"));
        htaHidden.value = p.id;
        htaInput.value = p.nombre;
        mostrarInfoHta(p);   // fija htaElegida = p (trae el id de la herramienta)
        infoHta.textContent = `Pendiente de devolver: ${p.pendiente}`;
        cantidad.value = p.pendiente;
        (condSelect || cantidad).focus();
      });
      chips.appendChild(b);
    });
    box.hidden = data.length === 0;
    pintarResumen();
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
