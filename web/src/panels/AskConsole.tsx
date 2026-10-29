import { useState } from "react";
import type { MandateTerms, Payee } from "../types";

const EXTRA_CATEGORIES = ["electronics", "travel", "gifts"];

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
  const [payee, setPayee] = useState("acme_eu");
  const [category, setCategory] = useState("office");
  const [amount, setAmount] = useState("75.00");
  const [description, setDescription] = useState("");

  const categories = [...(terms.allowed_categories ?? []), ...EXTRA_CATEGORIES];

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
          <span>counterparty</span>
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
          <span>category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label className="field amount">
          <span>amount</span>
          <input
            value={amount}
            inputMode="decimal"
            onChange={(e) => setAmount(e.target.value)}
            aria-label="amount in major units"
          />
        </label>

        <label className="field" style={{ flex: 1, minWidth: 160 }}>
          <span>what for</span>
          <input
            value={description}
            placeholder="optional"
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
