// The flow, as a timeline.
//
// `render(t)` paints the whole stage from elapsed seconds and nothing else.
// Every element's style is written on every frame rather than accumulated,
// because the recorder steps frames out of order and a property set once at
// t=3 must not still be sitting there at t=30.
//
// Four acts, about thirty-seven seconds:
//
//   1  a goal in words, an agent, a catalogue, a shelf of real-looking things
//   2  it picks the 150 one, and the track stops it at the per-item gate
//   3  told what would clear, it comes back with 88 and goes all the way
//   4  two charges of 75 to one merchant, each fine alone, caught together
//
// Then the cut to live footage, so the animation reads as a promise the
// demo keeps.

(function () {
  const { ease, clamp, cue, wipe, roll, drawPath } = window.Motion;

  /* -- geometry -----------------------------------------------------------
   * One place, because every act is measured against the same track and a
   * layout argued across two files is a layout that drifts. */

  const TRACK_Y = 585;
  const TRACK_X0 = 215;
  const TRACK_X1 = 1690;

  const GATE_X0 = 580;
  const GATE_GAP = 88;
  const GATES = 11;
  const gateX = (i) => GATE_X0 + i * GATE_GAP;

  const PER_ITEM = 5; // refuses the 150 on its own
  const CLUSTER = 8; // refuses the pair, together

  const SHELF_Y = 160;
  const CARD_W = 250;
  const CARD_GAP = 26;
  const SHELF_RIGHT = 1700;

  const PAIR_HI = 465;
  const PAIR_LO = 650;

  const $ = (id) => document.getElementById(id);
  const stage = $("stage");

  // Nodes are placed from here too, so the markup carries no geometry.
  function box(el, left, top, w, h) {
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    el.style.width = `${w}px`;
    el.style.height = `${h}px`;
  }
  box($("agent"), 70, TRACK_Y - 62, 125, 125);
  box($("cat"), 1560, 44, 160, 96);
  box($("pay"), 1700, TRACK_Y - 65, 165, 130);
  $("track").setAttribute("d", `M ${TRACK_X0} ${TRACK_Y} L ${TRACK_X1} ${TRACK_Y}`);

  /* -- the shelves --------------------------------------------------------
   * Clean numbers on purpose. Not a capture of a real run: the smallest set
   * of values that makes the rule legible at speed. 150 over a 100 cap, 88
   * under it, and 75 + 75 landing exactly back on the 150 that was refused
   * in the first place. */

  const SHELF_A = [
    { t: "Task chair, adjustable", p: "150.00", d: "acme.com" },
    { t: "Task chair, mesh back", p: "210.00", d: "acme.com" },
    { t: "Executive chair", p: "340.00", d: "globex.com" },
    { t: "Drafting stool", p: "95.00", d: "northwind.com" },
    { t: "Lounge chair", p: "480.00", d: "globex.com" },
  ];

  const SHELF_B = [
    { t: "Task chair, fixed arms", p: "88.00", d: "acme.com" },
    { t: "Task chair, basic", p: "74.00", d: "initech.com" },
    { t: "Drafting stool", p: "95.00", d: "northwind.com" },
  ];

  function buildShelf(items) {
    const total = items.length * CARD_W + (items.length - 1) * CARD_GAP;
    const x0 = SHELF_RIGHT - total;
    return items.map((it, i) => {
      const el = document.createElement("div");
      el.className = "card";
      el.style.left = `${x0 + i * (CARD_W + CARD_GAP)}px`;
      el.style.top = `${SHELF_Y}px`;
      el.innerHTML =
        `<div class="t">${it.t}</div>` +
        `<div class="p">${it.p}</div>` +
        `<div class="d">${it.d}</div>`;
      return el;
    });
  }

  const shelfHost = $("shelf");
  const cardsA = buildShelf(SHELF_A);
  const cardsB = buildShelf(SHELF_B);
  [...cardsA, ...cardsB].forEach((c) => shelfHost.appendChild(c));

  /* -- the gates, and the same eleven written out ------------------------- */

  // Ordered so the gate that refuses is the check that refuses: index five
  // is the per-item cap, index eight is structuring.
  const CHECKS = [
    "mandate_inactive",
    "currency_mismatch",
    "outside_window",
    "payee_not_allowed",
    "category_not_allowed",
    "per_item_limit",
    "per_payee_limit",
    "insufficient_budget",
    "structuring",
    "velocity",
    "concentration",
  ];

  const gatesHost = $("gates");
  const gates = [];
  for (let i = 0; i < GATES; i += 1) {
    const g = document.createElement("div");
    g.className = "gate";
    g.style.left = `${gateX(i) - 1}px`;
    g.style.top = `${TRACK_Y - 35}px`;
    g.style.height = "70px";
    g.innerHTML = "<i></i>";
    gatesHost.appendChild(g);
    gates.push(g);
  }

  const checksHost = $("checks");
  checksHost.style.left = "300px";
  checksHost.style.top = "742px";
  const rows = CHECKS.map((name) => {
    const el = document.createElement("div");
    el.className = "chk";
    el.innerHTML = `<u></u><span>${name}</span>`;
    checksHost.appendChild(el);
    return el;
  });

  /* -- the tokens ---------------------------------------------------------- */

  function buildToken(id, to) {
    const el = document.createElement("div");
    el.className = "token";
    el.id = id;
    el.innerHTML =
      `<span class="amt"><span class="n">0.00</span><i class="strike"></i></span>` +
      `<span class="to">${to}</span>`;
    stage.appendChild(el);
    return el;
  }

  const t1 = buildToken("t1", "acme.com"); // the 150, refused
  const t2 = buildToken("t2", "acme.com"); // the 88, cleared
  const t3 = buildToken("t3", "acme_us"); // the split, upper
  const t4 = buildToken("t4", "acme_eu"); // the split, lower

  const amtOf = (el) => el.querySelector(".n");
  const strikeOf = (el) => el.querySelector(".strike");
  const toOf = (el) => el.querySelector(".to");

  // Read once, after the fonts land. Every token carries a fixed-width
  // amount so none of them ever changes size afterwards.
  let TOKW = 300;

  /* -- travel --------------------------------------------------------------
   * Gate crossings are solved, not guessed: a gate lights at the exact
   * moment the token's leading edge reaches it. That is the difference
   * between the track reading as a mechanism and as decoration. */

  function invert(fn, y) {
    let lo = 0;
    let hi = 1;
    for (let i = 0; i < 28; i += 1) {
      const mid = (lo + hi) / 2;
      if (fn(mid) < y) lo = mid;
      else hi = mid;
    }
    return (lo + hi) / 2;
  }

  function leg(from, to, t0, t1, fn = ease.inOut) {
    return {
      from,
      to,
      t0,
      t1,
      at(t) {
        return from + (to - from) * fn(clamp((t - t0) / (t1 - t0)));
      },
      crosses(x) {
        const want = x - TOKW;
        if (want <= from) return t0;
        if (want >= to) return null;
        const p = invert(fn, (want - from) / (to - from));
        return t0 + p * (t1 - t0);
      },
    };
  }

  const START = 212;
  let L1, L2, L3, L4;

  function buildLegs() {
    L1 = leg(START, gateX(PER_ITEM) - TOKW, 9.6, 12.4);
    L2 = leg(gateX(PER_ITEM) - TOKW, 60, 16.6, 17.5, ease.hard);
    L3 = leg(START, TRACK_X1 - TOKW, 21.6, 24.4);
    L4 = leg(START, gateX(CLUSTER) - TOKW - 46, 28.0, 29.8);
  }
  buildLegs();

  /* -- helpers -------------------------------------------------------------- */

  function node(el, p) {
    el.style.opacity = p;
    el.style.transform = `scale(${0.86 + 0.14 * p})`;
  }

  /** A short flash that decays, for an impact or a gate being passed. */
  const flash = (t, at, up = 0.14, down = 0.42) =>
    cue(t, at, up, ease.hard) * (1 - cue(t, at + up, down));

  /** Damped recoil after hitting something immovable. */
  function recoil(t, at, amount = 15, dur = 0.5) {
    const p = clamp((t - at) / dur);
    if (p <= 0 || p >= 1) return 0;
    return Math.sin(p * Math.PI * 3) * amount * (1 - p) * (1 - p);
  }

  const GREEN = "#7fa37a";
  const RED = "#e2553d";
  const IDLE = "#4a443e";

  function shelf(cards, t, { arrive, pickAt, leave, pick = 0 }) {
    cards.forEach((c, i) => {
      const inP = cue(t, arrive + i * 0.11, 0.55, ease.hard);
      const out = cue(t, leave + i * 0.05, 0.5, ease.hard);
      const chosen = i === pick;
      const narrow = cue(t, pickAt, 0.65, ease.hard);
      const dim = chosen ? 0 : narrow;
      c.style.opacity = inP * (1 - 0.74 * dim) * (1 - out);
      c.style.transform =
        `translate(${(1 - inP) * 96 + out * 64}px, ${-(1 - inP) * 12}px) ` +
        `scale(${(0.97 + 0.03 * inP) * (1 - 0.05 * dim)})`;
      c.classList.toggle("on", chosen && narrow > 0.35 && out < 0.1);
    });
  }

  /* -- the timeline ---------------------------------------------------------- */

  const DURATION = 37;

  function render(t) {
    /* ---- the track and its gates --------------------------------------- */

    drawPath($("track"), cue(t, 0.0, 1.0, ease.inOut));

    let active = null;
    let blockAt = -1;
    if (t >= 9.4 && t < 17.8) {
      active = L1;
      blockAt = PER_ITEM;
    } else if (t >= 21.4 && t < 27.6) {
      active = L3;
    } else if (t >= 27.8) {
      active = L4;
      blockAt = CLUSTER;
    }

    const failAt = blockAt === PER_ITEM ? 12.42 : blockAt === CLUSTER ? 32.4 : null;

    gates.forEach((g, i) => {
      const born = cue(t, 0.8 + i * 0.035, 0.4, ease.back);
      g.style.opacity = born * 0.9;
      g.style.transform = `scaleY(${0.3 + 0.7 * born})`;

      const tick = g.firstElementChild;
      let lit = 0;
      let pop = 0;
      if (active && i !== blockAt) {
        const when = active.crosses(gateX(i));
        if (when !== null && t >= when) {
          lit = 1;
          pop = flash(t, when, 0.1, 0.5);
        }
      }
      tick.style.background = GREEN;
      tick.style.opacity = lit ? 0.5 + 0.5 * pop : 0;
      tick.style.transform = `scaleY(${1 + 0.55 * pop}) scaleX(${1 + 2.4 * pop})`;
    });

    // The same eleven, named. Appears with the first run and leaves before
    // act four needs the floor.
    {
      // Up early, with the track. These are the terms, and terms that only
      // appear once something is already moving read as a reaction rather
      // than as the thing that was agreed first.
      const p = cue(t, 2.6, 0.8, ease.hard) * (1 - cue(t, 27.5, 0.6, ease.hard));
      checksHost.style.opacity = p;
      rows.forEach((row, i) => {
        const born = cue(t, 2.7 + i * 0.05, 0.45, ease.hard);
        row.style.opacity = born;
        row.style.transform = `translateX(${(1 - born) * -14}px)`;

        let colour = IDLE;
        let filled = false;
        if (active && i === blockAt && failAt !== null && t >= failAt) {
          colour = RED;
          filled = true;
        } else if (active && i !== blockAt) {
          const when = active.crosses(gateX(i));
          if (when !== null && t >= when) {
            colour = GREEN;
            filled = true;
          }
        }
        row.style.color = colour;
        const dot = row.firstElementChild;
        dot.style.borderColor = colour;
        dot.style.background = filled ? colour : "transparent";
      });
    }

    /* ---- act one: the ask ----------------------------------------------- */

    node($("agent"), cue(t, 1.4, 0.6, ease.back));
    wipe($("agent-cap"), cue(t, 2.0, 0.5, ease.hard));

    const goalP = cue(t, 2.3, 0.6, ease.hard);
    const goal = $("goal");
    goal.style.opacity = goalP;
    goal.style.left = "58px";
    goal.style.top = `${TRACK_Y - 168 - 14 * goalP}px`;

    $("feed").setAttribute("d", `M 132 ${TRACK_Y - 62} C 132 290, 820 92, 1556 92`);
    drawPath($("feed"), cue(t, 3.0, 1.0, ease.inOut));

    node($("cat"), cue(t, 3.7, 0.55, ease.back));
    wipe($("cat-cap"), cue(t, 4.1, 0.5, ease.hard));

    shelf(cardsA, t, { arrive: 4.5, pickAt: 7.4, leave: 17.2, pick: 0 });

    /* ---- act two: the wall ---------------------------------------------- */

    {
      const born = cue(t, 8.6, 0.6, ease.back);
      const gone = cue(t, 17.1, 0.4, ease.hard);
      const x = (t > 16.5 ? L2.at(t) : L1.at(t)) + recoil(t, 12.4);
      t1.style.opacity = born * (1 - gone);
      t1.style.top = `${TRACK_Y - 38}px`;
      t1.style.transform = `translateX(${x}px)`;
      roll(amtOf(t1), 150, cue(t, 8.8, 0.8), { decimals: 2, grouping: false });
      strikeOf(t1).style.width = `${cue(t, 13.6, 0.5, ease.hard) * 166}px`;
      t1.classList.toggle("bad", t >= 12.45);
    }

    // The wall rises out of the track rather than appearing beside it, so
    // the track itself is what refuses.
    {
      const wall = $("wall");
      const act4 = t >= 27.8;
      const at = act4 ? gateX(CLUSTER) : gateX(PER_ITEM);
      const up = act4
        ? cue(t, 32.3, 0.34, ease.back) * (1 - cue(t, 36.4, 0.4))
        : cue(t, 12.3, 0.3, ease.back) * (1 - cue(t, 17.0, 0.4, ease.hard));
      wall.style.left = `${at - 3}px`;
      wall.style.top = `${TRACK_Y - 90}px`;
      wall.style.height = "180px";
      wall.style.opacity = up;
      wall.style.transform = `scaleY(${up})`;

      const ring = $("ring");
      const hit = act4 ? 32.4 : 12.42;
      const rp = clamp((t - hit) / 0.62);
      const live = rp > 0 && rp < 1;
      const r = 26 + 150 * ease.out(rp);
      ring.style.width = `${r * 2}px`;
      ring.style.height = `${r * 2}px`;
      ring.style.left = `${at - r}px`;
      ring.style.top = `${TRACK_Y - r}px`;
      ring.style.opacity = live ? (1 - rp) * 0.9 : 0;
      ring.style.transform = "none";
    }

    {
      const lab = $("glabel");
      const p = cue(t, 12.9, 0.4, ease.back) * (1 - cue(t, 16.9, 0.35, ease.hard));
      lab.style.left = `${gateX(PER_ITEM) - 92}px`;
      lab.style.top = `${TRACK_Y + 72}px`;
      lab.style.opacity = p;
      lab.style.transform = `translateY(${(1 - p) * -14}px) scale(${0.9 + 0.1 * p})`;
    }

    {
      const c = $("counter");
      const p = cue(t, 14.4, 0.5, ease.back) * (1 - cue(t, 19.4, 0.45, ease.hard));
      c.style.left = `${gateX(PER_ITEM) - 124}px`;
      c.style.top = `${TRACK_Y - 186 + (1 - p) * -16}px`;
      c.style.opacity = p;
    }

    /* ---- act three: all the way through --------------------------------- */

    shelf(cardsB, t, { arrive: 18.9, pickAt: 20.1, leave: 25.6, pick: 0 });

    {
      const born = cue(t, 20.9, 0.5, ease.back);
      const gone = cue(t, 25.7, 0.5, ease.hard);
      t2.style.opacity = born * (1 - gone);
      t2.style.top = `${TRACK_Y - 38}px`;
      t2.style.transform =
        `translate(${L3.at(t)}px, ${gone * 170}px) scale(${1 - 0.16 * gone})`;
      t2.classList.add("ok");
      roll(amtOf(t2), 88, cue(t, 21.1, 0.7), { decimals: 2, grouping: false });
    }

    {
      const pay = $("pay");
      node(pay, cue(t, 4.4, 0.55, ease.back));
      const fill = cue(t, 24.3, 0.45, ease.hard) * (1 - cue(t, 27.4, 0.5));
      const on = fill > 0.2;
      pay.style.borderColor = on ? GREEN : "#2b2622";
      pay.style.background = on
        ? "color-mix(in srgb, #7fa37a 15%, #121010)"
        : "#121010";
      pay.querySelector(".mark").style.color = on ? GREEN : "#9d958c";
      const cap = $("pay-cap");
      cap.textContent = fill > 0.45 ? "settled" : "payouts";
      wipe(cap, cue(t, 4.9, 0.5, ease.hard));
    }

    {
      const row = $("row");
      const p = cue(t, 25.9, 0.55, ease.back);
      const out = cue(t, 27.6, 0.5, ease.hard);
      row.style.left = "300px";
      row.style.top = "958px";
      row.style.width = "1380px";
      row.style.opacity = p * (1 - out);
      row.style.transform = `translateY(${(1 - p) * 28 + out * 20}px)`;
      $("row-amt").textContent = "88.00";
    }

    /* ---- act four: two that are fine alone ------------------------------ */

    {
      const born = cue(t, 28.0, 0.45, ease.back);
      const gone = cue(t, 36.3, 0.5, ease.hard);
      const x = L4.at(t) + recoil(t, 32.4, 11, 0.55);
      const bad = t >= 32.5;

      [t3, t4].forEach((el, i) => {
        el.style.opacity = born * (1 - gone);
        el.style.top = `${i === 0 ? PAIR_HI : PAIR_LO}px`;
        el.style.transform = `translateX(${x}px)`;
        el.classList.toggle("bad", bad);
        roll(amtOf(el), 75, cue(t, 28.2, 0.6), { decimals: 2, grouping: false });
      });

      // Both addresses resolve to one merchant, which is the only reason the
      // pair is a cluster at all.
      const resolved = cue(t, 30.6, 0.5, ease.hard) > 0.5;
      toOf(t3).textContent = resolved ? "acme_us → acme" : "acme_us";
      toOf(t4).textContent = resolved ? "acme_eu → acme" : "acme_eu";
      toOf(t3).style.color = resolved ? "#dfa33c" : "#6a635c";
      toOf(t4).style.color = resolved ? "#dfa33c" : "#6a635c";

      const bx = x - 32;
      const br = $("bracket");
      br.setAttribute(
        "d",
        `M ${x + 10} ${PAIR_HI + 42} L ${bx} ${PAIR_HI + 42} ` +
          `L ${bx} ${PAIR_LO + 42} L ${x + 10} ${PAIR_LO + 42}`,
      );
      drawPath(br, cue(t, 29.9, 0.8, ease.hard));
      br.style.opacity = born * (1 - gone);

      const sum = $("sum");
      const sp = cue(t, 31.4, 0.55, ease.hard) * (1 - gone);
      sum.style.left = `${x}px`;
      sum.style.top = "772px";
      wipe(sum, sp);
      // The total stays away until it is counted, otherwise the line reads
      // "75 + 75 = 0" for half a second and looks broken.
      $("sum-t").style.opacity = cue(t, 31.95, 0.2);
      roll($("sum-t"), 150, cue(t, 31.95, 0.5), { decimals: 0, grouping: false });

      const stamp = $("stamp");
      const st = cue(t, 33.2, 0.5, ease.back) * (1 - cue(t, 36.5, 0.4));
      stamp.style.left = `${x - 20}px`;
      stamp.style.top = "866px";
      stamp.style.opacity = st;
      stamp.style.transform = `scale(${0.76 + 0.24 * st}) rotate(${(1 - st) * -3}deg)`;
    }

    /* ---- the stack that did it ------------------------------------------ */

    wipe($("credits"), cue(t, 35.3, 1.0, ease.hard));

    // Anything belonging to an act that has not started is off, not merely
    // left wherever the previous frame put it.
    if (t < 8.5) t1.style.opacity = 0;
    if (t < 20.8) t2.style.opacity = 0;
    if (t < 27.9) {
      t3.style.opacity = 0;
      t4.style.opacity = 0;
      $("bracket").style.opacity = 0;
      $("sum").style.opacity = 0;
      $("stamp").style.opacity = 0;
    }
  }

  window.flow = {
    render,
    DURATION,
    /** Called once after the webfonts land, so token widths are real. */
    measure() {
      TOKW = Math.round(t1.getBoundingClientRect().width) || 300;
      buildLegs();
      return TOKW;
    },
  };

  // Static halves of the sum; only the total is counted.
  $("sum-a").textContent = "75";
  $("sum-b").textContent = "75";

  render(0);
})();
