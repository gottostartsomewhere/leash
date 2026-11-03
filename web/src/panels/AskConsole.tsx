import { useEffect, useMemo, useState } from "react";
import { label } from "../format";
import type { MandateTerms, Payee } from "../types";

// Roots the demo mandate leaves out, offered so the out-of-scope refusal
// can be triggered deliberately.
const EXTRA_CATEGORIES = ["electronics", "home-garden", "apparel-accessories"];

export interface AskResult {
  reason: string;
  verdict: "allow" | "block";
  severity: "medium" | "high" | "critical" | null;
}

interface AskConsoleProps {
  payees: Payee[];
  terms: MandateTerms;
  busy: boolean;
  /** Deliberately still usable: asking a revoked mandate for money and
   *  watching it refuse is the proof, and a greyed-out button is not. */
  revoked: boolean;
  last: AskResult | null;
  note: string;
  onAsk: (body: {
    payee: string;
    category: string;
    amount: string;
    description: string;
  }) => void;
}

/** One spend, by hand. The scenario covers the recorded demo; this is for the
 *  question a judge asks out loud, which is the one worth being able to
 *  answer live. */
export function AskConsole({
  payees,
  terms,
  busy,
  revoked,
  last,
  note,
  onAsk,
}: AskConsoleProps) {
  const categories = useMemo(
    () => [...(terms.allowed_categories ?? []), ...EXTRA_CATEGORIES],
    [terms.allowed_categories],
  );

  const [payee, setPayee] = useState("acme_eu");
  const [category, setCategory] = useState(() => categories[0] ?? "");
  const [amount, setAmount] = useState("75.00");
  const [description, setDescription] = useState("");

  // Derived rather than hardcoded, and corrected if the mandate's scope
  // changes. A category the select is not even showing would still be
  // submitted, and get refused for a reason nothing on screen explains.
  useEffect(() => {
    if (!categories.includes(category)) setCategory(categories[0] ?? "");
  }, [categories, category]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = amount.trim();
    if (!value || Number(value) <= 0) return;
    onAsk({ payee, category, amount: value, description: description.trim() });
  };

  return (
    <div className="ask">
      <form className="ask-form" onSubmit={submit}>
        <label className="field payee">
          <span>Counterparty</span>
          <select value={payee} onChange={(e) => setPayee(e.target.value)}>
            {payees.map((p) => (
              <option key={p.id} value={p.id}>
                {p.id}
                {p.counterparty !== p.id ? ` → ${p.counterparty}` : ""}
              </option>
            ))}
          </select>
        </label>

        <label className="field category">
          <span>Category</span>
          {/* The label is capitalised, the value it submits is not. */}
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {categories.map((c) => (
              <option key={c} value={c}>
                {label(c)}
              </option>
            ))}
          </select>
        </label>

        <label className="field amount">
          <span>Amount</span>
          <input
            value={amount}
            inputMode="decimal"
            onChange={(e) => setAmount(e.target.value)}
            aria-label="Amount in major units"
          />
        </label>

        <label className="field" style={{ flex: 1, minWidth: 160 }}>
          <span>What for</span>
          <input
            value={description}
            placeholder="Optional"
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>

        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? <span className="spin" /> : null}
          Ask to spend
        </button>
      </form>

      <div
        className={`ask-echo${
          last ? ` ${last.verdict}${last.severity === "critical" ? " critical" : ""}` : ""
        }`}
      >
        {note ? (
          <span style={{ color: "var(--ink-3)" }}>{note}</span>
        ) : last ? (
          <span>{last.reason}</span>
        ) : revoked ? (
          <span style={{ color: "var(--ink-4)" }}>
            The mandate is revoked. Ask it for money anyway and watch what it says.
          </span>
        ) : (
          <span style={{ color: "var(--ink-4)" }}>
            Try 75.00 to acme_eu twice. The second one is the interesting part.
          </span>
        )}
      </div>
    </div>
  );
}
