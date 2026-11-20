/* Soko Digital – "wow" motion: scroll-driven journey, 3D tilt, cursor glow, word reveals */
(function () {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const root = document.documentElement;

  // Split headings into words for the staggered reveal
  document.querySelectorAll(".split").forEach(h => {
    h.innerHTML = h.textContent.trim().split(/\s+/).map((w, i) => `<span class="w" style="--wi:${i}">${w}</span>`).join(" ");
  });
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.4 });
  document.querySelectorAll(".split").forEach(el => io.observe(el));

  // Scroll progress bar + the journey scene (driven by scroll position)
  const journey = document.getElementById("journey");
  const slides = journey ? [...journey.querySelectorAll(".j-slide")] : [];
  const crates = journey ? [...journey.querySelectorAll(".crate")] : [];
  const truck = journey ? journey.querySelector(".truck") : null;
  const marks = [0, 0.25, 0.55, 0.85];

  function frame() {
    const max = document.body.scrollHeight - innerHeight;
    root.style.setProperty("--prog", max > 0 ? clamp(scrollY / max, 0, 1).toFixed(4) : 0);
    if (!journey || reduce) return;
    const r = journey.getBoundingClientRect();
    const p = clamp(-r.top / (journey.offsetHeight - innerHeight), 0, 1);
    journey.style.setProperty("--p", p.toFixed(4));
    const t = truck.getBoundingClientRect();
    const truckMid = t.left + t.width * 0.55;
    crates.forEach(c => c.classList.toggle("open", truckMid > c.getBoundingClientRect().left + 20 && p > 0));
    let idx = 0;
    marks.forEach((m, i) => { if (p >= m) idx = i; });
    slides.forEach((s, i) => s.classList.toggle("on", i === idx));
  }
  let ticking = false;
  addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(() => { frame(); ticking = false; }); } }, { passive: true });
  addEventListener("resize", frame);
  frame();
  if (reduce) return;

  // 3D tilt + shine on listing cards
  const grid = document.getElementById("listings");
  if (grid) {
    grid.addEventListener("pointermove", e => {
      const card = e.target.closest(".listing");
      if (!card) return;
      const r = card.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      card.style.setProperty("--ry", ((x - 0.5) * 10).toFixed(2) + "deg");
      card.style.setProperty("--rx", ((0.5 - y) * 8).toFixed(2) + "deg");
      card.style.setProperty("--gx", (x * 100).toFixed(1) + "%");
      card.style.setProperty("--gy", (y * 100).toFixed(1) + "%");
    });
    grid.addEventListener("pointerout", e => {
      const card = e.target.closest(".listing");
      if (card && !card.contains(e.relatedTarget)) { card.style.setProperty("--rx", "0deg"); card.style.setProperty("--ry", "0deg"); }
    });
  }

  // Cursor glow + magnetic buttons in the hero
  const hero = document.querySelector(".hero");
  if (hero) {
    hero.addEventListener("pointermove", e => {
      const r = hero.getBoundingClientRect();
      hero.style.setProperty("--mx", (e.clientX - r.left) + "px");
      hero.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
    hero.querySelectorAll(".btn").forEach(b => {
      b.addEventListener("pointermove", e => {
        const r = b.getBoundingClientRect();
        b.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * 0.18}px, ${(e.clientY - r.top - r.height / 2) * 0.3}px)`;
      });
      b.addEventListener("pointerleave", () => { b.style.transform = ""; });
    });
  }
})();
