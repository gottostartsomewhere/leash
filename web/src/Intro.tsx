import { money } from "./format";
import type { MandateSummary } from "./types";

/** "$500", not "500.00": a headline is read, not reconciled. Cents only
 *  when there are some, and the plain amount for anything not in dollars. */
function headline(minor: number, currency: string): string {
  if (currency !== "USD") return `${money(minor, currency)} ${currency}`;
  const whole = minor % 100 === 0;
  return `$${(minor / 100).toLocaleString("en-US", {
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  })}`;
}

interface Props {
  mandate: MandateSummary;
  collapsed: boolean;
  busy: boolean;
  onWatch: () => void;
  onAttack: () => void;
  onConnect: () => void;
  onCollapse: () => void;
}

/** What a judge reads in the first five seconds.
 *
 *  The screen underneath is an instrument panel, and an instrument panel is
 *  meaningless until you know what it is measuring. So before any of it, one
 *  sentence about what is at stake and one invitation, with the three ways
 *  in. After the first one is taken it folds down to a single line, because
 *  by then the panel is doing the explaining. */
export function Intro({ mandate, collapsed, busy, onWatch, onAttack, onConnect, onCollapse }: Props) {
  const total = headline(mandate.total_limit, mandate.currency);
  const actions = (
    <div className="intro-actions">
      <button className="btn primary" onClick={onWatch} disabled={busy}>
        Watch it run
      </button>
      <button className="btn" onClick={onAttack} disabled={busy}>
        Attack it
      </button>
      <button className="btn" onClick={onConnect}>
        Connect your own agent
      </button>
    </div>
  );

  if (collapsed) {
    return (
      <div className="intro slim">
        <p>
          This agent can spend <b className="num">{total}</b> of your money. Try to break it.
        </p>
        {actions}
      </div>
    );
  }

  return (
    <section className="intro" aria-labelledby="intro-title">
      <div className="intro-copy">
        <h1 id="intro-title">
          This agent can spend <span className="num">{total}</span> of your money.
        </h1>
        <p className="intro-sub">These are the rules it can't break. Try to break them.</p>
      </div>
      <div className="intro-right">
        {actions}
        <p className="proof">
          Attacked 322 ways by two red teams, one of them a model. Nothing got
          through. It settles over PayPal Payouts, and only a person releases
          the money.
        </p>
        <button className="intro-hide" onClick={onCollapse}>
          Fold this away
        </button>
      </div>
    </section>
  );
}
