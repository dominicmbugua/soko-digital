/* Soko Digital front-end (listings, filter chips, sell form).
   Loaded on every page; each feature starts only if its elements exist on that page.
   Talks to the Django JSON API. The server decides every price, fee and status. */

// ---------- Data handed over by Django ({{ boot|json_script }}); absent on info pages ----------
const bootEl = document.getElementById("boot-data");
const boot = bootEl ? JSON.parse(bootEl.textContent) : { produce: [], config: {}, urls: {} };
const PRODUCE = boot.produce;                    // [{id, name, photo, ref:[min,max]}]
const produceById = (id) => PRODUCE.find(p => p.id === id);

// ---------- Helpers ----------
const $ = (id) => document.getElementById(id);
const esc = Soko.esc;
const art = (slug, cls = "") => {
  const p = produceById(slug);
  return p && p.photo
    ? `<img class="pa photo ${cls}" src="${esc(p.photo)}" alt="" loading="lazy" decoding="async">`
    : `<svg class="pa ${cls}" aria-hidden="true" focusable="false"><use href="#p-${esc(slug)}"/></svg>`;
};
const icon = (name) => `<svg class="i" aria-hidden="true" focusable="false"><use href="#i-${name}"/></svg>`;
const initials = (name) => String(name).split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("");

// ---------- Listings ----------
let listingsCache = [];
let currentFilter = "all";

function setFilter(slug) {
  currentFilter = slug === "all" || produceById(slug) ? slug : "all";
  document.querySelectorAll("#chips .chip-btn").forEach(b => {
    const on = b.dataset.filter === currentFilter;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", on);
  });
  renderListings();
}

async function renderListings(newId) {
  const grid = $("listings");
  if (!grid) return;
  const limit = Number(grid.dataset.limit) || 0;                       // home page shows just a few
  const colClass = grid.dataset.cols || "col-md-6 col-lg-4 col-xxl-3";
  const res = await Soko.request("GET", "/api/listings/");
  if (!res.ok) { Soko.toast(res.error); return; }
  listingsCache = res.data;
  let items = listingsCache.filter(l => currentFilter === "all" || l.produce === currentFilter);
  const total = items.length;
  if (limit) items = items.slice(0, limit);
  if ($("count")) $("count").textContent = total + (total === 1 ? " listing" : " listings") + " from farmers on the Molo, Nakuru and Nairobi route";
  grid.innerHTML = items.length ? items.map((l, idx) => {
    const p = produceById(l.produce);
    const soldOut = l.qty < 1;
    const start = Math.min(10, l.qty);
    return `<div class="${colClass} wow fadeInUp" data-wow-delay="${((idx % 4) * 0.12 + 0.05).toFixed(2)}s">
      <article class="listing h-100 ${l.id === newId ? "is-new" : ""}" data-p="${esc(l.produce)}" data-id="${l.id}">
        <div class="listing-top ${p.photo ? "has-photo" : ""}">
          ${art(l.produce, "lg")}
          <span class="grade" title="Grade as stated by the farmer">Grade ${esc(l.grade)}</span>
        </div>
        <div class="listing-body">
          <h3>${esc(p.name)}</h3>
          <p class="price">KES ${l.price}<small> per kg</small></p>
          <p class="ref">Usual range ${p.ref[0]}–${p.ref[1]}</p>
          <div class="seller">
            <span class="av" aria-hidden="true">${esc(initials(l.farmer))}</span>
            <div><b>${esc(l.farmer)}</b><span>${icon("map-pin")}${esc(l.location)} · ${l.qty.toLocaleString("en-KE")} kg available</span></div>
          </div>
          ${soldOut ? `<button class="btn btn-primary w-100 mt-auto" disabled>Sold out</button>` : `
          <div class="buy-row">
            <div class="qty-pick">
              <button type="button" class="qbtn" data-d="-5" aria-label="Less">${icon("minus")}</button>
              <input type="number" inputmode="numeric" class="qin" min="1" max="${l.qty}" value="${start}" aria-label="Kilograms to order">
              <button type="button" class="qbtn" data-d="5" aria-label="More">${icon("plus")}</button><span>kg</span>
            </div>
            <button class="btn btn-primary add-btn">Add to cart</button>
          </div>`}
        </div>
      </article></div>`;
  }).join("") : `<p class="empty-note">No listings for this produce yet. Farmers can add one from the <a href="${esc((boot.urls || {}).sell || "/sell/")}">Sell produce</a> page.</p>`;
  if (window.Wow) Wow.refresh();
}

// ---------- Sell form (only on the Sell page, for logged-in farmers) ----------
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
    location: $("s-location").value.trim(),
    produce: $("s-produce").value, grade: $("s-grade").value,
    qty: Number($("s-qty").value), price: Number($("s-price").value)
  };
  const msg = $("sell-msg");
  if (!body.location || !(body.qty >= 10) || !(body.price > 0)) {
    msg.className = "ms-3 fw-semibold text-danger";
    msg.textContent = "Fill in every field. Quantity must be at least 10 kg.";
    return;
  }
  const res = await Soko.request("POST", "/api/listings/", body);
  if (!res.ok) {
    msg.className = "ms-3 fw-semibold text-danger";
    msg.textContent = res.error;
    return;
  }
  msg.className = "ms-3 fw-semibold text-success";
  msg.innerHTML = `Listing saved. Bring the produce to the collection point to be weighed and graded. <a href="${esc((boot.urls || {}).market || "/market/")}?produce=${esc(body.produce)}">See it in the marketplace</a>.`;
  e.target.reset();
  $("s-location").value = body.location;
  updateHint();
}

// ---------- Init ----------
function init() {
  if ($("listings")) {
    const wanted = new URLSearchParams(location.search).get("produce");
    if ($("chips") && wanted && produceById(wanted)) setFilter(wanted); else renderListings();

    if ($("chips")) $("chips").addEventListener("click", (e) => {
      const b = e.target.closest(".chip-btn");
      if (b) setFilter(b.dataset.filter);
    });

    $("listings").addEventListener("click", async (e) => {
      const card = e.target.closest(".listing");
      if (!card) return;
      const input = card.querySelector(".qin");
      const q = e.target.closest(".qbtn");
      if (q) {
        const max = Number(input.max);
        input.value = Math.min(max, Math.max(1, (Number(input.value) || 1) + Number(q.dataset.d)));
        return;
      }
      const add = e.target.closest(".add-btn");
      if (add) {
        const l = listingsCache.find(x => x.id === Number(card.dataset.id));
        const qty = Math.min(l.qty, Math.max(1, Number(input.value) || 1));
        input.value = qty;
        add.disabled = true;
        await SokoCart.add(l.id, qty, card.querySelector(".listing-top .pa"), l.produce, produceById(l.produce).name);
        add.disabled = false;
      }
    });
  }

  if ($("sell-form")) {
    updateHint();
    $("s-produce").addEventListener("change", updateHint);
    $("s-price").addEventListener("input", updateHint);
    $("sell-form").addEventListener("submit", submitListing);
  }
}

document.addEventListener("DOMContentLoaded", init);
