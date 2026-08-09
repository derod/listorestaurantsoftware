// Carrito como lista de LÍNEAS en secuencia. Dos modos según la pestaña:
//  - General: agrupa por producto (tocar A, B, A → A ×2). "Pedir insumos".
//  - Desayuno/Uber: comanda secuencial; agrupa solo toques CONSECUTIVOS del
//    mismo producto; volver a un producto anterior crea una línea nueva.
let lines = [];      // [{product_id, name, quantity}]
let addStack = [];   // refs de línea, una por unidad agregada (para "Quitar último")

// i18n: texto traducido con fallback en español.
const T = (k, fb) => (window.I18N && window.I18N[k]) || fb;

function renderSummary() {
  const summary = document.getElementById("orderSummary");
  const total = document.getElementById("totalItems");
  if (!lines.length) {
    summary.innerHTML = T("salon.no_productos", "No hay productos.");
    summary.classList.add("empty-state");
    total.textContent = "0";
    return;
  }
  summary.classList.remove("empty-state");
  summary.innerHTML = lines.map(item => `
    <div class="summary-item">
      <span>${item.name}</span>
      <strong>${item.quantity}</strong>
    </div>
  `).join("");
  total.textContent = lines.reduce((acc, item) => acc + item.quantity, 0);
}

function addProduct(id, name) {
  const pid = Number(id);
  const sequential = (stationCategory === "Desayuno" || stationCategory === "Uber");
  let line = null;
  if (sequential) {
    const last = lines[lines.length - 1];
    if (last && last.product_id === pid) line = last;   // solo agrupa consecutivos
  } else {
    line = lines.find(l => l.product_id === pid);        // General: agrupa en cualquier lado
  }
  if (!line) { line = { product_id: pid, name, quantity: 0 }; lines.push(line); }
  line.quantity += 1;
  addStack.push(line);
  renderSummary();
}

/* ─── Toast (reemplaza los alert nativos) ───────────────────────────── */
function toast(message, type) {
  let host = document.getElementById("kdsToastHost");
  if (!host) {
    host = document.createElement("div");
    host.id = "kdsToastHost";
    host.style.cssText = "position:fixed;top:20px;left:50%;transform:translateX(-50%);z-index:100000;display:flex;flex-direction:column;gap:10px;align-items:center;pointer-events:none;";
    document.body.appendChild(host);
  }
  const t = document.createElement("div");
  const ok = type !== "error";
  t.textContent = message;
  t.style.cssText =
    "pointer-events:auto;min-width:220px;max-width:90vw;padding:16px 26px;border-radius:14px;font-size:22px;font-weight:800;text-align:center;color:#fff;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.45);opacity:0;transform:translateY(-12px);transition:opacity .2s,transform .2s;" +
    (ok ? "background:var(--green,#2e7d32);" : "background:var(--red,#c62828);");
  host.appendChild(t);
  requestAnimationFrame(() => { t.style.opacity = "1"; t.style.transform = "translateY(0)"; });
  setTimeout(() => {
    t.style.opacity = "0";
    t.style.transform = "translateY(-12px)";
    setTimeout(() => t.remove(), 250);
  }, 2600);
}

async function submitOrder() {
  const items = lines.filter(x => x.quantity > 0).map(x => ({ product_id: x.product_id, quantity: x.quantity }));
  if (!items.length) return toast(T("msg.agrega_productos", "Agrega productos primero."), "error");
  // En modo Uber el nombre de la orden es obligatorio.
  let orderLabel = null;
  if (stationCategory === "Uber") {
    const nameEl = document.getElementById("uberOrderName");
    orderLabel = ((nameEl && nameEl.value) || "").trim();
    if (!orderLabel) { toast("Escribe el nombre de la orden Uber.", "error"); if (nameEl) nameEl.focus(); return; }
  }
  const tableSel = document.getElementById("tableSelect");
  const tableId = (tableSel && tableSel.value) ? parseInt(tableSel.value, 10) : null;
  const res = await fetch("/api/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_role: window.KDS_CONFIG.sourceRole, items, waiter_id: window.KDS_CONFIG.waiterId, waiter_name: window.KDS_CONFIG.waiterName, order_label: orderLabel, table_id: tableId })
  });
  if (!res.ok) return toast(T("msg.no_enviar", "No se pudo enviar."), "error");
  lines = [];
  addStack = [];
  renderSummary();
  const nameEl = document.getElementById("uberOrderName");
  if (nameEl) nameEl.value = "";
  toast(T("msg.pedido_enviado", "Pedido enviado."));
  fetchRecent();
}

let stationProducts = [];
let stationSort = "manual";    // "manual" | "az"
let stationReorder = false;
let stationCategory = "General";  // pestaña de categoría activa
let stationQuitar = false;        // modo "Quitar" (ocultar productos del panel)
let hiddenIds = new Set();        // productos ocultos en este dispositivo (localStorage)
try { hiddenIds = new Set(JSON.parse(localStorage.getItem("station_hidden") || "[]").map(Number)); } catch (e) {}
function saveHidden() { try { localStorage.setItem("station_hidden", JSON.stringify([...hiddenIds])); } catch (e) {} }
function toggleHidden(id) {
  id = Number(id);
  if (hiddenIds.has(id)) hiddenIds.delete(id); else hiddenIds.add(id);
  saveHidden();
  applyCategoryFilter();
}

function productImg(p) {
  return p.image_path ? `<img src="${p.image_path}" alt="" style="width:100%;height:110px;object-fit:cover;border-radius:12px;margin-bottom:8px;">` : "";
}

function currentProductOrder() {
  const list = stationProducts.slice();
  if (stationSort === "az") list.sort((a, b) => a.name.localeCompare(b.name));
  return list;
}

function flashTap(btn) {
  btn.classList.remove("tapped");
  void btn.offsetWidth;        // reinicia la animación si se toca rápido de nuevo
  btn.classList.add("tapped");
}

function bindProductButtons() {
  document.querySelectorAll("#productsGrid .product-btn").forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      if (stationQuitar) { toggleHidden(btn.dataset.productId); return; }
      flashTap(btn);
      addProduct(btn.dataset.productId, btn.dataset.productName);
    });
    btn.addEventListener("animationend", () => btn.classList.remove("tapped"));
  });
}

// Muestra solo los productos de la categoría (pestaña) activa. En modo
// reordenar no se filtra (se ven todos para poder ordenarlos).
function applyCategoryFilter() {
  const grid = document.getElementById("productsGrid");
  if (!grid || stationReorder) return;
  // "Uber" es un modo de delivery: reutiliza los productos de "Desayuno".
  const shown = (stationCategory === "Uber") ? "Desayuno" : stationCategory;
  grid.querySelectorAll(".product-btn").forEach(btn => {
    const c = btn.dataset.category || "General";
    const inCat = (c === shown);
    const isHidden = hiddenIds.has(Number(btn.dataset.productId));
    btn.classList.toggle("is-hidden", isHidden);
    if (!inCat) { btn.style.display = "none"; return; }
    // En modo Quitar se ven todos (los ocultos en gris con ＋); si no, se esconden.
    btn.style.display = (stationQuitar || !isHidden) ? "" : "none";
  });
  // El campo "Nombre de la orden" solo aparece en modo Uber.
  const wrap = document.getElementById("uberNameWrap");
  if (wrap) wrap.style.display = (stationCategory === "Uber") ? "" : "none";
}

function renderProducts() {
  const grid = document.getElementById("productsGrid");
  if (!grid) return;
  const list = currentProductOrder();
  if (stationReorder) {
    grid.classList.add("reorder-active");
    // Reordenar SOLO los productos de la pestaña activa (Uber reutiliza Desayuno).
    const shownCat = (stationCategory === "Uber") ? "Desayuno" : stationCategory;
    const rlist = list.filter(p => (p.category || "General") === shownCat);
    grid.innerHTML =
      `<div class="reorder-hint">Reordenando <strong>${shownCat}</strong>. Arrastra ⠿ (o usa ▲▼). El orden se guarda solo.</div>` +
      '<div class="reorder-list">' +
      (rlist.length ? rlist.map((p, i) => `
        <div class="reorder-item" data-id="${p.id}">
          <span class="reorder-handle">⠿</span>
          <span class="reorder-name">${p.name}</span>
          <span class="reorder-item-arrows">
            <button class="reorder-arrow" data-move="up" data-id="${p.id}" ${i === 0 ? "disabled" : ""}>▲</button>
            <button class="reorder-arrow" data-move="down" data-id="${p.id}" ${i === rlist.length - 1 ? "disabled" : ""}>▼</button>
          </span>
        </div>`).join("") : '<div class="recent-empty">No hay productos en esta categoría.</div>') +
      '</div>';
    setupDragSort();
  } else {
    grid.classList.remove("reorder-active");
    grid.innerHTML = list.map(p =>
      `<button class="product-btn" data-product-id="${p.id}" data-product-name="${p.name}" data-category="${p.category || 'General'}">${productImg(p)}<span>${p.name}</span></button>`
    ).join("");
    bindProductButtons();
    applyCategoryFilter();
  }
}

function getDragAfterElement(container, y) {
  const els = [...container.querySelectorAll(".reorder-item:not(.dragging)")];
  return els.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) return { offset, element: child };
    return closest;
  }, { offset: -Infinity }).element || null;
}

function setupDragSort() {
  const listEl = document.querySelector("#productsGrid .reorder-list");
  if (!listEl) return;
  let dragEl = null;

  listEl.querySelectorAll(".reorder-item").forEach(item => {
    item.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".reorder-arrow")) return;  // let arrows work
      dragEl = item;
      item.classList.add("dragging");
      try { item.setPointerCapture(e.pointerId); } catch (_) {}
    });
    item.addEventListener("pointermove", (e) => {
      if (!dragEl) return;
      e.preventDefault();
      const after = getDragAfterElement(listEl, e.clientY);
      if (after == null) listEl.appendChild(dragEl);
      else listEl.insertBefore(dragEl, after);
    });
    const end = async (e) => {
      if (!dragEl) return;
      dragEl.classList.remove("dragging");
      try { item.releasePointerCapture(e.pointerId); } catch (_) {}
      dragEl = null;
      await commitReorder(listEl);
    };
    item.addEventListener("pointerup", end);
    item.addEventListener("pointercancel", () => {
      if (dragEl) { dragEl.classList.remove("dragging"); dragEl = null; }
    });
  });
}

async function commitReorder(listEl) {
  const ids = [...listEl.querySelectorAll(".reorder-item")].map(el => Number(el.dataset.id));
  try {
    const res = await fetch("/api/products/reorder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids })
    });
    if (!res.ok) throw new Error();
    // Reordena en su lugar solo los productos de la categoría (los ids enviados),
    // dejando el resto donde estaba.
    const idSet = new Set(ids);
    const reordered = ids.map(id => stationProducts.find(p => p.id === id)).filter(Boolean);
    let ri = 0;
    stationProducts = stationProducts.map(p => idSet.has(p.id) ? reordered[ri++] : p);
  } catch (e) {
    toast("No se pudo guardar el orden.", "error");
    await refreshProductsGrid();
  }
}

async function refreshProductsGrid() {
  try {
    const res = await fetch("/api/products");
    stationProducts = await res.json();
  } catch (e) { return; }
  renderProducts();
}

async function moveProduct(id, dir) {
  try {
    const res = await fetch(`/api/products/${id}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction: dir })
    });
    if (!res.ok) throw new Error();
    await refreshProductsGrid();
  } catch (e) { toast("No se pudo reordenar.", "error"); }
}

document.querySelectorAll(".sort-btn").forEach(b => {
  b.addEventListener("click", () => {
    if (stationReorder) return;
    stationSort = b.dataset.sort;
    document.querySelectorAll(".sort-btn").forEach(x => x.classList.toggle("active", x === b));
    renderProducts();
  });
});

// Pestañas de categoría (General / Desayuno / …)
document.querySelectorAll(".cat-tab").forEach(t => {
  t.addEventListener("click", () => {
    if (stationReorder) return;
    stationCategory = t.dataset.cat;
    document.querySelectorAll(".cat-tab").forEach(x => x.classList.toggle("active", x === t));
    applyCategoryFilter();
  });
});
// Filtro inicial sobre los botones renderizados por el servidor
applyCategoryFilter();

// Resalta el selector cuando hay una mesa elegida
const _tableSel = document.getElementById("tableSelect");
const _tablePick = document.getElementById("tablePick");
if (_tableSel && _tablePick) {
  _tableSel.addEventListener("change", () => {
    _tablePick.classList.toggle("mesa-set", !!_tableSel.value);
  });
  // Preselección desde el plano (/mesas → ?mesa=id)
  const _mesaParam = new URLSearchParams(location.search).get("mesa");
  if (_mesaParam && _tableSel.querySelector(`option[value="${_mesaParam}"]`)) {
    _tableSel.value = _mesaParam;
    _tablePick.classList.add("mesa-set");
    _tableSel.scrollIntoView({ block: "nearest" });
  }
}

const _reorderBtn = document.getElementById("reorderBtn");
if (_reorderBtn) {
  _reorderBtn.addEventListener("click", () => {
    stationReorder = !stationReorder;
    _reorderBtn.classList.toggle("on", stationReorder);
    _reorderBtn.textContent = stationReorder ? T("salon.listo_orden", "✓ Listo") : T("salon.ordenar", "↕ Ordenar");
    if (stationReorder) {
      stationSort = "manual";
      document.querySelectorAll(".sort-btn").forEach(x => x.classList.toggle("active", x.dataset.sort === "manual"));
      // salir del modo Quitar si estaba activo
      stationQuitar = false;
      const qb = document.getElementById("quitarBtn");
      if (qb) { qb.classList.remove("on"); qb.textContent = T("salon.quitar", "✕ Quitar"); }
      document.getElementById("productsGrid").classList.remove("quitar-on");
    }
    document.querySelectorAll(".sort-btn").forEach(x => { x.disabled = stationReorder; });
    renderProducts();
  });
}

// Modo "Quitar": ocultar/mostrar productos del panel (guardado en el dispositivo)
const _quitarBtn = document.getElementById("quitarBtn");
if (_quitarBtn) {
  _quitarBtn.addEventListener("click", () => {
    if (stationReorder) {   // salir de Ordenar primero
      stationReorder = false;
      if (_reorderBtn) { _reorderBtn.classList.remove("on"); _reorderBtn.textContent = T("salon.ordenar", "↕ Ordenar"); }
      document.querySelectorAll(".sort-btn").forEach(x => { x.disabled = false; });
      renderProducts();
    }
    stationQuitar = !stationQuitar;
    _quitarBtn.classList.toggle("on", stationQuitar);
    _quitarBtn.textContent = stationQuitar ? T("salon.listo_orden", "✓ Listo") : T("salon.quitar", "✕ Quitar");
    document.getElementById("productsGrid").classList.toggle("quitar-on", stationQuitar);
    applyCategoryFilter();
  });
}

const _productsGridEl = document.getElementById("productsGrid");
if (_productsGridEl) {
  _productsGridEl.addEventListener("click", async (e) => {
    const arrow = e.target.closest("[data-move]");
    if (!arrow) return;
    e.stopPropagation();
    const item = arrow.closest(".reorder-item");
    const listEl = document.querySelector("#productsGrid .reorder-list");
    if (!item || !listEl) return;
    // Mueve dentro de la lista visible (ya filtrada por categoría) y guarda.
    if (arrow.dataset.move === "up" && item.previousElementSibling) {
      listEl.insertBefore(item, item.previousElementSibling);
    } else if (arrow.dataset.move === "down" && item.nextElementSibling) {
      listEl.insertBefore(item.nextElementSibling, item);
    } else {
      return;
    }
    await commitReorder(listEl);
    renderProducts();   // refresca los estados ▲▼ (primero/último) en el nuevo orden
  });
}

refreshProductsGrid();

const newProductModal = document.getElementById("newProductModal");
const newProductInput = document.getElementById("newProductName");
function openNewProductModal() {
  newProductInput.value = "";
  newProductModal.style.display = "flex";
  setTimeout(() => newProductInput.focus(), 50);
}
function closeNewProductModal() { newProductModal.style.display = "none"; }
async function saveNewProduct() {
  const name = newProductInput.value.trim();
  if (!name) return toast(T("msg.escribe_nombre", "Escribe un nombre."), "error");
  // El producto nuevo toma la pestaña activa (Uber reutiliza los de Desayuno).
  const cat = (stationCategory === "Uber") ? "Desayuno" : stationCategory;
  // ¿Existe (activo) pero oculto en esta tablet? Ofrecer mostrarlo en vez de crear.
  const hiddenMatch = stationProducts.find(p => (p.name || "").trim().toLowerCase() === name.toLowerCase() && hiddenIds.has(Number(p.id)));
  if (hiddenMatch) {
    const ok = await window.askConfirm("Ese producto existe pero está oculto en esta tablet. ¿Mostrarlo?", { yes: "Mostrar" });
    if (ok) { hiddenIds.delete(Number(hiddenMatch.id)); saveHidden(); applyCategoryFilter(); closeNewProductModal(); toast("Producto mostrado."); }
    return;
  }
  const res = await fetch("/api/products", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, category: cat })
  });
  if (res.ok) { closeNewProductModal(); await refreshProductsGrid(); return; }
  const err = await res.json().catch(() => ({}));
  // Existe pero desactivado -> ofrecer reactivarlo.
  if (res.status === 409 && err.inactive && err.product_id) {
    const ok = await window.askConfirm("Ese producto existe pero está desactivado. ¿Reactivarlo?", { yes: "Reactivar" });
    if (ok) {
      const r2 = await fetch(`/api/products/${err.product_id}/activate`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ category: cat })
      });
      if (r2.ok) {
        hiddenIds.delete(Number(err.product_id)); saveHidden();
        closeNewProductModal(); await refreshProductsGrid(); toast("Producto reactivado.");
      } else { toast("No se pudo reactivar.", "error"); }
    }
    return;
  }
  toast(err.detail || "No se pudo crear.", "error");
}
document.getElementById("newProductBtn").addEventListener("click", openNewProductModal);
document.getElementById("newProductCancelBtn").addEventListener("click", closeNewProductModal);
document.getElementById("newProductSaveBtn").addEventListener("click", saveNewProduct);
newProductInput.addEventListener("keydown", (e) => { if (e.key === "Enter") saveNewProduct(); });
document.getElementById("sendBtn").addEventListener("click", submitOrder);
document.getElementById("clearBtn").addEventListener("click", () => { lines = []; addStack = []; renderSummary(); });
document.getElementById("undoBtn").addEventListener("click", () => {
  const line = addStack.pop();
  if (!line) return;
  line.quantity -= 1;
  if (line.quantity <= 0) {
    const idx = lines.indexOf(line);
    if (idx !== -1) lines.splice(idx, 1);
  }
  renderSummary();
});
renderSummary();

/* ─── Internal kitchen orders panel ─────────────────────────────────── */

let stationKnownIds = new Set();

async function changeKitchenOrderStatus(orderId, status) {
  await fetch(`/api/orders/${orderId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_role: "station_a", status })
  });
  pollKitchenInternal();
}

function renderKitchenInternal(orders) {
  const container = document.getElementById("kitchenInternalOrders");
  if (!container) return;
  if (!orders.length) {
    container.innerHTML = '<div style="text-align:center;padding:30px;font-size:24px;color:#6c757d;">No hay pedidos de salón.</div>';
    return;
  }
  container.innerHTML = orders.map(order => {
    const status = order.status;
    const itemsHtml = order.items.map(i =>
      `<div style="display:flex;justify-content:space-between;background:#10141b;border-radius:12px;padding:12px 18px;font-size:24px;font-weight:700;"><span>${i.product_name}</span><span style="color:var(--accent);">x${i.quantity}</span></div>`
    ).join("");
    let buttonsHtml = "";
    if (status === "nuevo" || status === "aceptado" || status === "preparando") {
      buttonsHtml = `<button class="action" data-k-action="listo" data-k-id="${order.id}" style="background:rgba(76,175,80,0.2);color:var(--green);min-height:60px;font-size:22px;">LISTO</button>`;
    } else if (status === "listo") {
      buttonsHtml = `<button class="action primary" data-k-action="despachar" data-k-id="${order.id}" style="min-height:60px;font-size:22px;">DESPACHAR</button>`;
    }
    buttonsHtml += `<button class="action" data-k-action="cancel" data-k-id="${order.id}" style="background:rgba(228,91,91,0.2);color:var(--red);min-height:60px;font-size:22px;">CANCELAR</button>`;
    return `
      <div style="background:var(--card);border:2px solid var(--blue);border-radius:20px;padding:22px;display:flex;flex-direction:column;gap:14px;">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
          <div style="font-size:28px;font-weight:800;">#${order.id} <span style="color:#b7becd;font-size:22px;text-transform:uppercase;margin-left:10px;">${status}</span></div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;">${itemsHtml}</div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;">${buttonsHtml}</div>
      </div>
    `;
  }).join("");

  container.querySelectorAll("[data-k-action]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.kId;
      const action = btn.dataset.kAction;
      if (action === "listo") changeKitchenOrderStatus(id, "listo");
      else if (action === "despachar") changeKitchenOrderStatus(id, "despachado");
      else if (action === "cancel") changeKitchenOrderStatus(id, "cancelado");
    });
  });
}

/* ─── Safari / iPad autoplay guard ─────────────────────────────────── */

if (typeof window.userInteracted === "undefined") window.userInteracted = false;

const AUDIO = window.STATION_AUDIO || {};
const activeAudioPlayers = new Set();

function normalizeAudioSrc(src) {
  if (!src) return src;
  try { return encodeURI(src); } catch (e) { return src; }
}

// Shared AudioContext — created once on first gesture. iOS limits how many
// contexts a page may create, so we must NOT make a new one per beep.
let _audioCtx = null;
function _getAudioCtx() {
  if (!_audioCtx) {
    try { _audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    catch (e) { return null; }
  }
  if (_audioCtx.state === "suspended") { _audioCtx.resume().catch(() => {}); }
  return _audioCtx;
}

// Decoded MP3s cached as AudioBuffers. On iPad this is the only reliable path:
// the <audio> element is silenced by the hardware mute switch and needs a
// per-element gesture unlock; the AudioContext plays through silent mode
// after one tap.
const _soundBuffers = {};
const _soundLoading = {};

function _loadBuffer(src) {
  if (_soundBuffers[src]) return Promise.resolve(_soundBuffers[src]);
  if (_soundLoading[src]) return _soundLoading[src];
  const ctx = _getAudioCtx();
  if (!ctx || typeof ctx.decodeAudioData !== "function") return Promise.reject(new Error("no webaudio"));
  const p = fetch(normalizeAudioSrc(src), { credentials: "same-origin" })
    .then((r) => { if (!r.ok) throw new Error("http " + r.status); return r.arrayBuffer(); })
    .then((buf) => new Promise((res, rej) => {
      const ret = ctx.decodeAudioData(buf, res, rej);
      if (ret && typeof ret.then === "function") ret.then(res, rej);
    }))
    .then((decoded) => { _soundBuffers[src] = decoded; delete _soundLoading[src]; return decoded; })
    .catch((err) => { delete _soundLoading[src]; throw err; });
  _soundLoading[src] = p;
  return p;
}

function _playBuffer(buffer) {
  const ctx = _getAudioCtx();
  if (!ctx) return false;
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  const gain = ctx.createGain();
  gain.gain.value = AUDIO.volume ?? 1;
  source.connect(gain);
  gain.connect(ctx.destination);
  try { source.start(0); } catch (e) { return false; }
  return true;
}

function _playViaWebAudio(src) {
  const ctx = _getAudioCtx();
  if (!ctx || typeof ctx.decodeAudioData !== "function") return false;
  if (_soundBuffers[src]) return _playBuffer(_soundBuffers[src]);
  _loadBuffer(src)
    .then((buf) => _playBuffer(buf))
    .catch((err) => { console.warn("[KDS] WebAudio failed, using <audio>:", src, err); _playSoundFileElement(src); });
  return true;
}

function _prewarmSounds() {
  Object.keys(AUDIO).forEach((k) => {
    const v = AUDIO[k];
    if (typeof v === "string" && /\.(mp3|wav|ogg|m4a|aac)$/i.test(v)) _loadBuffer(v).catch(() => {});
  });
}

let _audioPrewarmed = false;

// Canonical iOS unlock: resume the context AND play a 1-frame silent buffer
// inside the gesture. Without it, later source.start() stays muted on iPad.
// A permanent silent node keeps the context "running" so iOS doesn't suspend
// it — that's what lets order alerts play WITHOUT a fresh user gesture.
let _keepAliveNode = null;
function _startKeepAlive() {
  const ctx = _getAudioCtx();
  if (!ctx || _keepAliveNode) return;
  try {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    gain.gain.value = 0;             // inaudible
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    _keepAliveNode = osc;            // hold a reference so it isn't GC'd
  } catch (e) {}
}

function _unlockAudio() {
  const ctx = _getAudioCtx();
  if (!ctx) return;
  try {
    const buf = ctx.createBuffer(1, 1, 22050);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.start(0);
  } catch (e) {}
  _startKeepAlive();
}
window.unlockAudio = _unlockAudio;

function _initAudioOnGesture() {
  window.userInteracted = true;
  _unlockAudio();
  if (!_audioPrewarmed) { _audioPrewarmed = true; try { _prewarmSounds(); } catch (e) {} }
}
// NOT { once } — re-unlock on every tap so audio recovers after the iPad
// sleeps/locks (iOS suspends the AudioContext when backgrounded).
document.addEventListener("click",      _initAudioOnGesture, { capture: true });
document.addEventListener("touchstart", _initAudioOnGesture, { capture: true });
document.addEventListener("keydown",    _initAudioOnGesture, { capture: true });
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && _audioCtx && _audioCtx.state === "suspended") {
    _audioCtx.resume().catch(() => {});
  }
});

/* ─── Audio helpers ─────────────────────────────────────────────────── */

function playSoundFile(src) {
  if (!window.userInteracted) return false;
  if (!src) return false;
  // Prefer Web Audio (works on iPad even in silent mode); fall back to <audio>.
  if (_playViaWebAudio(src)) return true;
  return _playSoundFileElement(src);
}

function _playSoundFileElement(src) {
  if (!src) return false;
  try {
    const audio = new Audio(normalizeAudioSrc(src));
    audio.preload = "auto";
    audio.volume = AUDIO.volume ?? 1;
    activeAudioPlayers.add(audio);
    const cleanup = () => activeAudioPlayers.delete(audio);
    audio.addEventListener("ended", cleanup, { once: true });
    audio.addEventListener("error", () => {
      cleanup();
      beep(880, 400);
      console.warn("[KDS] Audio file failed to load:", src);
    }, { once: true });
    const playPromise = audio.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch((err) => {
        cleanup();
        beep(880, 400);
        console.warn("[KDS] Audio playback failed:", src, err);
      });
    }
    return true;
  } catch (e) { return false; }
}

function beep(freq, durMs) {
  if (!window.userInteracted) return;
  try {
    const ctx = _getAudioCtx();
    if (!ctx) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine"; osc.frequency.value = freq;
    const vol = (AUDIO.volume ?? 1) * 0.5;
    gain.gain.setValueAtTime(vol, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + durMs / 1000);
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + durMs / 1000);
  } catch (e) {}
}

/* ─── TTS voice loader ──────────────────────────────────────────────── */

let _stationVoice = null;
function _loadStationVoice() {
  const voices = speechSynthesis.getVoices();
  if (!voices.length) return;
  _stationVoice = voices.find(v => v.lang === "es-ES")
    || voices.find(v => v.lang.startsWith("es"))
    || null;
}
_loadStationVoice();
speechSynthesis.onvoiceschanged = _loadStationVoice;

function speakSpanish(text) {
  if (!window.userInteracted) return;
  if (!AUDIO.voiceEnabled) return;
  let spoken = false;
  try {
    const utterance = new SpeechSynthesisUtterance(text);
    if (_stationVoice) utterance.voice = _stationVoice;
    utterance.lang = "es-ES";
    utterance.volume = 1;
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.onstart = () => { spoken = true; };
    speechSynthesis.cancel();
    setTimeout(() => { speechSynthesis.speak(utterance); }, 100);
  } catch (e) {}
}

function formatItemsSpeech(items) {
  return items.map(i => `${i.quantity} ${i.product_name || i.name}`).join(", ");
}

/* ─── Polling ───────────────────────────────────────────────────────── */

let myReadyIds = new Set();
let firstPoll = true;

let _kitchenPolling = false;
async function pollKitchenInternal() {
  if (_kitchenPolling) return;   // evita sondeos solapados (doble alerta)
  _kitchenPolling = true;
  try {
    const res = await fetch("/api/orders/active");
    const all = await res.json();

    const kitchenOrders = all.filter(o => o.source_role === "kitchen");
    const newKitchenIds = kitchenOrders.filter(o => !stationKnownIds.has(o.id));
    if (newKitchenIds.length > 0 && !firstPoll) {
      if (!playSoundFile(AUDIO.stationSound)) beep(880, 400);
      newKitchenIds.forEach(o => speakSpanish(`Nuevo pedido de cocina. ${formatItemsSpeech(o.items)}.`));
    }
    stationKnownIds = new Set(kitchenOrders.map(o => o.id));

    firstPoll = false;
    renderKitchenInternal(kitchenOrders);
    fetchRecent();
    pollReadyRecent();
  } catch (e) {}
  finally { _kitchenPolling = false; }
}

/* ─── Aviso "Pedido listo" (cuando cocina despacha una orden de salón) ──
   Cocina despacha de un toque → la orden sale de "activos"; por eso lo
   detectamos con un feed de despachadas recientes, no en la lista activa. */
let readyAlerted = new Set();
let firstReadyPoll = true;
let _readyPolling = false;
async function pollReadyRecent() {
  if (_readyPolling) return;   // evita sondeos solapados (doble alerta)
  _readyPolling = true;
  try {
    const res = await fetch("/api/orders/ready-recent?minutes=5");
    const list = await res.json();
    list.forEach(o => {
      if (readyAlerted.has(o.id)) return;
      readyAlerted.add(o.id);
      if (firstReadyPoll) return;   // no avisar por las ya despachadas al cargar
      if (!playSoundFile(AUDIO.stationSound)) beep(1320, 500);
      speakSpanish(`Pedido listo. ${formatItemsSpeech(o.items)}.`);
    });
    firstReadyPoll = false;
  } catch (e) {}
  finally { _readyPolling = false; }
}

/* ─── Órdenes recientes (las que envió este agente) ─────────────────── */
let recentOrders = [];
let recentExpanded = false;
const RECENT_COLLAPSED = 6;

async function fetchRecent() {
  try {
    const wid = window.KDS_CONFIG.waiterId;
    const res = await fetch(`/api/orders/recent?source_role=station_a&waiter_id=${wid}&limit=20`);
    recentOrders = await res.json();
    renderRecent();
  } catch (e) {}
}

function recentBadge(s) {
  const label = s.charAt(0).toUpperCase() + s.slice(1);
  return `<span class="recent-badge rb-${s}">${label}</span>`;
}

const CANCELABLE = new Set(["nuevo", "aceptado", "preparando", "listo"]);

function renderRecent() {
  const list = document.getElementById("recentList");
  const toggle = document.getElementById("recentToggle");
  const cancelLastBtn = document.getElementById("cancelLastBtn");
  if (!list || !toggle) return;
  if (cancelLastBtn) cancelLastBtn.disabled = !recentOrders.some(o => CANCELABLE.has(o.status));
  if (!recentOrders.length) {
    list.innerHTML = '<div class="recent-empty">Aún no has enviado órdenes.</div>';
    toggle.style.display = "none";
    return;
  }
  const shown = recentExpanded ? recentOrders : recentOrders.slice(0, RECENT_COLLAPSED);
  list.innerHTML = shown.map(o => {
    const time = (o.created_at || "").slice(11, 16);
    const items = o.items.map(i => `${i.quantity} ${i.product_name}`).join(", ");
    const cancelBtn = CANCELABLE.has(o.status)
      ? `<button class="recent-row-cancel" data-cancel-id="${o.id}">Cancelar</button>` : "";
    const uberTag = o.order_label
      ? `<div class="recent-uber">🛵 UBER · ${String(o.order_label).replace(/[<>]/g, "")}</div>`
      : "";
    return `
      <div class="recent-row">
        <div class="recent-row-top">
          <span class="recent-id">#${o.id} <span class="recent-time">${time}</span></span>
          ${recentBadge(o.status)}
        </div>
        ${uberTag}
        <div class="recent-items">${items}</div>
        ${cancelBtn}
      </div>`;
  }).join("");
  if (recentOrders.length > RECENT_COLLAPSED) {
    toggle.style.display = "block";
    toggle.textContent = recentExpanded ? T("salon.ver_menos", "Ver menos") : `${T("salon.ver_mas", "Ver más")} (${recentOrders.length - RECENT_COLLAPSED})`;
  } else {
    toggle.style.display = "none";
  }
}

async function cancelOrder(id) {
  if (!(await window.askConfirm(`¿Cancelar la orden #${id}?`, { yes: "Sí, cancelar" }))) return;
  try {
    const res = await fetch(`/api/orders/${id}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "cancelado", actor_role: window.KDS_CONFIG.sourceRole })
    });
    if (!res.ok) throw new Error();
    toast(`Orden #${id} cancelada.`);
    fetchRecent();
  } catch (e) { toast("No se pudo cancelar.", "error"); }
}

function cancelLast() {
  const last = recentOrders.find(o => CANCELABLE.has(o.status));
  if (!last) { toast("No hay órdenes por cancelar.", "error"); return; }
  cancelOrder(last.id);
}

const _recentToggleBtn = document.getElementById("recentToggle");
if (_recentToggleBtn) {
  _recentToggleBtn.addEventListener("click", () => {
    recentExpanded = !recentExpanded;
    renderRecent();
  });
}
const _cancelLastBtn = document.getElementById("cancelLastBtn");
if (_cancelLastBtn) _cancelLastBtn.addEventListener("click", cancelLast);
const _recentListEl = document.getElementById("recentList");
if (_recentListEl) {
  _recentListEl.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cancel-id]");
    if (btn) cancelOrder(btn.dataset.cancelId);
  });
}

pollKitchenInternal();
setInterval(pollKitchenInternal, 4000);
fetchRecent();

/* ─── WebSocket en vivo (aditivo — el polling queda como respaldo) ──────
   Da avisos INSTANTÁNEOS en el Salón: pedido de cocina entrante y pedido
   listo, sin esperar el sondeo cada 4s. El dedup (stationKnownIds/readyAlerted)
   evita doble alerta cuando WS y polling ven el mismo pedido. */
(function initStationWS() {
  let ws = null;
  let retryTimer = null;
  const RETRY_MS = 2000;

  function connect() {
    try {
      const protocol = location.protocol === "https:" ? "wss://" : "ws://";
      ws = new WebSocket(protocol + location.host + "/ws/kitchen");

      ws.onopen = () => {
        console.info("[KDS] Station WebSocket connected");
        if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
      };

      ws.onmessage = (event) => {
        let msg;
        try { msg = JSON.parse(event.data); } catch { return; }
        const order = msg.order;
        if (!order) return;

        // Pedido de cocina entrante → aviso del Salón
        if (msg.event === "new_order" && order.source_role === "kitchen") {
          if (stationKnownIds.has(order.id)) return;
          stationKnownIds.add(order.id);
          if (!playSoundFile(AUDIO.stationSound)) beep(880, 400);
          speakSpanish(`Nuevo pedido de cocina. ${formatItemsSpeech(order.items)}.`);
          pollKitchenInternal();   // refresca la lista (con candado; inocuo si está ocupado)
          return;
        }

        // Pedido de salón marcado listo/despachado → aviso instantáneo
        if (msg.event === "order_ready") {
          if (readyAlerted.has(order.id)) return;
          readyAlerted.add(order.id);
          if (!playSoundFile(AUDIO.stationSound)) beep(1320, 500);
          speakSpanish(`Pedido listo. ${formatItemsSpeech(order.items)}.`);
          fetchRecent();
          return;
        }
      };

      ws.onerror = () => { /* onclose se encarga de reconectar */ };
      ws.onclose = () => {
        ws = null;
        retryTimer = setTimeout(connect, RETRY_MS);
      };
    } catch (e) {
      console.warn("[KDS] Station WebSocket init failed:", e);
      retryTimer = setTimeout(connect, RETRY_MS);
    }
  }

  connect();
})();

/* ─── On-screen audio diagnostic ────────────────────────────────────── */
function _injectAudioTest() {
  if (document.getElementById("audioTestBtn")) return;
  const btn = document.createElement("button");
  btn.id = "audioTestBtn";
  btn.textContent = "🔊 Probar audio";
  btn.style.cssText = "position:fixed;bottom:16px;right:16px;z-index:99999;padding:14px 20px;font-size:18px;font-weight:800;border:none;border-radius:14px;background:#ffd24d;color:#111;box-shadow:0 6px 20px rgba(0,0,0,.4);cursor:pointer;";
  const status = document.createElement("div");
  status.id = "audioTestStatus";
  status.style.cssText = "position:fixed;bottom:74px;right:16px;z-index:99999;max-width:340px;padding:12px 14px;font-size:13px;line-height:1.45;border-radius:12px;background:rgba(0,0,0,.88);color:#fff;white-space:pre-wrap;display:none;";
  btn.addEventListener("click", async () => {
    status.style.display = "block";
    window.userInteracted = true;
    _unlockAudio();
    const ctx = _getAudioCtx();
    let out = "AudioContext: " + (ctx ? ctx.state : "NO DISPONIBLE") + "\n";
    out += "sampleRate: " + (ctx ? ctx.sampleRate : "-") + "\n";
    try { beep(880, 300); out += "Beep: enviado — ¿lo oíste?\n"; }
    catch (e) { out += "Beep: ERROR " + (e && e.message) + "\n"; }
    const src = Object.keys(AUDIO).map((k) => AUDIO[k]).find((v) => typeof v === "string" && /\.(mp3|wav|ogg|m4a|aac)$/i.test(v));
    if (!src) { out += "MP3: NO hay sonido configurado (Admin › Audio)\n"; status.textContent = out; return; }
    out += "MP3 src: " + src + "\n";
    status.textContent = out + "MP3: cargando…";
    try {
      const buf = await _loadBuffer(src);
      const ok = _playBuffer(buf);
      out += "MP3: decodificado OK, reproducido=" + ok + " — ¿lo oíste?\n";
    } catch (e) {
      out += "MP3: FALLO -> " + (e && e.message ? e.message : e) + "\n";
      try { _playSoundFileElement(src); out += "Fallback <audio>: intentado\n"; } catch (e2) {}
    }
    status.textContent = out;
  });
  document.body.appendChild(btn);
  document.body.appendChild(status);
}
if (document.readyState !== "loading") _injectAudioTest();
else document.addEventListener("DOMContentLoaded", _injectAudioTest);
