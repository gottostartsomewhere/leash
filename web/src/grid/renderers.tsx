import { useLayoutEffect, useRef } from "react";
import type { CustomCellRendererProps } from "ag-grid-react";
import { money, spaced, withCurrency } from "../format";
import type { CheckRow, EvidenceRow, GridRow, LogRow, Severity } from "../types";

const RANK: Record<Severity, number> = { medium: 0, high: 1, critical: 2 };

export const worstOf = (codes: CheckRow[]): Severity =>
  codes.reduce<Severity>(
    (worst, r) => (RANK[r.severity] > RANK[worst] ? r.severity : worst),
    "medium",
  );

export const failuresOf = (row: LogRow): CheckRow[] =>
  row.trace.filter((r) => r.outcome === "fail");

/* -- verdict ----------------------------------------------------------- */

export function VerdictCell({ data }: CustomCellRendererProps<GridRow>) {
  if (!data || data.kind !== "decision") return null;
  const fails = failuresOf(data);
  const severity = fails.length ? worstOf(fails) : null;
  return (
    <span
      className={`verdict ${data.verdict}${severity === "critical" ? " critical" : ""}`}
    >
      {data.verdict === "allow" ? "ALLOW" : "BLOCK"}
    </span>
  );
}

/* -- money ------------------------------------------------------------- */

export function MoneyCell({ data }: CustomCellRendererProps<GridRow>) {
  if (!data || data.kind !== "decision") return null;
  return <span className="num">{money(data.amount, data.currency)}</span>;
}

/* -- charge state ------------------------------------------------------ */

export function StateCell({ data }: CustomCellRendererProps<GridRow>) {
  if (!data || data.kind !== "decision") return null;
  if (!data.charge_state) return <span className="headroom">&mdash;</span>;
  return (
    <span className={`chip state-${data.charge_state}`}>{data.charge_state}</span>
  );
}

/* -- headroom ---------------------------------------------------------- */

/** On a refusal this is the counter-offer, which is the whole point of
 *  reporting a boundary instead of a wall. On an allow it is what is left. */
export function HeadroomCell({ data }: CustomCellRendererProps<GridRow>) {
  if (!data || data.kind !== "decision") return null;
  if (data.verdict === "allow") {
    return <span className="headroom">{money(data.remaining_after, data.currency)}</span>;
  }
  if (data.max_allowable <= 0) {
    return <span className="headroom">no amount clears</span>;
  }
  return (
    <span className="headroom offered">
      {money(data.max_allowable, data.currency)} would
    </span>
  );
}

/* -- which rules fired ------------------------------------------------- */

export interface RulesCellParams {
  expanded: Set<string>;
  onToggle: (attemptId: string) => void;
}

export function RulesCell(
  props: CustomCellRendererProps<GridRow> & RulesCellParams,
) {
  const { data, expanded, onToggle } = props;
  if (!data || data.kind !== "decision") return null;

  const fails = failuresOf(data);
  if (!fails.length) {
    return <span className="headroom">inside every rule</span>;
  }

  const open = expanded.has(data.attempt_id);
  // Every check runs, so a bad attempt can name five rules at once. Two fit
  // on a row; the rest are a count, and expanding shows all of them in full.
  const shown = open ? fails : fails.slice(0, 2);
  const hidden = fails.length - shown.length;

  return (
    <div className="rules-cell">
      <button
        className={`expander${open ? " open" : ""}`}
        onClick={() => onToggle(data.attempt_id)}
        aria-expanded={open}
        aria-label={open ? "hide the evidence" : "show the evidence"}
        title={open ? "hide the evidence" : "show the evidence"}
      >
        <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden="true">
          <path d="M2 1l4 3.5L2 8" fill="none" stroke="currentColor" strokeWidth="1.4" />
        </svg>
      </button>
      {shown.map((r) => (
        <span key={r.code} className={`chip rule-chip ${r.severity}`}>
          {spaced(r.code)}
        </span>
      ))}
      {hidden > 0 ? (
        <button
          className="chip more"
          onClick={() => onToggle(data.attempt_id)}
          title={fails.map((r) => spaced(r.code)).join(", ")}
        >
          +{hidden}
        </button>
      ) : null}
    </div>
  );
}

/* -- the evidence band ------------------------------------------------- */

const HIDE_FROM_FACTS = new Set([
  "prior_charge_ids",
  "prior_amounts",
  "group",
  "detail",
]);

/** How tall the band needs to be. AG Grid wants a number before it renders,
 *  so this estimates from the same shape the band draws from. Erring tall
 *  costs a little whitespace; erring short clips the evidence. */
export function evidenceHeight(row: LogRow): number {
  const fails = failuresOf(row);
  let height = 22 + 44; // own padding, plus the footer strip
  for (const check of fails) {
    height += 26 + 20; // the rule chip row, plus the detail sentence
    const facts = Object.keys(check.evidence).filter((k) => !HIDE_FROM_FACTS.has(k));
    height += Math.ceil(facts.length / 4) * 32 + 9;
    if (check.code === "structuring") {
      const priors = (check.evidence.prior_amounts as number[] | undefined)?.length ?? 0;
      height += (priors + 2) * 13 + 22;
    }
    if (fails.length > 1) height += 14;
  }
  return Math.max(100, height);
}

function factValue(key: string, value: unknown, currency: string): string {
  if (value === null || value === undefined) return "none";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") {
    // Minor-unit money is named for it; shares and counts are not.
    if (/(limit|total|amount|spent|already|over_by|cap|committed|available|headroom|projected)/.test(key)) {
      return money(value, currency);
    }
    if (/(share|fill|confidence)/.test(key)) return `${Math.round(value * 100)}%`;
    return String(value);
  }
  return String(value);
}

/** The split, drawn. Each prior charge was fine on its own; the cap line is
 *  where the cluster crosses it. This is the picture the whole project is
 *  built to be able to draw. */
function Cluster({ check, row }: { check: CheckRow; row: LogRow }) {
  const e = check.evidence as {
    prior_amounts?: number[];
    limit?: number;
    cluster_total?: number;
  };
  const priors = e.prior_amounts ?? [];
  const limit = e.limit ?? 0;
  const total = e.cluster_total ?? 0;
  if (!priors.length || !limit) return null;

  const members = [...priors, row.amount];
  // Scaled so the cluster total fills the track; the cap then lands wherever
  // it falls, and every bar is read against the same dashed line.
  const scale = Math.max(total, limit) || 1;
  const capAt = (limit / scale) * 100;

  return (
    <div className="cluster" style={{ "--cap": `${capAt}%` } as React.CSSProperties}>
      {members.map((amount, i) => {
        const current = i === members.length - 1;
        return (
          <div key={i} className={`cluster-row${current ? " current" : ""}`}>
            <span className="who">{current ? "this one" : `charge ${i + 1}`}</span>
            <span className="track">
              <span className="fill" style={{ width: `${(amount / scale) * 100}%` }} />
            </span>
            <span className="amt">{money(amount, row.currency)}</span>
          </div>
        );
      })}
      <div className="cluster-row together">
        <span className="who">together</span>
        <span className="track">
          <span className="fill" style={{ width: "100%" }} />
        </span>
        <span className="amt">{money(total, row.currency)}</span>
      </div>
      <div className="cluster-row cluster-capline">
        <span />
        <span className="caprail">
          <span className="mark">cap {money(limit, row.currency)}</span>
        </span>
        <span />
      </div>
    </div>
  );
}

export function EvidenceBand(props: CustomCellRendererProps<GridRow>) {
  const { data, node, api } = props;
  const box = useRef<HTMLDivElement>(null);

  // `evidenceHeight` guesses before the band exists, which is enough to stop
  // the row resizing visibly. Once it has rendered it knows its own height
  // exactly, so it corrects the row rather than leaving slack under itself.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || !node || !api) return;
    const measure = () => {
      const wanted = el.scrollHeight;
      if (wanted > 0 && Math.abs((node.rowHeight ?? 0) - wanted) > 2) {
        node.setRowHeight(wanted);
        api.onRowHeightChanged();
      }
    };
    measure();
    const watcher = new ResizeObserver(measure);
    watcher.observe(el);
    return () => watcher.disconnect();
  }, [node, api]);

  const band = data as EvidenceRow | undefined;
  if (!band || band.kind !== "evidence") return null;
  const row = band.parent;
  const fails = failuresOf(row);

  return (
    <div className="evidence" ref={box}>
      {fails.map((check) => {
        const facts = Object.entries(check.evidence).filter(
          ([k]) => !HIDE_FROM_FACTS.has(k),
        );
        const group = check.evidence.group;
        return (
          <div key={check.code} style={{ marginBottom: fails.length > 1 ? 14 : 0 }}>
            <div className="evidence-head">
              <span className={`chip rule-chip ${check.severity}`}>{spaced(check.code)}</span>
              <span className="evidence-title" style={{ color: `var(--sev-${check.severity})` }}>
                {check.severity}
              </span>
              {typeof group === "string" ? (
                <span className="chip">counterparty {group}</span>
              ) : null}
            </div>
            <p className="evidence-detail">{check.detail}</p>
            {check.code === "structuring" ? <Cluster check={check} row={row} /> : null}
            <div className="facts" style={{ marginTop: 9 }}>
              {facts.map(([k, v]) => (
                <span className="fact" key={k}>
                  <span className="k">{spaced(k)}</span>
                  <span className="v">{factValue(k, v, row.currency)}</span>
                </span>
              ))}
            </div>
          </div>
        );
      })}
      <div className="facts" style={{ marginTop: 12, borderTop: "1px solid var(--line-soft)", paddingTop: 8 }}>
        <span className="fact">
          <span className="k">attempt</span>
          <span className="v">{row.attempt_id}</span>
        </span>
        <span className="fact">
          <span className="k">asked</span>
          <span className="v">{withCurrency(row.amount, row.currency)}</span>
        </span>
        <span className="fact">
          <span className="k">largest that would clear</span>
          <span className="v">
            {row.max_allowable > 0 ? withCurrency(row.max_allowable, row.currency) : "nothing"}
          </span>
        </span>
        <span className="fact">
          <span className="k">checks run</span>
          <span className="v">
            {row.trace.length} &middot; {row.trace.filter((r) => r.outcome === "pass").length} passed
            &middot; {fails.length} failed
            {row.trace.some((r) => r.outcome === "skip")
              ? ` · ${row.trace.filter((r) => r.outcome === "skip").length} not applicable`
              : ""}
          </span>
        </span>
      </div>
    </div>
  );
}
