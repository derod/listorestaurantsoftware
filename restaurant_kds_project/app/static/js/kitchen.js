const kitchenMap = new Map();
const kitchenSequence = [];
let knownOrderIds = new Set((window.INITIAL_ORDERS || []).map(o => o.id));

/* ─── Timer ─────────────────────────────────────────────────────────── */

function elapsedLabel(sinceIso) {
  if (!sinceIso) return { text: "--:--", seconds: 0 };
  const diff = Math.max(0, Math.floor((Date.now() - new Date(sinceIso).getTime()) / 1000));
  const min = String(Math.floor(diff / 60)).padStart(2, "0");
  const sec = String(diff % 60).padStart(2, "0");
  return { text: `${min}:${sec}`, seconds: diff };
}

/* ─── Internal order form ───────────────────────────────────────────── */

function renderKitchenSummary() {
  const el = document.getElementById("kitchenOrderSummary");
  const entries = [...kitchenMap.values()];
  if (!entries.length) {
    el.innerHTML = "No hay productos.";
    el.classList.add("empty-state");
    return;
  }
  el.classList.remove("empty-state");
  el.innerHTML = entries.map(item =>
    `<div class="summary-item"><span>${item.name}</span><strong>${item.quantity}</strong></div>`
  ).join("");
}

function addKitchenProduct(id, name) {
  const key = String(id);
  if (!kitchenMap.has(key)) kitchenMap.set(key, { product_id: id, name, quantity: 0 });
  kitchenMap.get(key).quantity += 1;
  kitchenSequence.push(key);
  renderKitchenSummary();
}

async function submitKitchenOrder() {
  const items = [...kitchenMap.values()].filter(x => x.quantity > 0)
    .map(x => ({ product_id: x.product_id, quantity: x.quantity }));
  if (!items.length) return alert("Agrega productos primero.");
  const res = await fetch("/api/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_role: "kitchen", items })
  });
  if (!res.ok) return alert("No se pudo enviar.");
  kitchenMap.clear();
  kitchenSequence.length = 0;
  renderKitchenSummary();
  document.getElementById("createModal").classList.remove("open");
  pollOrders();
}

/* ─── Safari autoplay guard ─────────────────────────────────────────── */

if (typeof window.userInteracted === "undefined") window.userInteracted = false;

// Shared AudioContext — created once on first gesture so Safari doesn't suspend it.
let _audioCtx = null;
function _getAudioCtx() {
  if (!_audioCtx) {
    _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  // Safari suspends the context when the page loses focus; resume before use.
  if (_audioCtx.state === "suspended") {
    _audioCtx.resume().catch(() => {});
  }
  return _audioCtx;
}

function _initAudioCtxOnGesture() {
  window.userInteracted = true;
  // Warm up the context inside the gesture so Safari unlocks it permanently.
  try { _getAudioCtx(); } catch (e) {}
}
document.addEventListener("click",      _initAudioCtxOnGesture, { once: true, capture: true });
document.addEventListener("touchstart", _initAudioCtxOnGesture, { once: true, capture: true });
document.addEventListener("keydown",    _initAudioCtxOnGesture, { once: true, capture: true });

/* ─── Audio ─────────────────────────────────────────────────────────── */

/* ─── TTS voice loader ──────────────────────────────────────────────── */

let _kitchenVoice = null;
function _loadKitchenVoice() {
  const voices = speechSynthesis.getVoices();
  if (!voices.length) return;
  _kitchenVoice = voices.find(v => v.lang === "es-ES")
    || voices.find(v => v.lang.startsWith("es"))
    || null;
}
_loadKitchenVoice();
speechSynthesis.onvoiceschanged = _loadKitchenVoice;

function speakSpanish(text) {
  if (!window.userInteracted) return;
  if (!window.KITCHEN_AUDIO.voiceEnabled) return;
  let spoken = false;
  try {
    const utterance = new SpeechSynthesisUtterance(text);
    if (_kitchenVoice) utterance.voice = _kitchenVoice;
    utterance.lang = "es-ES";
    utterance.volume = 1;
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.onstart = () => { spoken = true; };
    utterance.onerror = () => { beep(660, 400); };
    speechSynthesis.cancel();
    setTimeout(() => { speechSynthesis.speak(utterance); }, 100);
    setTimeout(() => { if (!spoken) beep(660, 400); }, 600);
  } catch (e) { beep(660, 400); }
}

const activeAudioPlayers = new Set();

function normalizeAudioSrc(src) {
  if (!src) return src;
  try { return encodeURI(src); } catch (e) { return src; }
}

function playSound(src) {
  if (!window.userInteracted) return false;
  if (!src) return false;
  try {
    const audio = new Audio(normalizeAudioSrc(src));
    audio.preload = "auto";
    audio.volume = window.KITCHEN_AUDIO.volume ?? 1;
    activeAudioPlayers.add(audio);
    const cleanup = () => activeAudioPlayers.delete(audio);
    audio.addEventListener("ended", cleanup, { once: true });
    audio.addEventListener("error", () => {
      cleanup();
      beep(660, 400);
      console.warn("[KDS] Audio file failed to load:", src);
    }, { once: true });
    const playPromise = audio.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch((err) => {
        cleanup();
        beep(660, 400);
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
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine"; osc.frequency.value = freq;
    const vol = (window.KITCHEN_AUDIO.volume ?? 1) * 0.5;
    gain.gain.setValueAtTime(vol, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + durMs / 1000);
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + durMs / 1000);
  } catch (e) {}
}

function playAlertRing() {
  if (!window.userInteracted) return;
  try {
    const ctx = _getAudioCtx();
    const vol = window.KITCHEN_AUDIO.volume ?? 1;

    function ring(freq, start, dur) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(vol * 0.5, ctx.currentTime + start);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + dur);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + start);
      osc.stop(ctx.currentTime + start + dur);
    }

    ring(880, 0, 0.25);
    ring(1100, 0.3, 0.25);
    ring(880, 0.6, 0.25);
  } catch (e) {}
}

function formatSpeech(items) {
  return items.map(item => `${item.quantity} ${item.product_name || item.name}`).join(", ");
}

/* ─── Status change helper ──────────────────────────────────────────── */

async function changeStatus(orderId, status) {
  await fetch(`/api/orders/${orderId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_role: "kitchen", status })
  });
  pollOrders();
}

/* When kitchen accepts a station_a order, go aceptado then preparando */
async function acceptAndPrepare(orderId) {
  await fetch(`/api/orders/${orderId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_role: "kitchen", status: "aceptado" })
  });
  await fetch(`/api/orders/${orderId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_role: "kitchen", status: "preparando" })
  });
  pollOrders();
}

/* ─── Render orders ─────────────────────────────────────────────────── */

function renderOrders(orders) {
  const container = document.getElementById("ordersContainer");

  if (!orders.length) {
    container.innerHTML = '<div class="empty-kitchen">No hay pedidos activos</div>';
    return;
  }

  container.innerHTML = "";

  orders.forEach(order => {
    const isStation = order.source_role === "station_a";
    const accentClass = isStation ? "accent-station" : "accent-kitchen";
    const badgeColor = isStation ? "badge-station" : "badge-kitchen";
    const badgeLabel = isStation ? "SALON" : "KITCHEN";
    const status = order.status;

    /* Timer: only runs when preparando, from preparing_at */
    let timerHtml = "";
    if (status === "preparando" && order.preparing_at) {
      const { text, seconds } = elapsedLabel(order.preparing_at);
      const cls = seconds > 600 ? "timer-big danger" : seconds > 300 ? "timer-big warn" : "timer-big";
      timerHtml = `<div class="${cls}">${text}</div>`;
    } else if (status === "listo") {
      timerHtml = `<div class="timer-big" style="color:var(--green);">LISTO</div>`;
    } else if (status === "nuevo" || status === "aceptado") {
      timerHtml = `<div class="timer-big" style="color:var(--yellow);">NUEVO</div>`;
    }

    /* Status label */
    const statusLabel = status.toUpperCase();

    /* Waiter */
    const waiterHtml = order.waiter_name
      ? `<div class="order-waiter-big">Agente: <strong>${order.waiter_name}</strong></div>`
      : "";

    /* Buttons depend on status */
    let buttonsHtml = "";
    if (status === "nuevo" || status === "aceptado") {
      buttonsHtml = `
        <button class="btn-aceptado" data-action="accept" data-order-id="${order.id}">ACEPTAR</button>
        <button class="btn-cancelado" data-action="cancel" data-order-id="${order.id}">CANCELAR</button>
      `;
    } else if (status === "preparando") {
      buttonsHtml = `
        <button class="btn-listo" data-action="listo" data-order-id="${order.id}">LISTO</button>
        <button class="btn-cancelado" data-action="cancel" data-order-id="${order.id}">CANCELAR</button>
      `;
    } else if (status === "listo") {
      buttonsHtml = `
        <button class="btn-despachado" data-action="despachar" data-order-id="${order.id}">DESPACHAR</button>
        <button class="btn-cancelado" data-action="cancel" data-order-id="${order.id}">CANCELAR</button>
      `;
    }

    const card = document.createElement("div");
    card.className = `order-card-big ${accentClass}`;
    card.innerHTML = `
      <div class="order-header">
        <div class="order-header-left">
          <div class="order-id-big">#${order.id}</div>
          <div class="order-badge-big ${badgeColor}">${badgeLabel}</div>
          <div class="order-status-big">${statusLabel}</div>
          ${waiterHtml}
        </div>
        ${timerHtml}
      </div>
      <div class="order-items-big">
        ${order.items.map(item =>
          `<div class="order-line-big"><span>${item.product_name}</span><span class="qty">x${item.quantity}</span></div>`
        ).join("")}
      </div>
      <div class="order-actions-big">
        ${buttonsHtml}
      </div>
    `;

    container.appendChild(card);
  });

  /* Bind action buttons */
  document.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.orderId;
      const action = btn.dataset.action;
      if (action === "accept") acceptAndPrepare(id);
      else if (action === "listo") changeStatus(id, "listo");
      else if (action === "despachar") changeStatus(id, "despachado");
      else if (action === "cancel") changeStatus(id, "cancelado");
    });
  });
}

/* ─── Polling ───────────────────────────────────────────────────────── */

async function pollOrders() {
  const res = await fetch("/api/orders/active");
  const all = await res.json();
  const orders = all.filter(o => o.source_role !== "kitchen");
  const newOrders = orders.filter(o => !knownOrderIds.has(o.id));
  newOrders.forEach(order => {
    knownOrderIds.add(order.id);
    if (order.source_role === "station_a") {
      if (!playSound(window.KITCHEN_AUDIO.stationSound)) beep(880, 400);
      speakSpanish(`Nuevo pedido. ${formatSpeech(order.items)}.`);
    } else {
      if (!playSound(window.KITCHEN_AUDIO.kitchenSound)) beep(660, 400);
    }
  });
  window.INITIAL_ORDERS = orders;
  renderOrders(orders);
}

/* ─── Event listeners ───────────────────────────────────────────────── */

function bindKitchenProductButtons() {
  document.querySelectorAll("#kitchenProductsGrid .product-btn").forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => addKitchenProduct(btn.dataset.productId, btn.dataset.productName));
  });
}
bindKitchenProductButtons();

async function refreshKitchenProductsGrid() {
  const res = await fetch("/api/products");
  const products = await res.json();
  const grid = document.getElementById("kitchenProductsGrid");
  grid.innerHTML = products.map(p => {
    const img = p.image_path ? `<img src="${p.image_path}" alt="" style="width:100%;height:110px;object-fit:cover;border-radius:12px;margin-bottom:8px;">` : "";
    return `<button class="product-btn" data-product-id="${p.id}" data-product-name="${p.name}">${img}<span>${p.name}</span></button>`;
  }).join("");
  bindKitchenProductButtons();
}

const kNewModal = document.getElementById("kitchenNewProductModal");
const kNewInput = document.getElementById("kitchenNewProductName");
function openKitchenNewProductModal() {
  kNewInput.value = "";
  kNewModal.classList.add("open");
  setTimeout(() => kNewInput.focus(), 50);
}
function closeKitchenNewProductModal() { kNewModal.classList.remove("open"); }
async function saveKitchenNewProduct() {
  const name = kNewInput.value.trim();
  if (!name) return alert("Escribe un nombre.");
  const res = await fetch("/api/products", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    return alert(err.detail || "No se pudo crear.");
  }
  closeKitchenNewProductModal();
  await refreshKitchenProductsGrid();
}
document.getElementById("kitchenNewProductBtn").addEventListener("click", openKitchenNewProductModal);
document.getElementById("kitchenNewProductCancelBtn").addEventListener("click", closeKitchenNewProductModal);
document.getElementById("kitchenNewProductSaveBtn").addEventListener("click", saveKitchenNewProduct);
kNewInput.addEventListener("keydown", (e) => { if (e.key === "Enter") saveKitchenNewProduct(); });
document.getElementById("kitchenSendBtn").addEventListener("click", submitKitchenOrder);
document.getElementById("kitchenClearBtn").addEventListener("click", () => {
  kitchenMap.clear();
  kitchenSequence.length = 0;
  renderKitchenSummary();
});
// Modal open/close
document.getElementById("openCreateBtn").addEventListener("click", () => {
  document.getElementById("createModal").classList.add("open");
});
document.getElementById("closeCreateBtn").addEventListener("click", () => {
  document.getElementById("createModal").classList.remove("open");
});

function visibleOrders() {
  return (window.INITIAL_ORDERS || []).filter(o => o.source_role !== "kitchen");
}

renderKitchenSummary();
renderOrders(visibleOrders());
setInterval(pollOrders, 4000);
setInterval(() => renderOrders(visibleOrders()), 1000);

/* ─── WebSocket real-time layer (additive — polling remains as fallback) ── */

(function initKitchenWS() {
  let ws = null;
  let retryTimer = null;
  const RETRY_MS = 2000;

  function connect() {
    try {
      const protocol = location.protocol === "https:" ? "wss://" : "ws://";
      ws = new WebSocket(protocol + location.host + "/ws/kitchen");

      ws.onopen = () => {
        console.info("[KDS] WebSocket connected");
        if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
      };

      ws.onmessage = (event) => {
        let msg;
        try { msg = JSON.parse(event.data); } catch { return; }

        if (msg.event !== "new_order" || !msg.order) return;
        const order = msg.order;

        // Skip if we already know this order (prevents double-alert on reconnect)
        if (knownOrderIds.has(order.id)) return;
        knownOrderIds.add(order.id);

        // Immediate audio alert
        if (order.source_role === "station_a") {
          if (!playSound(window.KITCHEN_AUDIO.stationSound)) beep(880, 400);
          speakSpanish(`Nuevo pedido. ${formatSpeech(order.items)}.`);
        } else {
          if (!playSound(window.KITCHEN_AUDIO.kitchenSound)) beep(660, 400);
        }

        // Refresh the order list from the server so we get the canonical state
        pollOrders();
      };

      ws.onerror = () => {
        // onerror is always followed by onclose; let onclose handle reconnect
      };

      ws.onclose = () => {
        console.warn("[KDS] WebSocket closed — retrying in", RETRY_MS, "ms");
        ws = null;
        retryTimer = setTimeout(connect, RETRY_MS);
      };
    } catch (e) {
      console.warn("[KDS] WebSocket init failed:", e);
      retryTimer = setTimeout(connect, RETRY_MS);
    }
  }

  connect();
})();
