import { useCallback, useState } from "react";

import { MCP_URL, viaMcp } from "../api";
import { label, money } from "../format";
import type { DecisionRow } from "../types";

const PROMPT =
  "Read my Leash mandate, then buy me an office chair. After that, try paying " +
  "acme_us $75 and acme_eu $75 for a desk, and tell me what happened.";

const TOOLS: [string, string][] = [
  ["read_mandate", "what it may spend, and what is left"],
  ["search_products", "a live catalogue, with who to pay"],
  ["request_purchase", "ask to spend, and get told why not"],
  ["recent_decisions", "what it has asked for so far"],
];

interface Props {
  decisions: DecisionRow[];
}

/** Put your own agent on a Leash.
 *
 *  The built-in shopper is a demonstration. This is the product: the same
 *  mandate, served over MCP, so a Claude or a ChatGPT that is not ours can
 *  shop and ask to spend, through the same checks, into the log above. */
export function ConnectPanel({ decisions }: Props) {
  const theirs = decisions.filter((d) => viaMcp(d.attempt_id)).slice(-6).reverse();

  return (
    <section className="dock-panel connect" aria-labelledby="connect-title">
      <div className="dock-head">
        <div>
          <h2 id="connect-title">Put your own agent on a Leash</h2>
          <p>
            Any agent that speaks MCP can shop and ask to spend under this
            mandate. Its purchases land in the log above, marked{" "}
            <span className="via-mcp">via MCP</span>, and nothing it does can
            move money: a person releases what it is allowed.
          </p>
        </div>
      </div>

      <div className="connect-grid">
        <div className="connect-steps">
          <Copyable label="1. Add this as a connector" value={MCP_URL} mono />
          <ul className="clients">
            <li>
              <b>Claude</b> Settings, Connectors, add a custom connector with the URL.
            </li>
            <li>
              <b>ChatGPT</b> Turn on developer mode, then create a connector with the URL.
            </li>
            <li>
              <b>Anything else</b> Any MCP client over streamable HTTP. To poke at it by
              hand, <code>npx @modelcontextprotocol/inspector</code>.
            </li>
          </ul>
          <Copyable label="2. Then ask it" value={PROMPT} />
        </div>

        <div className="connect-side">
          <h3>What it gets</h3>
          <ul className="tools">
            {TOOLS.map(([name, what]) => (
              <li key={name}>
                <code>{name}</code>
                <span>{what}</span>
              </li>
            ))}
          </ul>
          <p className="no-money">No tool moves money, revokes, or edits the mandate.</p>

          <h3>Its moves</h3>
          {theirs.length ? (
            <ul className="their-moves" aria-live="polite">
              {theirs.map((d) => (
                <li key={d.attempt_id}>
                  <span className={`verdict-chip ${d.verdict}`}>
                    {d.verdict === "allow" ? "held" : "refused"}
                  </span>
                  <span className="num">{money(d.amount, d.currency)}</span>
                  <span className="move-payee">{d.payee}</span>
                  {d.failed_codes.length ? (
                    <span className="move-rule">{label(d.failed_codes[0])}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="dock-hint">
              Nothing yet. Connect an agent and ask it to buy something; each
              attempt shows up here and in the log within a few seconds.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function Copyable({ label: title, value, mono }: { label: string; value: string; mono?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard refused; the text is selectable anyway */
    }
  }, [value]);
  return (
    <div className="copyable">
      <span className="copyable-label">{title}</span>
      <div className="copyable-row">
        <span className={`copyable-value${mono ? " num" : ""}`}>{value}</span>
        <button className="btn small" onClick={copy} aria-label={`Copy: ${title}`}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}
