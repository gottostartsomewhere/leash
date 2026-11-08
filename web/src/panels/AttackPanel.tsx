import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../api";
import { label, money } from "../format";
import type { AttackCampaign, AttackMove, AttackReport } from "../types";

/** What each objective is, in the words a person would use. */
const OBJECTIVES: Record<string, string> = {
  exceed_per_item: "Beat the per-purchase cap",
  exceed_per_payee: "Beat the per-merchant cap",
  exceed_budget: "Spend past the total",
  spend_out_of_scope: "Buy outside the categories",
  spend_after_revocation: "Spend after revocation",
};

/** How long the replay takes, start to finish. Long enough to watch three
 *  hundred attempts land; short enough that nobody reaches for the button
 *  again. The run itself takes tens of milliseconds, and the panel says so. */
const REPLAY_MS = 2600;

type By = "strategy" | "model";

interface Props {
  busy: boolean;
  revoked: boolean;
  onAttack: (by: By) => Promise<AttackReport>;
  /** Set by the intro's "Attack it", so one click both opens and fires.
   *  The panel calls `onAutostart` as it fires, and the parent clears it,
   *  so switching back to this tab later does not attack again. */
  autostart?: boolean;
  onAutostart?: () => void;
}

/** A red team you can press.
 *
 *  The attack runs on a sandbox copy of the mandate, seeded with what it
 *  already holds, so the real one is untouched however hard this tries. The
 *  strategy search is exhaustive and instant; it is replayed at a pace a
 *  person can follow, and labelled as a replay. The model is slower and
 *  shows its reasoning, because its reasoning is the interesting part. */
export function AttackPanel({ busy, revoked, onAttack, autostart, onAutostart }: Props) {
  const [report, setReport] = useState<AttackReport | null>(null);
  const [running, setRunning] = useState<By | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [progress, setProgress] = useState(1);
  const frame = useRef<number | null>(null);

  const replay = useCallback(() => {
    if (frame.current) cancelAnimationFrame(frame.current);
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) {
      setProgress(1);
      return;
    }
    const began = performance.now();
    const step = (now: number) => {
      // Ease out, so the tally races and then settles on its verdict.
      const t = Math.min(1, (now - began) / REPLAY_MS);
      setProgress(1 - Math.pow(1 - t, 3));
      if (t < 1) frame.current = requestAnimationFrame(step);
    };
    setProgress(0);
    frame.current = requestAnimationFrame(step);
  }, []);

  useEffect(() => () => {
    if (frame.current) cancelAnimationFrame(frame.current);
  }, []);

  const run = useCallback(
    async (by: By) => {
      setRunning(by);
      setProblem(null);
      try {
        const next = await onAttack(by);
        setReport(next);
        replay();
      } catch (error) {
        setProblem(
          error instanceof ApiError && error.status === 503
            ? "No model is configured on this server, so only the strategy search can run."
            : error instanceof ApiError && error.status === 429
              ? "A model attack is already running. Try again in a moment."
              : error instanceof Error
                ? error.message
                : String(error),
        );
      } finally {
        setRunning(null);
      }
    },
    [onAttack, replay],
  );

  // The panel is usually mounted by the very click that asks it to fire, so
  // a "has the request changed since I mounted" check never sees a change.
  // The parent owns the request instead, and the ref only stops React's
  // development double-run of effects from firing it twice.
  const fired = useRef(false);
  useEffect(() => {
    if (!autostart) {
      fired.current = false;
      return;
    }
    if (fired.current) return;
    fired.current = true;
    onAutostart?.();
    void run("strategy");
  }, [autostart, onAutostart, run]);

  const shown = report ? Math.round(progress * report.attempts) : 0;
  const settled = progress >= 1;
  const isModel = report?.adversary.startsWith("llm:");

  const caughtBy = useMemo(() => {
    if (!report) return [];
    const counts = new Map<string, number>();
    for (const c of report.campaigns) {
      for (const [code, n] of Object.entries(c.by_code)) {
        counts.set(code, (counts.get(code) ?? 0) + n);
      }
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  }, [report]);

  return (
    <section className="dock-panel attack" aria-labelledby="attack-title">
      <div className="dock-head">
        <div>
          <h2 id="attack-title">Try to break it</h2>
          <p>
            Five objectives, thrown at a sandbox copy of this mandate with
            everything it already holds. Nothing reaches the real one.
          </p>
        </div>
        <div className="dock-actions">
          <button
            className="btn primary"
            onClick={() => run("strategy")}
            disabled={busy || running !== null}
          >
            {running === "strategy" ? <span className="spin" /> : null}
            Run 300 attacks
          </button>
          <button
            className="btn"
            onClick={() => run("model")}
            disabled={busy || running !== null}
            title="Slower. The model is the attacker that has found real bugs."
          >
            {running === "model" ? <span className="spin" /> : null}
            {running === "model" ? "The model is thinking" : "Send a model at it"}
          </button>
        </div>
      </div>

      {problem ? <p className="dock-problem">{problem}</p> : null}

      {revoked && !report ? (
        <p className="dock-hint">
          This mandate is revoked, so every attack bounces off. Reset it to
          attack a live one.
        </p>
      ) : null}

      {!report && !running && !problem ? (
        <div className="attack-empty">
          <p>
            The search works through ten strategies: splitting a purchase
            under the cap, hopping between one merchant's addresses, dripping
            small amounts, spraying across payees, slowing down to slip under
            the pace limit, trying other categories and currencies.
          </p>
          <p>
            The model is told the objective and nothing else. It found a real
            bug the search never could, because every strategy above stays
            under the cap, and the bug was at the cap exactly. That is fixed,
            and it is why the model is here.
          </p>
        </div>
      ) : null}

      {report ? (
        <>
          <div className={`attack-verdict${settled ? " settled" : ""}`} aria-live="polite">
            <span className="tally num">{shown}</span>
            <span className="tally-of">
              {settled ? (
                report.held ? (
                  <>
                    attacks, <b>none got through</b>
                  </>
                ) : (
                  <>
                    attacks, <b className="breach">{report.breaches.length} got through</b>
                  </>
                )
              ) : (
                "attacks"
              )}
            </span>
            <span className="attack-meta">
              {isModel
                ? `${report.adversary.replace("llm:", "")} · ${(report.elapsed_ms / 1000).toFixed(1)}s`
                : `ran in ${report.elapsed_ms} ms, replayed so you can watch it`}
            </span>
          </div>

          <ol className="lanes">
            {report.campaigns.map((c) => (
              <Lane key={c.objective} campaign={c} progress={progress} />
            ))}
          </ol>

          {settled && caughtBy.length ? (
            <p className="caught-by">
              <span>Caught by</span>
              {caughtBy.map(([code, n]) => (
                <span key={code} className="caught">
                  {label(code)} <b className="num">{n}</b>
                </span>
              ))}
            </p>
          ) : null}

          {settled && isModel ? <ModelMoves report={report} /> : null}

          {settled ? (
            <p className="dock-hint">
              Allowed attempts were inside the rules: an attacker trying to beat
              a $100 cap with a $40 purchase gets the $40 purchase. A breach is
              an objective actually reached.
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function Lane({ campaign, progress }: { campaign: AttackCampaign; progress: number }) {
  const visible = Math.round(progress * campaign.log.length);
  const moves = campaign.log.slice(0, visible);
  const done = progress >= 1;
  return (
    <li className={`lane${campaign.breach ? " breached" : ""}`}>
      <span className="lane-name">{OBJECTIVES[campaign.objective] ?? label(campaign.objective)}</span>
      <span className="ticks" aria-hidden="true">
        {moves.map((m) => (
          <i
            key={m.sequence}
            className={m.verdict === "allow" ? "inside" : "refused"}
            title={`${money(m.amount, m.currency)} to ${m.payee}: ${m.headline}`}
          />
        ))}
      </span>
      <span className="lane-count num">
        {done ? (
          campaign.breach ? (
            <b className="breach">breached</b>
          ) : (
            <>
              {campaign.attempts} tried · <b>held</b>
            </>
          )
        ) : (
          visible
        )}
      </span>
    </li>
  );
}

/** The model's moves, with its own reasons. Few enough to read every one. */
function ModelMoves({ report }: { report: AttackReport }) {
  const moves: (AttackMove & { objective: string })[] = report.campaigns.flatMap((c) =>
    c.log.map((m) => ({ ...m, objective: c.objective })),
  );
  if (!moves.length) {
    return (
      <p className="dock-hint">
        The model gave up without trying anything, or could not be reached. Try again in a minute.
      </p>
    );
  }
  return (
    <ul className="model-moves">
      {moves.slice(0, 8).map((m) => (
        <li key={`${m.objective}-${m.sequence}`}>
          <span className={`verdict-chip ${m.verdict}`}>{m.verdict === "allow" ? "inside" : "refused"}</span>
          <span className="num">{money(m.amount, m.currency)}</span>
          <span className="move-payee">{m.payee}</span>
          <span className="move-why">{m.rationale || m.strategy}</span>
          {m.verdict === "block" ? <span className="move-rule">{label(m.codes[0] ?? "")}</span> : null}
        </li>
      ))}
    </ul>
  );
}
