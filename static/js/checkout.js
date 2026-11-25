/* Checkout and "finish your order" pages: ask for the M-Pesa number, show the PIN prompt overlay,
   wait for the result, and the confetti on the confirmation page.

   Flow: POST /api/checkout/<id>/pay/ sends the prompt to the buyer's phone (real M-Pesa) -> we poll
   /api/checkout/<id>/status/ every few seconds -> success sends the buyer to the confirmation page. */
(function () {
  const overlay = document.getElementById("pay-overlay");
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const $ = (id) => document.getElementById(id);

  const waitingHtml = overlay ? $("pay-msg").innerHTML : "";      // "Enter your M-Pesa PIN to pay KES ..."

  function showWaiting() {
    if (!overlay) return;
    overlay.classList.remove("failed");
    $("pay-title").textContent = "Check your phone";
    $("pay-msg").innerHTML = waitingHtml;
    $("pay-actions").hidden = true;
    if ($("pay-demo")) $("pay-demo").hidden = false;
    overlay.hidden = false;
  }

  function showFailed(message) {
    overlay.classList.add("failed");
    $("pay-title").textContent = "Payment not completed";
    $("pay-msg").textContent = message;
    $("pay-actions").hidden = false;
    if ($("pay-demo")) $("pay-demo").hidden = true;
    $("pay-retry").focus();
  }

  /* Runs one payment from "send the prompt" to "paid or failed". Returns { ok, done } or { ok: false, message }. */
  async function pay(payUrl, pollUrl, phone) {
    const started = await Soko.request("POST", payUrl, { phone });
    if (!started.ok) return { ok: false, message: started.error, status: started.status };
    let d = started.data;
    if (d.simulated && d.status === "success") {            // demo mode: keep the "check your phone" moment
      await sleep(2200);
      return { ok: true, done: d.done };
    }
    const giveUp = Date.now() + 150000;
    while (d.status === "pending") {
      if (Date.now() > giveUp) {
        return { ok: false, message: "We didn't get an answer from M-Pesa. If money left your account, check your M-Pesa SMS before trying again." };
      }
      await sleep(3000);
      const r = await Soko.request("GET", pollUrl);
      if (r.ok) d = r.data;
      else if (r.status !== 0) return { ok: false, message: r.error };      // status 0 = a network blip: keep polling
    }
    return d.status === "success" || d.status === "needs_review" ? { ok: true, done: d.done } : { ok: false, message: d.message };
  }

  /* Shows the overlay, runs the payment, then either redirects or offers "Try again" / "Change number". */
  async function runWithOverlay(payUrl, pollUrl, getPhone, onChangeNumber) {
    showWaiting();
    const res = await pay(payUrl, pollUrl, getPhone());
    if (res.ok) { location.href = res.done; return; }
    showFailed(res.message);
    $("pay-retry").onclick = () => runWithOverlay(payUrl, pollUrl, getPhone, onChangeNumber);
    $("pay-close").onclick = () => { overlay.hidden = true; onChangeNumber(); };
  }

  // ---------- Checkout page ----------
  const form = document.getElementById("checkout-form");
  if (form) {
    let changed = false;
    document.addEventListener("soko:cart-changed", () => { changed = true; });
    const drawer = document.getElementById("cart-drawer");
    if (drawer) drawer.addEventListener("hidden.bs.offcanvas", () => { if (changed) location.reload(); });

    const err = $("co-error"), btn = $("co-pay"), phoneInput = $("co-phone");
    let made = null;                                        // the checkout, once created (never create it twice)

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      btn.disabled = true;
      if (!made) {
        const res = await Soko.request("POST", "/api/checkout/", {
          phone: phoneInput.value, address: $("co-address").value, note: $("co-note").value
        });
        if (!res.ok) {
          err.textContent = res.error;
          btn.disabled = false;
          if (res.status === 409) setTimeout(() => location.reload(), 2200);   // cart changed: show the fresh one
          return;
        }
        made = res.data;
      }
      const urls = { pay: `/api/checkout/${made.id}/pay/`, poll: `/api/checkout/${made.id}/status/` };
      await runWithOverlay(urls.pay, urls.poll, () => phoneInput.value,
        () => { location.href = made.done; });              // wrong number: the "finish your order" page asks for it again
    });
  }

  // ---------- "One step left" page (retry, or pay with another number) ----------
  const retry = document.getElementById("retry-form");
  if (retry) {
    const input = $("retry-phone"), rerr = $("retry-error");
    retry.addEventListener("submit", async (e) => {
      e.preventDefault();
      rerr.textContent = "";
      if (!input.value.trim()) { rerr.textContent = "Enter the M-Pesa number to pay with."; return; }
      await runWithOverlay(retry.dataset.pay, retry.dataset.poll, () => input.value, () => input.focus());
    });
  }

  const host = document.querySelector(".confetti-host");
  if (host && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const colors = ["#1f7a4a", "#7fb552", "#e3a21a", "#14382a", "#c9432c"];
    for (let i = 0; i < 30; i++) {
      const p = document.createElement("i");
      p.className = "confetti";
      p.style.cssText = `left:${Math.random() * 100}vw;background:${colors[i % colors.length]};--dx:${(Math.random() - 0.5) * 240}px;--r:${Math.random() * 720}deg;animation-delay:${Math.random() * 0.5}s;animation-duration:${2.2 + Math.random() * 1.4}s`;
      document.body.appendChild(p);
      setTimeout(() => p.remove(), 4500);
    }
  }
})();
