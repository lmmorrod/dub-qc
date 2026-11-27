/* Dub QC showcase motion. Plain JS + Lenis. Everything degrades to a static page
   without JS, and switches off for people who prefer reduced motion. */
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];

  /* ---- Smooth scroll root (Lenis), and anchor links that use it ---- */
  let lenis = null;
  if (!reduce && window.Lenis) {
    lenis = new Lenis({ lerp: 0.1, smoothWheel: true });
    const raf = (t) => { lenis.raf(t); requestAnimationFrame(raf); };
    requestAnimationFrame(raf);
  }
  $$('a[href^="#"]').forEach((a) => a.addEventListener("click", (e) => {
    const id = a.getAttribute("href");
    const target = id === "#top" ? document.body : document.querySelector(id);
    if (!target) return;
    e.preventDefault();
    if (lenis) lenis.scrollTo(id === "#top" ? 0 : target, { offset: -90, duration: 1.2 });
    else (id === "#top" ? window.scrollTo(0, 0) : target.scrollIntoView());
  }));

  /* ---- Word-stagger headings: wrap each word, keep <em> accents ---- */
  $$("[data-split]").forEach((el) => {
    let i = 0;
    const wrapWords = (text, tag) => text.split(/(\s+)/).map((part) => {
      if (!part.trim()) return part;
      const inner = tag ? `<${tag}>${part}</${tag}>` : part;
      return `<span class="w"><span style="transition-delay:${(i++ * 0.04).toFixed(2)}s">${inner}</span></span>`;
    }).join("");
    el.innerHTML = [...el.childNodes].map((n) =>
      n.nodeType === 3 ? wrapWords(n.textContent) : wrapWords(n.textContent, n.tagName.toLowerCase())).join("");
  });

  /* ---- Reveal once, 20% into the viewport ---- */
  $$(".manifest span").forEach((s, i) => s.style.setProperty("--i", i));
  const io = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (!e.isIntersecting) return;
    e.target.classList.add("in");
    io.unobserve(e.target);
    if (e.target.querySelector("[data-count]")) countUp(e.target.querySelector("[data-count]"));
  }), { rootMargin: "0px 0px -20% 0px" });
  $$("[data-reveal], [data-split]").forEach((el) => io.observe(el));

  /* ---- Count-up numbers ---- */
  function countUp(el) {
    const end = +el.dataset.count;
    if (reduce) return;
    const t0 = performance.now(), dur = 1200;
    const step = (t) => {
      const p = Math.min(1, (t - t0) / dur);
      el.textContent = Math.round(end * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* ---- Waveforms for the bento widgets (deterministic, so every visit looks the same) ---- */
  let seed = 7;
  const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  $$("[data-wave]").forEach((svg) => {
    const music = svg.dataset.wave === "music";
    const n = 120, w = 600 / n, rects = [];
    for (let k = 0; k < n; k++) {
      let h;
      if (music) h = 0.45 + 0.2 * Math.sin(k / 9) + 0.1 * rnd();                  // smooth chord bed
      else {
        const inLine = (k % 30) > 4 && (k % 30) < 26;                              // lines with gaps
        h = inLine ? (0.25 + 0.55 * Math.abs(Math.sin(k * 0.9)) * (0.6 + 0.4 * rnd())) : 0.04;
      }
      if (music && k > 52 && k < 72) h += 0.25 * Math.abs(Math.sin(k * 1.4));      // the walla
      const hh = Math.min(1, h) * 100;
      rects.push(`<rect x="${(k * w + 1).toFixed(1)}" y="${(60 - hh / 2).toFixed(1)}" width="${(w - 2).toFixed(1)}" height="${hh.toFixed(1)}" rx="1.5"/>`);
    }
    svg.innerHTML = rects.join("");
  });

  /* ---- Bar chart: one bar is "active", cycling every 3 s ---- */
  $$("[data-bars]").forEach((chart) => {
    const bars = $$(".bar", chart);
    let k = 0;
    const tick = () => { bars.forEach((b, j) => b.classList.toggle("active", j === k)); k = (k + 1) % bars.length; };
    tick();
    if (!reduce) setInterval(tick, 3000);
  });

  /* ---- Duplicate the marquee + notes tracks so they loop seamlessly ---- */
  $$("[data-marquee]").forEach((t) => { t.innerHTML += t.innerHTML; });

  /* ---- Magnetic buttons (desktop pointers only) ---- */
  if (!reduce && matchMedia("(hover: hover) and (min-width: 769px)").matches) {
    $$(".magnetic").forEach((b) => {
      b.addEventListener("pointermove", (e) => {
        const r = b.getBoundingClientRect();
        b.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * 0.15}px, ${(e.clientY - r.top - r.height / 2) * 0.15}px)`;
      });
      b.addEventListener("pointerleave", () => { b.style.transform = ""; });
    });
  }

  /* ---- Copy button ---- */
  $$("[data-copy]").forEach((btn) => btn.addEventListener("click", async () => {
    const text = document.querySelector(btn.dataset.copy).innerText.split("\n").filter((l) => !l.startsWith("#")).join("\n");
    try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; } catch { btn.textContent = "Select to copy"; }
    setTimeout(() => (btn.textContent = "Copy"), 1600);
  }));

  /* ---- Scroll-driven: tilt-flatten billboard + reading word-fill ---- */
  const billboard = document.querySelector("[data-tilt]");
  const fill = document.querySelector("[data-fill]");
  let words = [];
  if (fill) {
    fill.innerHTML = fill.textContent.trim().split(/\s+/).map((w) => `<span class="fw">${w}</span>`).join(" ");
    words = $$(".fw", fill);
  }
  const clamp = (v) => Math.max(0, Math.min(1, v));
  function onScroll() {
    const vh = innerHeight;
    if (billboard && !reduce) {
      const r = billboard.getBoundingClientRect();
      const p = clamp(1 - (r.top - vh * 0.15) / (vh * 0.7));     // 0 when low in view, 1 near the top
      billboard.style.setProperty("--rx", `${(18 * (1 - p)).toFixed(2)}deg`);
      billboard.style.setProperty("--sc", (1.04 - 0.04 * p).toFixed(4));
    }
    if (words.length && !reduce) {
      const r = fill.getBoundingClientRect();
      const p = clamp((vh * 0.8 - r.top) / (vh * 0.6 + r.height * 0.4));
      const n = words.length;
      words.forEach((w, i) => w.style.setProperty("--o", (0.15 + 0.85 * clamp(p * n - i)).toFixed(3)));
    }
  }
  if (lenis) lenis.on("scroll", onScroll); else addEventListener("scroll", onScroll, { passive: true });
  addEventListener("resize", onScroll);
  onScroll();

  /* ---- Footer: auto-fit wordmark + reveal-from-behind height ---- */
  const wordmark = document.querySelector("[data-autofit]");
  const footer = document.querySelector("[data-footer]");
  const footerWrap = document.querySelector("[data-footer-wrap]");
  function fitFooter() {
    if (wordmark) {
      const box = wordmark.parentElement.clientWidth;
      const ctx = document.createElement("canvas").getContext("2d");
      ctx.font = `700 100px "Inter Tight", sans-serif`;
      const width = ctx.measureText(wordmark.textContent).width * 0.955;       // letter-spacing -0.045em
      wordmark.style.fontSize = `${Math.floor((box / width) * 100)}px`;
    }
    if (footer && footerWrap) footerWrap.style.height = `${footer.offsetHeight}px`;
  }
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(fitFooter);
  new ResizeObserver(fitFooter).observe(document.body);
})();
