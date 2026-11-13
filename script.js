/* Soko Digital – marketplace demo with a simulated (mock) API.
   Nothing here talks to a real server or real M-Pesa. */

const FEE_RATE = 0.08;        // platform fee, deducted from the farmer's payout
const DELIVERY_PER_KG = 6;    // KES per kg to Nairobi

const PRODUCE = [
  { id: "potatoes", name: "Potatoes",           ref: [44, 52] },
  { id: "maize",    name: "Maize",              ref: [58, 68] },
  { id: "tomatoes", name: "Tomatoes",           ref: [78, 92] },
  { id: "kale",     name: "Kale (sukuma wiki)", ref: [36, 44] },
  { id: "onions",   name: "Onions",             ref: [88, 102] },
  { id: "beans",    name: "Beans",              ref: [140, 160] },
  { id: "bananas",  name: "Bananas",            ref: [50, 60] },
  { id: "avocados", name: "Avocados",           ref: [100, 120] }
];
const produceById = (id) => PRODUCE.find(p => p.id === id);

// ---------- Mock database ----------
const db = {
  nextListing: 9,
  listings: [
    { id: "L1", farmer: "Wanjiku Kamau",  location: "Molo",     produce: "potatoes", price: 48,  qty: 800, grade: "A" },
    { id: "L2", farmer: "Peter Kiprono",  location: "Elburgon", produce: "potatoes", price: 45,  qty: 1500, grade: "B" },
    { id: "L3", farmer: "Grace Njeri",    location: "Nakuru",   produce: "tomatoes", price: 82,  qty: 300, grade: "A" },
    { id: "L4", farmer: "Samuel Mwangi",  location: "Njoro",    produce: "kale",     price: 38,  qty: 250, grade: "A" },
    { id: "L5", farmer: "Faith Chebet",   location: "Molo",     produce: "onions",   price: 98,  qty: 400, grade: "B" },
    { id: "L6", farmer: "John Ochieng",   location: "Nakuru",   produce: "maize",    price: 60,  qty: 2000, grade: "B" },
    { id: "L7", farmer: "Mary Wambui",    location: "Elburgon", produce: "beans",    price: 155, qty: 180, grade: "A" },
    { id: "L8", farmer: "David Kariuki",  location: "Njoro",    produce: "avocados", price: 125, qty: 220, grade: "A" }
  ],
  orders: []
};

// ---------- Mock API ----------
const wait = (ms) => new Promise(r => setTimeout(r, ms));
const rand = (a, b) => Math.floor(a + Math.random() * (b - a + 1));

const api = {
  async getListings() { await wait(rand(150, 300)); return { status: 200, data: db.listings }; },

  async createListing(body) {
    await wait(rand(300, 500));
    const listing = { id: "L" + db.nextListing++, ...body };
    db.listings.unshift(listing);
    return { status: 201, data: listing };
  },

  async createOrder({ listingId, qty, phone }) {
    await wait(rand(300, 600));
    const l = db.listings.find(x => x.id === listingId);
    if (!l || qty > l.qty) return { status: 409, error: "Not enough produce left in this listing." };
    l.qty -= qty;
    const produceValue = l.price * qty;
    const order = {
      id: "ORD-" + rand(1000, 9999), listingId, qty, phone,
      produceValue, delivery: qty * DELIVERY_PER_KG,
      status: "AWAITING_PAYMENT"
    };
    db.orders.push(order);
    return { status: 201, data: order };
  },

  // M-Pesa prompt + callback, ending with the money sitting in the holding account.
  async collectPayment(orderId) {
    await wait(rand(1800, 2600));
    const o = db.orders.find(x => x.id === orderId);
    o.status = "PAYMENT_HELD";
    return { status: 200, data: o };
  },

  async deliver(orderId) {
    await wait(rand(1500, 2200));
    const o = db.orders.find(x => x.id === orderId);
    o.status = "DELIVERED";
    return { status: 200, data: o };
  },

  async confirmDelivery(orderId) {
    await wait(rand(700, 1100));
    const o = db.orders.find(x => x.id === orderId);
    const fee = Math.round(o.produceValue * FEE_RATE);
    o.status = "SETTLED";
    o.settlement = { fee, farmerPayout: o.produceValue - fee };
    return { status: 200, data: o };
  },

  async reportProblem(orderId) {
    await wait(rand(500, 900));
    const o = db.orders.find(x => x.id === orderId);
    o.status = "DISPUTED";
    return { status: 200, data: o };
  },

  async health() { await wait(rand(80, 400)); return { ok: Math.random() > 0.08, ms: rand(40, 380) }; }
};

const ENDPOINTS = [
  { method: "GET",  path: "/api/listings" },
  { method: "POST", path: "/api/listings" },
  { method: "POST", path: "/api/orders" },
  { method: "POST", path: "/api/payments/collect" },
  { method: "POST", path: "/api/orders/:id/confirm" },
  { method: "POST", path: "/api/payouts/farmer" }
];

// ---------- Helpers ----------
const $ = (id) => document.getElementById(id);
const kes = (n) => "KES " + Math.round(n).toLocaleString("en-KE");
const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function normalisePhone(raw) {
  const m = raw.replace(/[\s-]/g, "").match(/^(?:\+?254|0)([17]\d{8})$/);
  return m ? "254" + m[1] : null;
}

// ---------- Reference prices and listings ----------
function renderReference() {
  $("ref-rows").innerHTML = PRODUCE.map(p =>
    `<tr><th scope="row" class="fw-normal">${p.name}</th><td class="price">${p.ref[0]}–${p.ref[1]}</td></tr>`).join("");
}

async function renderListings(newId) {
  const res = await api.getListings();
  const filter = $("filter").value;
  const items = res.data.filter(l => filter === "all" || l.produce === filter);
  $("count").textContent = items.length + (items.length === 1 ? " listing" : " listings") + " from farmers on the Molo, Nakuru and Nairobi route";
  $("listings").innerHTML = items.length ? items.map(l => {
    const p = produceById(l.produce);
    const soldOut = l.qty < 1;
    return `<div class="col-md-6 col-lg-4">
      <div class="card listing h-100 ${l.id === newId ? "is-new" : ""}">
        <div class="card-body d-flex flex-column">
          <div class="d-flex justify-content-between align-items-start">
            <h3 class="card-title h5">${p.name}</h3>
            <span class="badge badge-grade" title="Grade as stated by the farmer">Grade ${esc(l.grade)}</span>
          </div>
          <p class="price mb-0">KES ${l.price}<span class="fs-6 fw-normal"> per kg</span></p>
          <p class="ref mb-2">Usual range ${p.ref[0]}–${p.ref[1]}</p>
          <p class="mb-3">${esc(l.farmer)}, ${esc(l.location)}<br>${l.qty.toLocaleString("en-KE")} kg available</p>
          <button class="btn btn-primary mt-auto buy-btn" data-id="${l.id}" ${soldOut ? "disabled" : ""}>${soldOut ? "Sold out" : "Order"}</button>
        </div>
      </div></div>`;
  }).join("") : `<p>No listings for this produce yet. Farmers can add one below.</p>`;
}

// ---------- Sell form ----------
function updateHint() {
  const p = produceById($("s-produce").value);
  const price = Number($("s-price").value);
  let text = `Usual range for ${p.name.toLowerCase()}: KES ${p.ref[0]}–${p.ref[1]} per kg.`;
  if (price) {
    if (price > p.ref[1] * 1.15) text += " Your price is well above the range, so buyers may skip it.";
    else if (price < p.ref[0] * 0.85) text += " Your price is well below the range. You may be selling for less than you could.";
    else text += " Your price is within the usual range.";
  }
  $("price-hint").textContent = text;
}

async function submitListing(e) {
  e.preventDefault();
  const body = {
    farmer: $("s-name").value.trim(), location: $("s-location").value.trim(),
    produce: $("s-produce").value, grade: $("s-grade").value,
    qty: Number($("s-qty").value), price: Number($("s-price").value)
  };
  const msg = $("sell-msg");
  if (!body.farmer || !body.location || !(body.qty >= 10) || !(body.price > 0)) {
    msg.className = "ms-3 fw-semibold text-danger";
    msg.textContent = "Fill in every field. Quantity must be at least 10 kg.";
    return;
  }
  const res = await api.createListing(body);
  msg.className = "ms-3 fw-semibold text-success";
  msg.textContent = "Listing posted. Bring the produce to the collection point to be weighed and graded.";
  e.target.reset();
  updateHint();
  $("filter").value = "all";
  await renderListings(res.data.id);
  $("buy").scrollIntoView({ behavior: "smooth" });
}

// ---------- Order modal ----------
let modal, active = null;

function openOrder(id) {
  const l = db.listings.find(x => x.id === id);
  active = { listing: l, order: null };
  $("order-summary").innerHTML = `<strong>${produceById(l.produce).name}</strong> from ${esc(l.farmer)}, ${esc(l.location)}. KES ${l.price} per kg, ${l.qty} kg available.`;
  $("o-qty").value = Math.min(50, l.qty);
  $("o-qty").max = l.qty;
  $("o-phone").value = "";
  $("o-error").textContent = "";
  $("order-form").classList.remove("d-none");
  $("o-pay").disabled = false;
  $("timeline").classList.add("d-none");
  $("confirm-box").classList.add("d-none");
  $("o-result").classList.add("d-none");
  updateTotals();
  modal.show();
}

function updateTotals() {
  if (!active) return;
  const qty = Number($("o-qty").value) || 0;
  const value = qty * active.listing.price, delivery = qty * DELIVERY_PER_KG;
  $("t-produce").textContent = kes(value);
  $("t-delivery").textContent = kes(delivery);
  $("t-total").textContent = kes(value + delivery);
}

function setStep(step, state) {
  const li = document.querySelector(`#timeline li[data-step="${step}"]`);
  li.className = "list-group-item " + (state ? state + "-step" : "");
}

function showResult(text, kind) {
  const r = $("o-result");
  r.className = "alert mt-3 alert-" + kind;
  r.textContent = text;
}

async function submitOrder(e) {
  e.preventDefault();
  const qty = Number($("o-qty").value);
  const phone = normalisePhone($("o-phone").value);
  const err = $("o-error");
  if (!qty || qty < 1 || qty > active.listing.qty) { err.textContent = `Enter a quantity between 1 and ${active.listing.qty} kg.`; return; }
  if (!phone) { err.textContent = "Enter a Safaricom number like 0712345678."; return; }
  err.textContent = "";

  $("o-pay").disabled = true;
  $("order-form").classList.add("d-none");
  $("timeline").classList.remove("d-none");
  ["order", "paid", "delivered", "released"].forEach(s => setStep(s, ""));

  setStep("order", "active");
  const created = await api.createOrder({ listingId: active.listing.id, qty, phone });
  if (created.status !== 201) {
    setStep("order", "failed");
    showResult(created.error, "danger");
    return;
  }
  active.order = created.data;
  setStep("order", "done");

  setStep("paid", "active");
  await api.collectPayment(active.order.id);
  setStep("paid", "done");

  setStep("delivered", "active");
  await api.deliver(active.order.id);
  setStep("delivered", "done");

  $("confirm-box").classList.remove("d-none");
  renderListings();
}

async function confirmOrder() {
  $("confirm-box").classList.add("d-none");
  setStep("released", "active");
  const res = await api.confirmDelivery(active.order.id);
  const s = res.data.settlement;
  setStep("released", "done");
  showResult(`Order ${res.data.id} complete. Farmer paid ${kes(s.farmerPayout)} (price ${kes(res.data.produceValue)} minus our ${FEE_RATE * 100}% fee of ${kes(s.fee)}).`, "success");
}

async function reportOrder() {
  $("confirm-box").classList.add("d-none");
  const res = await api.reportProblem(active.order.id);
  setStep("released", "failed");
  showResult(`Order ${res.data.id}: your money stays on hold while we review the photos you send. The farmer is not paid until the review is done.`, "warning");
}

// ---------- API status ----------
async function pingAll() {
  $("endpoints").innerHTML = ENDPOINTS.map((ep, i) => `
    <li class="list-group-item d-flex align-items-center gap-3">
      <span class="method ${ep.method.toLowerCase()}">${ep.method}</span>
      <span class="path flex-grow-1">${ep.path}</span>
      <span class="text-muted small" id="ms-${i}">–</span>
      <span class="badge text-bg-secondary" id="badge-${i}">Checking</span>
    </li>`).join("");
  await Promise.all(ENDPOINTS.map(async (ep, i) => {
    const res = await api.health();
    $("ms-" + i).textContent = res.ms + " ms";
    $("badge-" + i).textContent = res.ok ? "Up" : "Down";
    $("badge-" + i).className = "badge " + (res.ok ? "text-bg-success" : "text-bg-danger");
  }));
}

// ---------- Init ----------
function init() {
  modal = new bootstrap.Modal($("order-modal"));
  $("filter").add(new Option("All produce", "all"));
  PRODUCE.forEach(p => { $("filter").add(new Option(p.name, p.id)); $("s-produce").add(new Option(p.name, p.id)); });

  renderReference();
  renderListings();
  updateHint();
  pingAll();

  $("filter").addEventListener("change", () => renderListings());
  $("s-produce").addEventListener("change", updateHint);
  $("s-price").addEventListener("input", updateHint);
  $("sell-form").addEventListener("submit", submitListing);
  $("listings").addEventListener("click", (e) => {
    const b = e.target.closest(".buy-btn");
    if (b) openOrder(b.dataset.id);
  });
  $("o-qty").addEventListener("input", updateTotals);
  $("order-form").addEventListener("submit", submitOrder);
  $("o-confirm").addEventListener("click", confirmOrder);
  $("o-report").addEventListener("click", reportOrder);
  $("ping").addEventListener("click", pingAll);
}

document.addEventListener("DOMContentLoaded", init);
