import { duration, money, percent, withCurrency } from "../format";
import type { MandateSummary } from "../types";

interface AuthorityProps {
  mandate: MandateSummary;
  /** How many refusals each rule has caused so far, across the whole session. */
  firedCounts: Map<string, number>;
  busy: boolean;
  onRevoke: () => void;
  onReset: () => void;
}

/** Settled, held and free, drawn to scale. Held money is hatched because it
 *  is committed without having moved, which is a different thing from spent
 *  and a different thing from available. */
function Gauge({ mandate }: { mandate: MandateSummary }) {
  const { total_limit: total, committed, held, available, currency } = mandate;
  const settled = Math.max(committed - held, 0);
  const pct = (part: number) => (total > 0 ? (part / total) * 100 : 0);

  return (
    <>
      <div className="gauge-total">
        <span className="big">{money(available, currency)}</span>
        <span className="of">of {withCurrency(total, currency)} unspent</span>
      </div>
      <div
        className="gauge"
        role="img"
        aria-label={`${money(settled, currency)} settled, ${money(held, currency)} held, ${money(available, currency)} available of ${money(total, currency)}`}
      >
        <div className="gauge-seg gauge-settled" style={{ width: `${pct(settled)}%` }} />
        <div className="gauge-seg gauge-held" style={{ width: `${pct(held)}%` }} />
        <div className="gauge-seg gauge-free" />
      </div>
      <div className="gauge-legend">
        <div>
          <span className="k">Settled</span>
          <span className="v">{money(settled, currency)}</span>
        </div>
        <div>
          <span className="k">Held</span>
          <span className="v" style={{ color: held ? "var(--sev-high)" : undefined }}>
            {money(held, currency)}
          </span>
        </div>
        <div>
          <span className="k">Available</span>
          <span className="v">{money(available, currency)}</span>
        </div>
      </div>
    </>
  );
}

interface Constraint {
  code: string;
  label: string;
  value: string;
}

function constraintsOf(mandate: MandateSummary): Constraint[] {
  const { terms: t, currency } = mandate;
  const list: Constraint[] = [
    {
      code: "insufficient_budget",
      label: "Total authority",
      value: withCurrency(mandate.total_limit, currency),
    },
  ];

  if (t.per_item_limit !== null) {
    list.push({
      code: "per_item_limit",
      label: "Any one purchase",
      value: money(t.per_item_limit, currency),
    });
    list.push({
      code: "structuring",
      label: "…and any split of one",
      value: `Within ${duration(t.structuring_window_seconds)}`,
    });
  }

  if (t.per_payee_limit !== null) {
    list.push({
      code: "per_payee_limit",
      label: "Any one counterparty",
      value: money(t.per_payee_limit, currency),
    });
  }

  if (t.velocity) {
    const parts: string[] = [];
    if (t.velocity.max_count !== null) parts.push(`${t.velocity.max_count} charges`);
    if (t.velocity.max_amount !== null)
      parts.push(money(t.velocity.max_amount, currency));
    list.push({
      code: "velocity",
      label: `Pace per ${duration(t.velocity.window_seconds)}`,
      value: parts.join(" · ") || "Unlimited",
    });
  }

  if (t.concentration_max_share !== null) {
    list.push({
      code: "concentration",
      label: "Share to one counterparty",
      value:
        percent(t.concentration_max_share) +
        (t.concentration_floor ? ` past ${money(t.concentration_floor, currency)}` : ""),
    });
  }

  list.push({
    code: "outside_window",
    label: "Expires",
    value: new Date(t.ends_at).toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
    }),
  });

  return list;
}

export function Authority({
  mandate,
  firedCounts,
  busy,
  onRevoke,
  onReset,
}: AuthorityProps) {
  const { terms } = mandate;
  const revoked = mandate.status === "revoked";

  return (
    <aside className="rail">
      <div className="section">
        <div className="section-head">
          <span className="label">Authority</span>
          <span className={`status ${mandate.status}`}>{mandate.status}</span>
        </div>
        <Gauge mandate={mandate} />
      </div>

      <div className="section">
        <div className="section-head">
          <span className="label">Terms</span>
          <span className="hint">{mandate.currency}</span>
        </div>
        <div className="rules">
          {constraintsOf(mandate).map((c) => {
            // A running count rather than a flag on the latest decision: it
            // says which rules are actually doing the work, and it does not
            // flicker on every attempt.
            const fired = firedCounts.get(c.code) ?? 0;
            return (
              <div className={`rule${fired ? " fired" : ""}`} key={c.code}>
                <span className="rule-k">
                  {c.label}
                  {fired ? (
                    <span
                      className="rule-fires"
                      title={`Stopped ${fired} ${fired === 1 ? "attempt" : "attempts"}`}
                    >
                      {" "}
                      ×{fired}
                    </span>
                  ) : null}
                </span>
                <span className="rule-v">{c.value}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="section">
        <div className="section-head">
          <span className="label">Scope</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          <div>
            <span className="scope-k">
              Categories
            </span>
            <div className="scope">
              {terms.allowed_categories?.length ? (
                terms.allowed_categories.map((c) => (
                  <span className="chip" key={c}>
                    {c}
                  </span>
                ))
              ) : (
                <span className="hint">Anything</span>
              )}
            </div>
          </div>
          <div>
            <span className="scope-k">
              Counterparties
            </span>
            <div className="scope">
              {terms.allowed_payees?.length ? (
                terms.allowed_payees.map((p) => (
                  <span className="chip" key={p}>
                    {p}
                  </span>
                ))
              ) : (
                <span className="hint">Any known payee</span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="rail-foot">
        <p>
          Revoking drops every hold that has not settled. Money that already
          moved stays moved, because that is the truth.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn danger"
            style={{ flex: 1 }}
            onClick={onRevoke}
            disabled={busy || revoked}
          >
            {revoked ? "Revoked" : "Revoke"}
          </button>
          <button className="btn" onClick={onReset} disabled={busy}>
            Reset
          </button>
        </div>
      </div>
    </aside>
  );
}
