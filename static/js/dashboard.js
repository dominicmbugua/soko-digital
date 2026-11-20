/* Dashboard helpers: one-click API buttons, toasts, count-up numbers */
(function () {
  const token = () => document.querySelector('meta[name="csrf-token"]').content;
  const toast = (msg) => {
    const t = document.getElementById("toast");
    t.textContent = msg; t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 4500);
  };

  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-api]");
    if (!b) return;
    if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;
    const label = b.textContent;
    b.disabled = true; b.textContent = "Working…";
    try {
      const r = await fetch(b.dataset.api, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": token() },
        body: b.dataset.body || "{}"
      });
      const d = await r.json().catch(() => null);
      if (r.ok) { location.reload(); return; }
      toast((d && d.error) || "Something went wrong. Please try again.");
    } catch (_) { toast("Could not reach the server."); }
    b.disabled = false; b.textContent = label;
  });

  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.querySelectorAll("[data-count]").forEach((el) => {
      const target = Number(el.dataset.count) || 0, prefix = el.dataset.prefix || "";
      if (!target) return;
      const t0 = performance.now();
      const tick = (t) => {
        const k = Math.min(1, (t - t0) / 1000);
        el.textContent = prefix + Math.round(target * (1 - Math.pow(1 - k, 3))).toLocaleString("en-KE");
        if (k < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }
})();
