/* Soko Digital – entrance animations (WOW.js style, no dependencies).
   Add class="wow fadeInUp" (or fadeInLeft / fadeInRight / fadeIn / zoomIn) and optionally data-wow-delay="0.3s".
   Each element animates once when it scrolls into view. Scrolling itself is never touched.
   Also: first-visit loading screen and the back-to-top button. */
(function () {
  const root = document.documentElement;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const spinner = document.getElementById("spinner");
  let ready = !spinner;          // wait for the loading screen so the hero animates in view
  let io = null;

  function reveal(el) {
    const d = el.getAttribute("data-wow-delay");
    if (d) el.style.animationDelay = d;
    const t = el.getAttribute("data-wow-duration");
    if (t) el.style.animationDuration = t;
    el.classList.add("animated");
  }

  function scan() {
    if (!ready) return;
    document.querySelectorAll(".wow:not(.animated):not([data-wow-seen])").forEach((el) => {
      if (!io) { el.classList.add("animated"); return; }
      el.setAttribute("data-wow-seen", "");
      io.observe(el);
    });
  }

  if ("IntersectionObserver" in window && !reduce) {
    io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (e.isIntersecting) { reveal(e.target); io.unobserve(e.target); }
    }), { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    root.classList.add("wow-ready");
  }
  window.Wow = { refresh: scan };

  function start() {
    if (ready && !spinner) { scan(); return; }
    ready = true;
    if (spinner) { spinner.classList.add("done"); setTimeout(() => spinner.remove(), 500); }
    scan();
  }
  if (spinner) {
    try { sessionStorage.setItem("sokoSeen", "1"); } catch (_) { /* private mode */ }
    let fired = false;
    const go = () => { if (!fired) { fired = true; setTimeout(start, 250); } };
    if (document.readyState === "complete") go(); else window.addEventListener("load", go);
    setTimeout(go, 1500);        // never wait longer than this on slow connections
  } else {
    scan();
  }

  // Back to top
  const top = document.getElementById("back-to-top");
  if (top) {
    const onScroll = () => top.classList.toggle("show", window.scrollY > 500);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    top.addEventListener("click", (e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" }); });
  }
})();
