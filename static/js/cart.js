/* Site-wide: Soko helpers (request, toast) and the cart drawer. */
(function () {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const kes = (n) => "KES " + Math.round(n).toLocaleString("en-KE");
  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const csrf = () => document.querySelector('meta[name="csrf-token"]').content;
  const art = (slug, cls = "", photo = "") => photo
    ? `<img class="pa photo ${cls}" src="${esc(photo)}" alt="">`
    : `<svg class="pa ${cls}" aria-hidden="true" focusable="false"><use href="#p-${esc(slug)}"/></svg>`;
  const ico = (name) => `<svg class="i" aria-hidden="true" focusable="false"><use href="#i-${name}"/></svg>`;

  async function request(method, url, body) {
    const opts = { method, credentials: "same-origin", headers: { "Accept": "application/json" } };
    if (method !== "GET") {
      opts.headers["Content-Type"] = "application/json";
      opts.headers["X-CSRFToken"] = csrf();
      opts.body = JSON.stringify(body || {});
    }
    try {
      const r = await fetch(url, opts);
      let data = null;
      try { data = await r.json(); } catch (_) { /* not JSON */ }
      return r.ok ? { ok: true, status: r.status, data }
                  : { ok: false, status: r.status, error: (data && data.error) || "Something went wrong. Please try again." };
    } catch (_) {
      return { ok: false, status: 0, error: "Could not reach the server. Check your connection." };
    }
  }

  let toastTimer;
  function toast(msg) {
    const t = document.getElementById("toast");
    if (!t) return;
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 4200);
  }

  window.Soko = { request, toast, kes, esc };

  const drawer = document.getElementById("cart-drawer");
  if (!drawer) {   // farmers and staff have no cart
    window.SokoCart = { add: async () => toast("Only buyer accounts can order. Log in with a buyer account to shop.") };
    return;
  }

  const badge = document.getElementById("cart-badge");
  const list = document.getElementById("cart-items");
  const foot = document.getElementById("cart-foot");
  const notes = document.getElementById("cart-notes");
  let cart = { items: [] };

  function setBadge(n) {
    badge.textContent = n; badge.hidden = !n;
    badge.classList.remove("bump"); void badge.offsetWidth; badge.classList.add("bump");
  }

  function render(c) {
    cart = c;
    setBadge(c.count);
    notes.innerHTML = (c.notes || []).map(n => `<div class="alert alert-warning py-2 small mt-2 mb-0">${esc(n)}</div>`).join("");
    if (!c.items.length) {
      list.innerHTML = `<li class="cart-empty"><span class="empty-ico">${ico("shopping-basket")}</span><strong>Your cart is empty</strong><p>Add produce from the listings and it will show up here.</p>
        <button class="btn btn-primary" data-bs-dismiss="offcanvas">Browse produce</button></li>`;
      foot.hidden = true;
      return;
    }
    list.innerHTML = c.items.map(i => `
      <li class="ci" data-id="${i.id}" data-max="${i.max}" data-qty="${i.qty}">
        <span class="ci-art" data-p="${esc(i.produce)}">${art(i.produce, "md", i.photo)}</span>
        <div class="ci-main">
          <strong>${esc(i.name)}</strong>
          <small>${esc(i.farmer)}, ${esc(i.location)} · Grade ${esc(i.grade)}</small>
          <small>${kes(i.price)} per kg</small>
          <div class="qty-pick sm">
            <button type="button" data-act="dec" aria-label="Less">${ico("minus")}</button>
            <input type="number" min="1" max="${i.max}" value="${i.qty}" aria-label="Kilograms">
            <button type="button" data-act="inc" aria-label="More">${ico("plus")}</button><span>kg</span>
          </div>
        </div>
        <div class="ci-side"><b>${kes(i.line)}</b><button type="button" class="ci-del" data-act="del" aria-label="Remove ${esc(i.name)}">${ico("x")}</button></div>
      </li>`).join("");
    document.getElementById("c-sub").textContent = kes(c.subtotal);
    document.getElementById("c-del").textContent = kes(c.delivery);
    document.getElementById("c-total").textContent = kes(c.total);
    foot.hidden = false;
  }

  async function load() {
    const r = await request("GET", "/api/cart/");
    if (r.ok) render(r.data);
  }

  async function setQty(id, qty) {
    const r = await request("POST", "/api/cart/set/", { listingId: id, qty });
    if (!r.ok) { toast(r.error); return; }
    render(r.data);
    document.dispatchEvent(new CustomEvent("soko:cart-changed"));
  }

  list.addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const li = b.closest(".ci"), id = Number(li.dataset.id), qty = Number(li.dataset.qty), max = Number(li.dataset.max);
    if (b.dataset.act === "del") setQty(id, 0);
    if (b.dataset.act === "inc") setQty(id, Math.min(max, qty + 5));
    if (b.dataset.act === "dec") setQty(id, Math.max(1, qty - 5));
  });
  list.addEventListener("change", (e) => {
    if (e.target.tagName !== "INPUT") return;
    const li = e.target.closest(".ci");
    setQty(Number(li.dataset.id), Math.max(1, Number(e.target.value) || 1));
  });

  function fly(fromEl) {
    const target = document.getElementById("cart-btn");
    if (reduce || !fromEl || !target) return;
    const a = fromEl.getBoundingClientRect(), b = target.getBoundingClientRect();
    const size = 56;
    const sx = a.left + a.width / 2 - size / 2, sy = a.top + a.height / 2 - size / 2;
    const dx = (b.left + b.width / 2 - size / 2) - sx, dy = (b.top + b.height / 2 - size / 2) - sy;
    const el = fromEl.cloneNode(true);
    el.removeAttribute("class"); el.setAttribute("class", "fly");
    el.style.cssText = `left:${sx}px;top:${sy}px;width:${size}px;height:${size}px`;
    document.body.appendChild(el);
    el.animate([
      { transform: "translate(0,0) scale(1)", opacity: 1 },
      { transform: `translate(${dx * 0.55}px, ${dy * 0.55 - 70}px) scale(.8)`, opacity: 1, offset: 0.5 },
      { transform: `translate(${dx}px, ${dy}px) scale(.25)`, opacity: .2 }
    ], { duration: 650, easing: "cubic-bezier(.4,0,.2,1)" }).onfinish = () => el.remove();
  }

  async function add(listingId, qty, fromEl, slug, name) {
    const r = await request("POST", "/api/cart/add/", { listingId, qty });
    if (!r.ok) { toast(r.error); return false; }
    fly(fromEl);
    setTimeout(() => render(r.data), reduce ? 0 : 560);
    toast(r.data.notes && r.data.notes.length ? r.data.notes[r.data.notes.length - 1]
                                               : `Added ${r.data.added} kg of ${name} to your cart.`);
    document.dispatchEvent(new CustomEvent("soko:cart-changed"));
    return true;
  }

  window.SokoCart = { add };
  drawer.addEventListener("show.bs.offcanvas", load);
})();
