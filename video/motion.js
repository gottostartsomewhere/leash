// The animation vocabulary, shared by the title cards and the callout layer.
//
// Everything is a pure function of progress 0..1 so a frame can be painted
// from a timestamp alone. The callout layer is captured frame by frame and
// cannot rely on wall-clock CSS animations; the cards run in real time but
// use the same primitives so the two never look like different films.

// Wrapped so nothing but window.Motion reaches the global scope: these
// pages are classic scripts sharing one scope, and a bare `const ease`
// here collides with the same name in the page.
(function () {
  const ease = {
    // Decelerate. The default for anything arriving.
    out: (p) => 1 - Math.pow(1 - p, 3),
    // Hard out, for things that should feel like they land.
    hard: (p) => 1 - Math.pow(1 - p, 5),
    inOut: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    // Slight overshoot, for a stamp or a number resolving.
    back: (p) => {
      const c = 1.70158 + 1;
      return 1 + c * Math.pow(p - 1, 3) + 1.70158 * Math.pow(p - 1, 2);
    },
  };

  const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));

  /** Progress of a cue that starts at `start` and lasts `dur`. */
  const cue = (t, start, dur = 0.5, fn = ease.out) =>
    fn(clamp((t - start) / dur));

  /** Split an element's text into spans so letters can move independently.
   *  Idempotent: safe to call every frame. */
  function letters(node) {
    if (node.dataset.split) return [...node.querySelectorAll("i")];
    const text = node.textContent;
    node.textContent = "";
    for (const ch of text) {
      const i = document.createElement("i");
      i.textContent = ch === " " ? " " : ch;
      i.style.display = "inline-block";
      // <i> is italic in the browser's own stylesheet, so every piece of
      // text that arrived through kinetic() has been rendering oblique:
      // the wordmark, the end card, both punch lines. Nothing asked for
      // that. Inherit rather than force upright, so a parent that really
      // is italic still gets its way.
      i.style.fontStyle = "inherit";
      i.style.willChange = "transform, opacity, filter";
      node.appendChild(i);
    }
    node.dataset.split = "1";
    return [...node.querySelectorAll("i")];
  }

  /** Per-character arrival. Each letter lands slightly after the one before,
   *  which reads as handwriting rather than as a machine printing. */
  function kinetic(node, t, start, { gap = 0.018, dur = 0.42, rise = 26 } = {}) {
    const chars = letters(node);
    node.style.opacity = 1;
    chars.forEach((c, i) => {
      const p = cue(t, start + i * gap, dur, ease.hard);
      c.style.opacity = p;
      c.style.transform = `translateY(${(1 - p) * rise}px) scale(${0.86 + 0.14 * p})`;
      c.style.filter = p < 1 ? `blur(${(1 - p) * 9}px)` : "none";
    });
  }

  /** Revealed by a moving edge rather than faded in. The text is already
   *  there; the mask is what moves. */
  function wipe(node, p, from = "left") {
    const pct = (1 - p) * 100;
    const inset =
      from === "left" ? `0 ${pct}% 0 0` : from === "right" ? `0 0 0 ${pct}%` : `${pct}% 0 0 0`;
    node.style.clipPath = `inset(${inset})`;
    node.style.opacity = p > 0 ? 1 : 0;
  }

  /** Starts wide and tightens as it lands. Cheap, and it reads as confident. */
  function tighten(node, p, fromEm = 0.34) {
    node.style.letterSpacing = `${(1 - p) * fromEm}em`;
    node.style.opacity = p;
  }

  /** Recede rather than merely dim, so earlier lines feel pushed back. */
  function recede(node, p, { scale = 0.96, dim = "#4a443e" } = {}) {
    node.style.transform = `scale(${1 - (1 - scale) * p})`;
    node.style.color = p > 0.5 ? dim : "";
    node.style.opacity = 1 - 0.45 * p;
  }

  /** Odometer roll. Digits move, which makes a number feel counted rather
   *  than typed. */
  function roll(node, to, p, { decimals = 2, grouping = true } = {}) {
    const value = to * ease.out(p);
    const fixed = value.toFixed(decimals);
    node.textContent = grouping
      ? fixed.replace(/\B(?=(\d{3})+(?!\.))/g, ",")
      : fixed;
  }

  /** Draw an SVG path by its own length. */
  function drawPath(path, p) {
    const len = path.getTotalLength();
    path.style.strokeDasharray = len;
    path.style.strokeDashoffset = len * (1 - p);
  }

  /** A band of light crossing an element, for pointing at a row without
   *  drawing a box around it. */
  function sweep(node, p) {
    if (p <= 0 || p >= 1) {
      node.style.opacity = 0;
      return;
    }
    node.style.opacity = 1;
    node.style.transform = `translateX(${-120 + 340 * p}%)`;
  }

  // Classic script rather than a module: the recorder loads these pages from
  // file://, where module imports are blocked by CORS.
  window.Motion = {
    ease, clamp, cue, letters, kinetic, wipe, tighten, recede, roll, drawPath, sweep,
  };
})();
