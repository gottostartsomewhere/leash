import { useCallback, useState } from "react";

import { ApiError } from "../api";
import { label } from "../format";
import type { Draft, MandateBody } from "../types";

const EXAMPLES: [string, string][] = [
  [
    "Office supplies",
    "Office furniture and supplies only. $300 in total, nothing over $80, at most 4 purchases a minute, for two weeks.",
  ],
  [
    "Groceries",
    "Let it buy groceries and kitchen stuff, $150 for the week, never more than $40 at any one shop. Also no alcohol.",
  ],
];

interface Props {
  busy: boolean;
  onDraft: (text: string) => Promise<Draft>;
  onSign: (body: MandateBody) => Promise<void>;
}

/** Write the mandate in your own words.
 *
 *  The model drafts and the person decides. So the draft is shown the way
 *  the engine will read it, with every assumption the model made, everything
 *  it could not turn into a rule, what the terms leave open, and the result
 *  of attacking it, all before the one button that signs it. */
export function WritePanel({ busy, onDraft, onSign }: Props) {
  const [text, setText] = useState(EXAMPLES[0][1]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [working, setWorking] = useState<"draft" | "sign" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [signed, setSigned] = useState(false);

  const write = useCallback(async () => {
    if (text.trim().length < 8) {
      setProblem("Say a little more: at least how much it may spend in all.");
      return;
    }
    setWorking("draft");
    setProblem(null);
    setSigned(false);
    try {
      setDraft(await onDraft(text));
    } catch (error) {
      setDraft(null);
      setProblem(
        error instanceof ApiError && error.status === 503
          ? "No model is configured on this server, so drafting is off."
          : error instanceof Error
            ? error.message
            : String(error),
      );
    } finally {
      setWorking(null);
    }
  }, [onDraft, text]);

  const sign = useCallback(async () => {
    if (!draft) return;
    setWorking("sign");
    setProblem(null);
    try {
      await onSign(draft.mandate);
      setSigned(true);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(null);
    }
  }, [draft, onSign]);

  return (
    <section className="dock-panel write" aria-labelledby="write-title">
      <div className="dock-head">
        <div>
          <h2 id="write-title">Write a mandate in your own words</h2>
          <p>
            A model drafts it. The engine checks the draft, says what it leaves
            open, and attacks it. Then you sign it, or you don't. The model
            never decides what is allowed.
          </p>
        </div>
      </div>

      <div className="write-input">
        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setProblem(null);
          }}
          rows={2}
          aria-label="What the agent may spend, in plain English"
          placeholder="Office supplies only, $300 in total, nothing over $80, for two weeks."
        />
        <div className="write-row">
          <span className="examples">
            Try
            {EXAMPLES.map(([name, example]) => (
              <button key={name} className="example" onClick={() => setText(example)}>
                {name}
              </button>
            ))}
          </span>
          <button className="btn primary" onClick={write} disabled={busy || working !== null}>
            {working === "draft" ? <span className="spin" /> : null}
            {working === "draft" ? "Drafting" : "Draft it"}
          </button>
        </div>
      </div>

      {problem ? <p className="dock-problem">{problem}</p> : null}

      {draft ? (
        <div className="draft">
          <div className="draft-cols">
            <div>
              <h3>It read that as</h3>
              <Terms body={draft.mandate} />
              {draft.assumptions.length ? (
                <>
                  <h3>It assumed</h3>
                  <ul className="draft-list">
                    {draft.assumptions.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </>
              ) : null}
              {draft.unclear.length ? (
                <>
                  <h3>
                    It couldn't place <span className="not-enforced">not enforced</span>
                  </h3>
                  <ul className="draft-list unclear">
                    {draft.unclear.map((u) => (
                      <li key={u}>{u}</li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>

            <div>
              <h3>The worst an agent could do inside it</h3>
              <dl className="exposure">
                {draft.exposure.map((e) => (
                  <div key={e.label} className={e.loose ? "loose" : ""}>
                    <dt>{e.label}</dt>
                    <dd className="num">{e.value}</dd>
                    {e.note ? <dd className="note">{e.note}</dd> : null}
                  </div>
                ))}
              </dl>
            </div>
          </div>

          <div className="sign-row">
            <p className="attacked">
              Attacked before you sign:{" "}
              <b className="num">{draft.attack.attempts}</b> attempts,{" "}
              {draft.attack.held ? (
                <b className="held">none got through</b>
              ) : (
                <b className="breach">{draft.attack.breaches.length} got through</b>
              )}
              <span className="drafted-by">drafted by {draft.drafted_by}</span>
            </p>
            {signed ? (
              <p className="signed">
                Signed. The demo now runs on this mandate. Reset puts the default back.
              </p>
            ) : (
              <button className="btn primary" onClick={sign} disabled={busy || working !== null}>
                {working === "sign" ? <span className="spin" /> : null}
                Sign it and use it
              </button>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Terms({ body }: { body: MandateBody }) {
  const dollars = (v: string | null) => (v === null ? "none" : `${v} ${body.currency}`);
  const rows: [string, string][] = [
    ["Total", dollars(body.total_limit)],
    ["Any one purchase", dollars(body.per_item_limit)],
    ["Any one merchant", dollars(body.per_payee_limit)],
    [
      "Categories",
      body.allowed_categories?.length ? body.allowed_categories.map(label).join(", ") : "any",
    ],
    ["Pace", body.velocity?.max_count ? `${body.velocity.max_count} a minute` : "no limit"],
    ["Lasts", `${Math.round(body.duration_hours / 24)} days`],
  ];
  return (
    <dl className="terms-read">
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd className={v === "none" || v === "any" || v === "no limit" ? "open" : "num"}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
