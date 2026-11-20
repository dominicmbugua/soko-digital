/* Soko Digital front-end (home page).
   Talks to the Django JSON API. The server decides every price, fee and status. */

// ---------- Data handed over by Django ({{ boot|json_script }}) ----------
const boot = JSON.parse(document.getElementById("boot-data").textContent);
const PRODUCE = boot.produce;                    // [{id, name, emoji, ref:[min,max]}]
const produceById = (id) => PRODUCE.find(p => p.id === id);

// ---------- Helpers ----------
const $ = (id) => document.getElementById(id);
const esc = Soko.esc;

// ---------- Listings ----------
let listingsCache = [];

async function renderListings(newId) {
  const res = await Soko.request("GET", "/api/listings/");
  if (!res.ok) { Soko.toast(res.error); return; }
  listingsCache = res.data;
  const filter = $("filter").value;
  const items = listingsCache.filter(l => filter === "all" || l.produce === filter);
  $("count").textContent = items.length + (items.length === 1 ? " listing" : " listings") + " from farmers on the Molo, Nakuru and Nairobi route";
  $("listings").innerHTML = items.length ? items.map((l, idx) => {
    const p = produceById(l.produce);
    const soldOut = l.qty < 1;
    const start = Math.min(10, l.qty);
    return `<div class="col-md-6 col-lg-4">
      <div class="card listing h-100 ${l.id === newId ? "is-new" : ""}" data-p="${esc(l.produce)}" data-id="${l.id}" style="--i:${idx}">
        <div class="listing-top">
          <span class="listing-emoji" aria-hidden="true">${p.emoji}</span>
          <span class="badge badge-grade" title="Grade as stated by the farmer">Grade ${esc(l.grade)}</span>
        </div>
        <div class="card-body d-flex flex-column">
          <h3 class="card-title h5">${esc(p.name)}</h3>
          <p class="price mb-0">KES ${l.price}<span class="fs-6 fw-normal"> per kg</span></p>
          <p class="ref mb-2">Usual range ${p.ref[0]}–${p.ref[1]}</p>
          <p class="mb-3">${esc(l.farmer)}, ${esc(l.location)}<br>${l.qty.toLocaleString("en-KE")} kg available</p>
          ${soldOut ? `<button class="btn btn-primary mt-auto" disabled>Sold out</button>` : `
          <div class="mt-auto">
            <div class="qty-pick mb-2">
              <button type="button" class="qbtn" data-d="-5" aria-label="Less">−</button>
              <input type="number" class="qin" min="1" max="${l.qty}" value="${start}" aria-label="Kilograms to order">
              <button type="button" class="qbtn" data-d="5" aria-label="More">+</button><span>kg</span>
            </div>
            <button class="btn btn-primary w-100 add-btn">Add to cart</button>
          </div>`}
        </div>
      </div></div>`;
  }).join("") : `<p>No listings for this produce yet. Farmers can add one below.</p>`;
}

// ---------- Sell form (only on the page for logged-in farmers) ----------
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
  msg.textContent = "Listing saved. Bring the produce to the collection point to be weighed and graded.";
  e.target.reset();
  $("s-location").value = body.location;
  updateHint();
  $("filter").value = "all";
  await renderListings(res.data.id);
  $("buy").scrollIntoView({ behavior: "smooth" });
}

// ---------- Motion: scroll reveal, count-up, navbar, parallax ----------
function initMotion() {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const nav = document.querySelector(".site-nav");
  const onScroll = () => {
    if (nav) nav.classList.toggle("scrolled", window.scrollY > 10);
    if (!reduce) document.documentElement.style.setProperty("--sy", window.scrollY);
  };
  window.addEventListener("scroll", () => requestAnimationFrame(onScroll), { passive: true });
  onScroll();

  const countUp = (el) => {
    const target = Number(el.dataset.count) || 0;
    if (reduce) { el.textContent = target; return; }
    const t0 = performance.now(), dur = 1200;
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      el.textContent = Math.round(target * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  const io = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (!e.isIntersecting) return;
      e.target.classList.add("in");
      e.target.querySelectorAll("[data-count]").forEach(countUp);
      io.unobserve(e.target);
    });
  }, { threshold: 0.12 });
  document.querySelectorAll(".reveal").forEach(el => io.observe(el));
}

// ---------- Init ----------
function init() {
  initMotion();
  const wanted = new URLSearchParams(location.search).get("produce");
  if (wanted && produceById(wanted)) $("filter").value = wanted;
  renderListings();

  $("filter").addEventListener("change", () => renderListings());
  if ($("sell-form")) {
    updateHint();
    $("s-produce").addEventListener("change", updateHint);
    $("s-price").addEventListener("input", updateHint);
    $("sell-form").addEventListener("submit", submitListing);
  }

  const grid = $("listings");
  grid.addEventListener("click", async (e) => {
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
      await SokoCart.add(l.id, qty, card.querySelector(".listing-emoji"), produceById(l.produce).emoji, produceById(l.produce).name);
      add.disabled = false;
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
