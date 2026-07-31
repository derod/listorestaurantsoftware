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

async function submitKitchenOrder() {
  const items = [...kitchenMap.values()].filter(x => x.quantity > 0)
    .map(x => ({ product_id: x.product_id, quantity: x.quantity }));
  if (!items.length) return toast("Agrega productos primero.", "error");
  const res = await fetch("/api/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_role: "kitchen", items })
  });
  if (!res.ok) return toast("No se pudo enviar.", "error");
  kitchenMap.clear();
  kitchenSequence.length = 0;
  renderKitchenSummary();
  document.getElementById("createModal").classList.remove("open");
  pollOrders();
  toast("Pedido enviado.");
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

// Decoded MP3s cached as AudioBuffers so we can play them through the
// AudioContext. On iPad this is the ONLY reliable path: the <audio> element
// is muted by the hardware silent switch and needs a per-element gesture
// unlock, while the AudioContext plays through silent mode after one tap.
const _soundBuffers = {};   // src -> AudioBuffer
const _soundLoading = {};   // src -> Promise

function _loadBuffer(src) {
  if (_soundBuffers[src]) return Promise.resolve(_soundBuffers[src]);
  if (_soundLoading[src]) return _soundLoading[src];
  const ctx = _getAudioCtx();
  if (!ctx || typeof ctx.decodeAudioData !== "function") return Promise.reject(new Error("no webaudio"));
  const p = fetch(normalizeAudioSrc(src), { credentials: "same-origin" })
    .then((r) => { if (!r.ok) throw new Error("http " + r.status); return r.arrayBuffer(); })
    .then((buf) => new Promise((res, rej) => {
      // Safari <14.1 only supports the callback form of decodeAudioData.
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
  gain.gain.value = window.KITCHEN_AUDIO.volume ?? 1;
  source.connect(gain);
  gain.connect(ctx.destination);
  try { source.start(0); } catch (e) { return false; }
  return true;
}

// Play via Web Audio. Returns true if it handled playback (so the caller
// skips the <audio> fallback and we never double up). Falls back only when
// Web Audio is unavailable or the decode fails.
function _playViaWebAudio(src) {
  const ctx = _getAudioCtx();
  if (!ctx || typeof ctx.decodeAudioData !== "function") return false;
  if (_soundBuffers[src]) return _playBuffer(_soundBuffers[src]);
  _loadBuffer(src)
    .then((buf) => _playBuffer(buf))
    .catch((err) => { console.warn("[KDS] WebAudio failed, using <audio>:", src, err); _playSoundElement(src); });
  return true;
}

function _prewarmSounds() {
  const cfg = window.KITCHEN_AUDIO || {};
  Object.keys(cfg).forEach((k) => {
    const v = cfg[k];
    if (typeof v === "string" && /\.(mp3|wav|ogg|m4a|aac)$/i.test(v)) _loadBuffer(v).catch(() => {});
  });
}

let _audioPrewarmed = false;

// Canonical iOS unlock: resume the context AND play a 1-frame silent buffer
// inside the gesture. Without the silent buffer, later source.start() calls
// stay muted on iPad even though the context reports "running".
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

function _initAudioCtxOnGesture() {
  window.userInteracted = true;
  _unlockAudio();
  if (!_audioPrewarmed) { _audioPrewarmed = true; try { _prewarmSounds(); } catch (e) {} }
}
// NOT { once } — re-unlock on every tap so audio recovers after the iPad
// sleeps/locks (iOS suspends the AudioContext when backgrounded).
document.addEventListener("click",      _initAudioCtxOnGesture, { capture: true });
document.addEventListener("touchstart", _initAudioCtxOnGesture, { capture: true });
document.addEventListener("keydown",    _initAudioCtxOnGesture, { capture: true });
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && _audioCtx && _audioCtx.state === "suspended") {
    _audioCtx.resume().catch(() => {});
  }
});

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

function showAudioLockedHint() {
  let hint = document.getElementById("audioLockedHint");
  if (hint) return;
  hint = document.createElement("button");
  hint.id = "audioLockedHint";
  hint.textContent = "🔔 Toca aquí para activar alertas";
  hint.style.cssText = "position:fixed;top:20px;left:50%;transform:translateX(-50%);z-index:9999;padding:18px 28px;font-size:22px;font-weight:800;border:none;border-radius:16px;background:var(--yellow,#ffd24d);color:#111;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,0.4);animation:pulse 1.2s infinite;";
  hint.onclick = () => {
    if (typeof window.unlockAudio === "function") window.unlockAudio();
    window.userInteracted = true;
    hint.remove();
  };
  document.body.appendChild(hint);
  if (!document.getElementById("audioLockedHintKeyframes")) {
    const style = document.createElement("style");
    style.id = "audioLockedHintKeyframes";
    style.textContent = "@keyframes pulse{0%,100%{transform:translateX(-50%) scale(1);}50%{transform:translateX(-50%) scale(1.06);}}";
    document.head.appendChild(style);
  }
}

function playSound(src) {
  if (!src) return false;
  // Prefer Web Audio (works on iPad even in silent mode); fall back to <audio>.
  if (window.userInteracted && _playViaWebAudio(src)) return true;
  return _playSoundElement(src);
}

function _playSoundElement(src) {
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
      console.warn("[KDS] Audio file failed to load:", src);
    }, { once: true });
    const playPromise = audio.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch((err) => {
        cleanup();
        console.warn("[KDS] Audio playback blocked/failed:", src, err);
        if (err && (err.name === "NotAllowedError" || err.name === "AbortError")) {
          showAudioLockedHint();
        }
      });
    }
    return true;
  } catch (e) { return false; }
}

let _titleFlashTimer = null;
let _originalTitle = null;
function flashPageTitle(text) {
  if (_originalTitle === null) _originalTitle = document.title;
  if (_titleFlashTimer) clearInterval(_titleFlashTimer);
  let toggle = false;
  _titleFlashTimer = setInterval(() => {
    document.title = toggle ? _originalTitle : text;
    toggle = !toggle;
  }, 900);
  setTimeout(() => {
    clearInterval(_titleFlashTimer);
    _titleFlashTimer = null;
    document.title = _originalTitle;
  }, 12000);
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

    /* Timer intentionally hidden on the kitchen card (kept in Admin only). */
    const timerHtml = "";

    /* Status label */
    const statusLabel = status.toUpperCase();

    /* Waiter */
    const waiterHtml = order.waiter_name
      ? `<div class="order-waiter-big">Agente: <strong>${order.waiter_name}</strong></div>`
      : "";

    /* Uber (pedido de delivery con nombre) — etiqueta naranja neón */
    const uberHtml = order.order_label
      ? `<div class="order-uber-big">🛵 UBER · ${String(order.order_label).replace(/[<>]/g, "")}</div>`
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
        <button class="btn-listo" data-action="despachar" data-order-id="${order.id}">LISTO</button>
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
          <div class="order-status-big ${status === 'preparando' ? 'blink-prep' : ''}">${statusLabel}</div>
          ${waiterHtml}
          ${uberHtml}
        </div>
        ${timerHtml}
      </div>
      <div class="order-items-big">
        ${order.items.map(item =>
          `<div class="order-line-big"><span class="qty"><span class="mult">×</span>${item.quantity}</span><span class="prod-name">${item.product_name}</span></div>`
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

/* ─── Cancelled-order alerts (persistent until dismissed) ───────────── */
let cancelledShown = new Set();
let firstCancelledPoll = true;

async function pollCancelled() {
  try {
    const res = await fetch("/api/orders/cancelled-recent?minutes=5");
    const cancelled = await res.json();
    cancelled.forEach(o => {
      if (cancelledShown.has(o.id)) return;
      cancelledShown.add(o.id);
      if (firstCancelledPoll) return;  // don't alert for ones already cancelled at load
      showCancelledAlert(o);
      if (!playSound(window.KITCHEN_AUDIO.cancelSound)) beep(300, 600);
      flashPageTitle("🚫 CANCELADO");
      speakSpanish(`Pedido cancelado. ${formatSpeech(o.items)}.`);
    });
    firstCancelledPoll = false;
  } catch (e) {}
}

function showCancelledAlert(o) {
  const host = document.getElementById("cancelledAlerts");
  if (!host || document.getElementById("cancelled-" + o.id)) return;
  const items = o.items.map(i => `${i.quantity} ${i.product_name}`).join(", ");
  const el = document.createElement("div");
  el.className = "cancel-alert";
  el.id = "cancelled-" + o.id;
  el.innerHTML =
    '<div class="ca-left">' +
      '<div class="ca-title">🚫 CANCELADO · #' + o.id + '</div>' +
      '<div class="ca-items">' + items + '</div>' +
    '</div>' +
    '<button class="ca-dismiss">Entendido</button>';
  el.querySelector(".ca-dismiss").addEventListener("click", () => el.remove());
  host.prepend(el);
}

async function pollOrders() {
  const res = await fetch("/api/orders/active");
  const all = await res.json();
  const orders = all.filter(o => o.source_role !== "kitchen");
  const newOrders = orders.filter(o => !knownOrderIds.has(o.id));
  newOrders.forEach(order => {
    knownOrderIds.add(order.id);
    flashPageTitle("🔔 NUEVO PEDIDO");
    if (order.source_role === "station_a") {
      if (!playSound(window.KITCHEN_AUDIO.kitchenSound)) beep(880, 400);
      speakSpanish(`Nuevo pedido. ${formatSpeech(order.items)}.`);
    } else {
      if (!playSound(window.KITCHEN_AUDIO.kitchenSound)) beep(660, 400);
    }
  });
  window.INITIAL_ORDERS = orders;
  renderOrders(orders);
  pollCancelled();
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
  if (!name) return toast("Escribe un nombre.", "error");
  const res = await fetch("/api/products", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    return toast(err.detail || "No se pudo crear.", "error");
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

        // Immediate audio alert — also flash the page title so the cook sees it
        flashPageTitle("🔔 NUEVO PEDIDO");
        if (order.source_role === "station_a") {
          if (!playSound(window.KITCHEN_AUDIO.kitchenSound)) beep(880, 400);
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
    const cfg = window.KITCHEN_AUDIO || {};
    const src = Object.keys(cfg).map((k) => cfg[k]).find((v) => typeof v === "string" && /\.(mp3|wav|ogg|m4a|aac)$/i.test(v));
    if (!src) { out += "MP3: NO hay sonido configurado (Admin › Audio)\n"; status.textContent = out; return; }
    out += "MP3 src: " + src + "\n";
    status.textContent = out + "MP3: cargando…";
    try {
      const buf = await _loadBuffer(src);
      const ok = _playBuffer(buf);
      out += "MP3: decodificado OK, reproducido=" + ok + " — ¿lo oíste?\n";
    } catch (e) {
      out += "MP3: FALLO -> " + (e && e.message ? e.message : e) + "\n";
      try { _playSoundElement(src); out += "Fallback <audio>: intentado\n"; } catch (e2) {}
    }
    status.textContent = out;
  });
  document.body.appendChild(btn);
  document.body.appendChild(status);
}
if (document.readyState !== "loading") _injectAudioTest();
else document.addEventListener("DOMContentLoaded", _injectAudioTest);
