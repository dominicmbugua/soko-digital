/* Checkout page (submit + simulated M-Pesa prompt) and the confetti on the confirmation page. */
(function () {
  const form = document.getElementById("checkout-form");

  if (form) {
    let changed = false;
    document.addEventListener("soko:cart-changed", () => { changed = true; });
    const drawer = document.getElementById("cart-drawer");
    if (drawer) drawer.addEventListener("hidden.bs.offcanvas", () => { if (changed) location.reload(); });

    const err = document.getElementById("co-error"), btn = document.getElementById("co-pay"), overlay = document.getElementById("pay-overlay");
    const pause = (ms) => new Promise(r => setTimeout(r, ms));

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      btn.disabled = true;
      const made = await Soko.request("POST", "/api/checkout/", {
        phone: document.getElementById("co-phone").value,
        address: document.getElementById("co-address").value,
        note: document.getElementById("co-note").value
      });
      if (!made.ok) {
        err.textContent = made.error;
        btn.disabled = false;
        if (made.status === 409) setTimeout(() => location.reload(), 2200);   // cart changed: show the fresh one
        return;
      }
      overlay.hidden = false;
      await pause(2600);                                                      // the "check your phone" moment
      await Soko.request("POST", `/api/checkout/${made.data.id}/pay/`);
      location.href = made.data.done;                                         // paid, or a retry button if it failed
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
