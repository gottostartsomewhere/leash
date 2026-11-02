import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { money, withCurrency } from "./format";
import { DecisionGrid } from "./grid/DecisionGrid";
import { failuresOf, worstOf } from "./grid/renderers";
import { Authority } from "./panels/Authority";
import { AskConsole, type AskResult } from "./panels/AskConsole";
import { ShopPanel } from "./panels/ShopPanel";
import { SCENARIO } from "./scenario";
import type {
  Charge,
  DecisionRow,
  GridRow,
  Health,
  LogRow,
  MandateSummary,
  Payee,
  ShopStep,
} from "./types";

const MANDATE_ID = "mnd_demo";
const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));

/** A tether with slack in it, anchored at one end. */
function Mark() {
  return (
    <svg width="27" height="15" viewBox="0 0 27 15" aria-hidden="true">
      <circle cx="2.6" cy="3" r="2.6" fill="currentColor" />
      <path
        d="M2.6 3 C 6 13.6, 16.5 13.6, 23.4 5.8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <circle cx="23.6" cy="5.6" r="2.3" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export default function App() {
  const [mandate, setMandate] = useState<MandateSummary | null>(null);
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [charges, setCharges] = useState<Charge[]>([]);
  const [payees, setPayees] = useState<Payee[]>([]);
  const [health, setHealth] = useState<Health | null>(null);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string[]>([]);
  const [onlyRefusals, setOnlyRefusals] = useState(false);
  const [query, setQuery] = useState("");
  const [console_, setConsole] = useState<"ask" | "shop">("ask");

  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState("");
  const [lastAsk, setLastAsk] = useState<AskResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);

  const seen = useRef(0);
  const cancelled = useRef(false);

  const say = useCallback((problem: unknown) => {
    setError(
      problem instanceof ApiError
        ? problem.message
        : problem instanceof Error
          ? problem.message
          : String(problem),
    );
  }, []);

  /** Pull the whole picture. Cheap enough to do after every action, and it
   *  means the screen is never a guess about what the engine thinks. */
  const refresh = useCallback(async () => {
    const [nextMandate, nextDecisions, nextCharges] = await Promise.all([
      api.mandate(MANDATE_ID),
      api.decisions(MANDATE_ID),
      api.charges(MANDATE_ID),
    ]);

    // Anything that got caught structuring opens itself. It is the one row a
    // person has to actually look at, so it should not need a click.
    const fresh = nextDecisions.slice(seen.current);
    const toOpen = fresh
      .filter((d) => d.failed_codes.includes("structuring"))
      .map((d) => d.attempt_id);
    seen.current = nextDecisions.length;

    setMandate(nextMandate);
    setDecisions(nextDecisions);
    setCharges(nextCharges);
    if (toOpen.length) {
      setExpanded((open) => new Set([...open, ...toOpen]));
    }
  }, []);

  useEffect(() => {
    cancelled.current = false;
    (async () => {
      // Free hosting puts the API to sleep after fifteen minutes, and waking
      // it takes about a minute. That is not an error, so it should not be
      // reported as one. Keep knocking, and say what is happening.
      const deadline = Date.now() + 120_000;
      for (let attempt = 0; ; attempt += 1) {
        if (cancelled.current) return;
        try {
          const [nextHealth, nextPayees] = await Promise.all([
            api.health(),
            api.payees(),
          ]);
          if (cancelled.current) return;
          setHealth(nextHealth);
          setPayees(nextPayees);
          setWaking(false);
          await refresh();
          return;
        } catch (problem) {
          if (Date.now() > deadline) {
            setWaking(false);
            say(problem);
            return;
          }
          setWaking(true);
          await wait(Math.min(1500 + attempt * 500, 4000));
        }
      }
    })();
    return () => {
      cancelled.current = true;
    };
  }, [refresh, say]);

  const act = useCallback(
    async (work: () => Promise<void>) => {
      setBusy(true);
      setError(null);
      try {
        await work();
        await refresh();
      } catch (problem) {
        say(problem);
      } finally {
        setBusy(false);
      }
    },
    [refresh, say],
  );

  const ask = useCallback(
    (body: { payee: string; category: string; amount: string; description: string }) =>
      act(async () => {
        setNote("");
        const decision = (await api.attempt(MANDATE_ID, body)) as {
          verdict: "allow" | "block";
          reason: string;
          trace: LogRow["trace"];
        };
        const fails = decision.trace.filter((r) => r.outcome === "fail");
        setLastAsk({
          verdict: decision.verdict,
          reason: decision.reason,
          severity: fails.length ? worstOf(fails) : null,
        });
      }),
    [act],
  );

  /** Unlike `act`, this lets the error reach the panel, which has somewhere
   *  sensible to put it and knows which search failed. */
  const shop = useCallback(
    async (needs: string[]): Promise<ShopStep[]> => {
      setBusy(true);
      setError(null);
      try {
        const outcome = await api.shop(MANDATE_ID, needs);
        await refresh();
        const turned = outcome.steps.filter((s) => s.action === "reshopped");
        setNote(
          turned.length
            ? "Refused, told what would clear, and went back to the shop for it."
            : outcome.steps.map((s) => s.summary).join("  ·  "),
        );
        return outcome.steps;
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const runScenario = useCallback(async () => {
    setRunning(true);
    setError(null);
    setLastAsk(null);
    setSelected([]);
    try {
      await api.reset();
      setExpanded(new Set());
      seen.current = 0;
      await refresh();

      for (const beat of SCENARIO) {
        if (cancelled.current) return;
        setNote(beat.note);
        await api.attempt(MANDATE_ID, {
          payee: beat.payee,
          category: beat.category,
          amount: beat.amount,
          description: beat.description,
        });
        await refresh();
        if (beat.pause) await wait(beat.pause);
      }
      setNote("Six holds standing. Approve them and one batch moves the money.");
    } catch (problem) {
      say(problem);
    } finally {
      setRunning(false);
    }
  }, [refresh, say]);

  const payOut = useCallback(
    () =>
      act(async () => {
        const result = await api.payout(MANDATE_ID, selected);
        const count = result.settled_charge_ids.length;
        setNote(
          `Batch ${result.batch.batch_id}: ${count} ${
            count === 1 ? "payout" : "payouts"
          } sent, ${result.batch.status.toLowerCase()}.`,
        );
        setSelected([]);
      }),
    [act, selected],
  );

  const handBack = useCallback(
    () =>
      act(async () => {
        for (const chargeId of selected) await api.releaseHold(chargeId);
        setNote(
          `${selected.length} ${selected.length === 1 ? "hold" : "holds"} handed back. The budget is free again.`,
        );
        setSelected([]);
      }),
    [act, selected],
  );

  const revoke = useCallback(
    () =>
      act(async () => {
        const result = await api.revoke(MANDATE_ID);
        const dropped = result.released_charge_ids.length;
        setNote(
          dropped
            ? `Revoked. ${dropped} ${dropped === 1 ? "hold" : "holds"} dropped mid-flight. Anything settled stays settled.`
            : "Revoked. Nothing further will clear on this mandate.",
        );
        setSelected([]);
      }),
    [act],
  );

  const reset = useCallback(
    () =>
      act(async () => {
        await api.reset();
        setExpanded(new Set());
        setSelected([]);
        setLastAsk(null);
        setNote("");
        seen.current = 0;
      }),
    [act],
  );

  const toggle = useCallback((attemptId: string) => {
    setExpanded((open) => {
      const next = new Set(open);
      if (next.has(attemptId)) next.delete(attemptId);
      else next.add(attemptId);
      return next;
    });
  }, []);

  const rows = useMemo<GridRow[]>(() => {
    const byId = new Map(charges.map((c) => [c.id, c]));
    const out: GridRow[] = [];
    decisions.forEach((decision, index) => {
      const charge = byId.get(`chg_${decision.attempt_id}`);
      const row: LogRow = {
        ...decision,
        kind: "decision",
        sequence: index + 1,
        charge_state: charge?.state ?? null,
        charge_id: charge?.id ?? null,
      };
      out.push(row);
      // A search filters the grid, and a half-height band under a hidden
      // parent is just a stray. Bands come back when the search clears.
      if (!query && expanded.has(decision.attempt_id) && failuresOf(row).length) {
        out.push({ kind: "evidence", attempt_id: decision.attempt_id, parent: row });
      }
    });
    return out;
  }, [charges, decisions, expanded, query]);

  const firedCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const decision of decisions) {
      for (const code of decision.failed_codes) {
        counts.set(code, (counts.get(code) ?? 0) + 1);
      }
    }
    return counts;
  }, [decisions]);

  const selectedTotal = useMemo(() => {
    const byId = new Map(charges.map((c) => [c.id, c]));
    return selected.reduce((sum, id) => sum + (byId.get(id)?.amount.minor ?? 0), 0);
  }, [charges, selected]);

  const refusals = decisions.filter((d) => d.verdict === "block").length;
  const holds = charges.filter((c) => c.state === "pending").length;
  const working = busy || running;

  if (!mandate) {
    return (
      <div className="empty" style={{ height: "100vh" }}>
        {error ? (
          <>
            <h3>The engine is not answering</h3>
            <p>{error}</p>
            <p style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>
              uvicorn leash.api:app --reload
            </p>
          </>
        ) : waking ? (
          <>
            <span className="spin" />
            <h3>Waking the engine</h3>
            <p>
              The API sleeps after fifteen idle minutes on free hosting, and
              takes about a minute to come back. Nothing is wrong.
            </p>
          </>
        ) : (
          <>
            <span className="spin" />
            <p>reading the mandate</p>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="shell">
      <header className="topbar">
        <span className="wordmark-row">
          <Mark />
          <span className="wordmark">Leash</span>
        </span>
        <span className="topbar-id">
          <b>{mandate.mandate_id}</b>
          <span>·</span>
          <span>{mandate.agent_id}</span>
        </span>
        <div className="topbar-right">
          <span className="chip">
            {health?.gateway === "paypal" ? "PayPal sandbox" : "simulated payouts"}
          </span>
          <span className={`status ${mandate.status}`}>{mandate.status}</span>
        </div>
      </header>

      <div className="body">
        <Authority
          mandate={mandate}
          firedCounts={firedCounts}
          busy={working}
          onRevoke={revoke}
          onReset={reset}
        />

        <div className="main">
          <div className="grid-frame">
            {error ? (
              <div className="banner">
                <span>{error}</span>
                <button className="btn small" onClick={() => setError(null)}>
                  dismiss
                </button>
              </div>
            ) : null}

            <div className="grid-bar">
              <span className="label">Decision log</span>
              <span className="counts">
                <b>{decisions.length}</b> asked
              </span>
              <span className="counts refused">
                <b>{refusals}</b> refused
              </span>
              <button
                className={`toggle${onlyRefusals ? " on" : ""}`}
                onClick={() => setOnlyRefusals((on) => !on)}
                aria-pressed={onlyRefusals}
              >
                only refusals
              </button>
              <input
                className="field"
                style={{
                  height: 26,
                  width: 170,
                  padding: "0 8px",
                  border: "1px solid var(--line)",
                  background: "var(--sunk)",
                  color: "var(--ink)",
                  fontFamily: "var(--mono)",
                  fontSize: 11.5,
                }}
                placeholder="search the log"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="search the decision log"
              />
              <span className="spacer" />
              <button
                className="btn"
                onClick={runScenario}
                disabled={working}
                title="Reset and play the scripted run"
              >
                {running ? <span className="spin" /> : null}
                {running ? "Running" : "Run scenario"}
              </button>
            </div>

            <DecisionGrid
              rows={rows}
              expanded={expanded}
              onToggle={toggle}
              onSelectionChange={setSelected}
              onlyRefusals={onlyRefusals}
              query={query}
            />

            <div className="actionbar">
              <span className="selection-note">
                {selected.length ? (
                  <>
                    {selected.length} of {holds} held ·{" "}
                    {withCurrency(selectedTotal, mandate.currency)}
                  </>
                ) : holds ? (
                  <>
                    {holds} {holds === 1 ? "hold" : "holds"} standing ·{" "}
                    {money(mandate.held, mandate.currency)} not yet moved
                  </>
                ) : (
                  <span style={{ color: "var(--ink-4)" }}>nothing held</span>
                )}
              </span>
              <span className="spacer" />
              <button
                className="btn"
                onClick={handBack}
                disabled={working || !selected.length}
              >
                Hand back
              </button>
              <button
                className="btn primary"
                onClick={payOut}
                disabled={working || !selected.length}
              >
                {busy ? <span className="spin" /> : null}
                Approve and pay out
              </button>
            </div>
          </div>

          <div>
            <div className="console-tabs" role="tablist">
              <button
                className={`console-tab${console_ === "ask" ? " on" : ""}`}
                onClick={() => setConsole("ask")}
                role="tab"
                aria-selected={console_ === "ask"}
              >
                Ask for one thing
              </button>
              <button
                className={`console-tab${console_ === "shop" ? " on" : ""}`}
                onClick={() => setConsole("shop")}
                role="tab"
                aria-selected={console_ === "shop"}
              >
                Send it shopping
              </button>
            </div>

            {console_ === "ask" ? (
              <AskConsole
                payees={payees}
                terms={mandate.terms}
                busy={working}
                revoked={mandate.status !== "active"}
                last={lastAsk}
                note={note}
                onAsk={ask}
              />
            ) : (
              <ShopPanel
                catalogName={health?.catalog ?? "static"}
                busy={working}
                onShop={shop}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
