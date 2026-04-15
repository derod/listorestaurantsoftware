const orderMap = new Map();
const orderSequence = [];

function renderSummary() {
  const summary = document.getElementById("orderSummary");
  const total = document.getElementById("totalItems");
  const entries = [...orderMap.values()];
  if (!entries.length) {
    summary.innerHTML = "No hay productos.";
    summary.classList.add("empty-state");
    total.textContent = "0";
    return;
  }
  summary.classList.remove("empty-state");
  summary.innerHTML = entries.map(item => `
    <div class="summary-item">
      <span>${item.name}</span>
      <strong>${item.quantity}</strong>
    </div>
  `).join("");
  total.textContent = entries.reduce((acc, item) => acc + item.quantity, 0);
}

function addProduct(id, name) {
  const key = String(id);
  if (!orderMap.has(key)) orderMap.set(key, { product_id: id, name, quantity: 0 });
  orderMap.get(key).quantity += 1;
  orderSequence.push(key);
  renderSummary();
}

async function submitOrder() {
  const items = [...orderMap.values()].filter(x => x.quantity > 0).map(x => ({ product_id: x.product_id, quantity: x.quantity }));
  if (!items.length) return alert("Agrega productos primero.");
  const res = await fetch("/api/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_role: window.KDS_CONFIG.sourceRole, items, waiter_id: window.KDS_CONFIG.waiterId, waiter_name: window.KDS_CONFIG.waiterName })
  });
  if (!res.ok) return alert("No se pudo enviar.");
  orderMap.clear();
  orderSequence.length = 0;
  renderSummary();
  alert("Pedido enviado.");
}

function bindProductButtons() {
  document.querySelectorAll("#productsGrid .product-btn").forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => addProduct(btn.dataset.productId, btn.dataset.productName));
  });
}
bindProductButtons();

async function refreshProductsGrid() {
  const res = await fetch("/api/products");
  const products = await res.json();
  const grid = document.getElementById("productsGrid");
  grid.innerHTML = products.map(p => {
    const img = p.image_path ? `<img src="${p.image_path}" alt="" style="width:100%;height:110px;object-fit:cover;border-radius:12px;margin-bottom:8px;">` : "";
    return `<button class="product-btn" data-product-id="${p.id}" data-product-name="${p.name}">${img}<span>${p.name}</span></button>`;
  }).join("");
  bindProductButtons();
}

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
  closeNewProductModal();
  await refreshProductsGrid();
}
document.getElementById("newProductBtn").addEventListener("click", openNewProductModal);
document.getElementById("newProductCancelBtn").addEventListener("click", closeNewProductModal);
document.getElementById("newProductSaveBtn").addEventListener("click", saveNewProduct);
newProductInput.addEventListener("keydown", (e) => { if (e.key === "Enter") saveNewProduct(); });
document.getElementById("sendBtn").addEventListener("click", submitOrder);
document.getElementById("clearBtn").addEventListener("click", () => { orderMap.clear(); orderSequence.length = 0; renderSummary(); });
document.getElementById("undoBtn").addEventListener("click", () => {
  const last = orderSequence.pop();
  if (!last || !orderMap.has(last)) return;
  orderMap.get(last).quantity -= 1;
  if (orderMap.get(last).quantity <= 0) orderMap.delete(last);
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

/* ─── Safari autoplay guard ─────────────────────────────────────────── */

if (typeof window.userInteracted === "undefined") window.userInteracted = false;
document.addEventListener("click", () => { window.userInteracted = true; }, { once: true, capture: true });
document.addEventListener("touchstart", () => { window.userInteracted = true; }, { once: true, capture: true });

/* ─── Audio helpers ─────────────────────────────────────────────────── */

const AUDIO = window.STATION_AUDIO || {};

function playSoundFile(src) {
  if (!window.userInteracted) return false;
  if (!src) return false;
  try {
    const audio = new Audio(src);
    audio.preload = "auto";
    audio.load();
    audio.volume = AUDIO.volume ?? 1;
    audio.play().catch(() => {});
    return true;
  } catch (e) { return false; }
}

function beep(freq, durMs) {
  if (!window.userInteracted) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
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
    utterance.onerror = () => { beep(880, 400); };
    speechSynthesis.cancel();
    setTimeout(() => { speechSynthesis.speak(utterance); }, 100);
    setTimeout(() => { if (!spoken) beep(880, 400); }, 600);
  } catch (e) { beep(880, 400); }
}

function formatItemsSpeech(items) {
  return items.map(i => `${i.quantity} ${i.product_name || i.name}`).join(", ");
}

/* ─── Polling ───────────────────────────────────────────────────────── */

let myReadyIds = new Set();
let firstPoll = true;

async function pollKitchenInternal() {
  try {
    const res = await fetch("/api/orders/active");
    const all = await res.json();

    const kitchenOrders = all.filter(o => o.source_role === "kitchen");
    const newKitchenIds = kitchenOrders.filter(o => !stationKnownIds.has(o.id));
    if (newKitchenIds.length > 0 && !firstPoll) {
      if (!playSoundFile(AUDIO.kitchenSound)) beep(880, 400);
      newKitchenIds.forEach(o => speakSpanish(`Nuevo pedido de cocina. ${formatItemsSpeech(o.items)}.`));
    }
    stationKnownIds = new Set(kitchenOrders.map(o => o.id));

    const myOrders = all.filter(o => o.source_role === "station_a");
    const nowReady = myOrders.filter(o => o.status === "listo" && !myReadyIds.has(o.id));
    if (nowReady.length > 0 && !firstPoll) {
      if (!playSoundFile(AUDIO.readySound)) beep(1320, 500);
      nowReady.forEach(o => speakSpanish(`Pedido listo. ${formatItemsSpeech(o.items)}.`));
    }
    myReadyIds = new Set(myOrders.filter(o => o.status === "listo").map(o => o.id));

    firstPoll = false;
    renderKitchenInternal(kitchenOrders);
  } catch (e) {}
}

pollKitchenInternal();
setInterval(pollKitchenInternal, 4000);
