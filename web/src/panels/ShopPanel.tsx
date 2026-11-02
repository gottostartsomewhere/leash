import { useCallback, useState } from "react";
import { ApiError, api } from "../api";
import { label, money, sentence } from "../format";
import type { CatalogItem, CatalogOffer, ShopStep } from "../types";

interface ShopPanelProps {
  catalogName: string;
  busy: boolean;
  onShop: (needs: string[]) => Promise<ShopStep[]>;
}

const SUGGESTIONS = ["chair", "monitor", "desk", "paper", "lamp"];

/** No image is the normal case for some catalogues, so the placeholder has to
 *  be deliberate rather than a broken box. */
function Thumb({ item }: { item: CatalogItem }) {
  if (item.image_url) {
    return <img className="thumb" src={item.image_url} alt="" loading="lazy" />;
  }
  return (
    <span className="thumb thumb-blank" aria-hidden="true">
      {(item.category || item.title).slice(0, 2).toUpperCase()}
    </span>
  );
}

function Merchants({ item }: { item: CatalogItem }) {
  const extra = item.counterparties.length - 1;
  const best = item.best;
  return (
    <span className="merchants">
      <span className="chip">{best ? best.domain : "Nobody selling"}</span>
      {extra > 0 ? (
        <span
          className="chip more"
          title={item.offers.map((o) => `${o.domain} ${o.display}`).join("\n")}
        >
          +{extra} more
        </span>
      ) : null}
    </span>
  );
}

function Product({ item }: { item: CatalogItem }) {
  const best = item.best;
  return (
    <article className="product" title={item.title}>
      <Thumb item={item} />
      <div className="product-body">
        <h4 className="product-title">{item.title}</h4>
        <div className="product-meta">
          {item.brand ? <span>{item.brand}</span> : null}
          {item.category ? <span className="chip">{item.category}</span> : null}
        </div>
        <div className="product-foot">
          <span className="product-price num">
            {best ? money(best.amount, best.currency) : "—"}
          </span>
          <Merchants item={item} />
        </div>
      </div>
    </article>
  );
}

/** One line of what the agent did: what it tried, where, and what it cost. */
function TraceRow({
  item,
  offer,
  verdict,
  codes,
}: {
  item: CatalogItem | null;
  offer: CatalogOffer | null;
  verdict: "bought" | "refused";
  codes: string[];
}) {
  if (!item) return null;
  const price = offer ?? item.best;
  return (
    <div className={`trace-row ${verdict}`}>
      <span className={`trace-verdict ${verdict}`}>
        {verdict === "bought" ? "BOUGHT" : "REFUSED"}
      </span>
      <span className="trace-what">{item.title}</span>
      <span className="trace-where">{price ? price.domain : ""}</span>
      <span className="trace-amt num">
        {price ? money(price.amount, price.currency) : ""}
      </span>
      <span className="trace-rules">
        {codes.map((code) => (
          <span className="chip rule-chip high" key={code}>
            {label(code)}
          </span>
        ))}
      </span>
    </div>
  );
}

/** The whole point of the catalogue, drawn: refused, told what would clear,
 *  went back to the shop with that as a ceiling, bought something else. */
function Trace({ step }: { step: ShopStep }) {
  const codes = step.decision?.failed_codes ?? [];

  if (step.action === "reshopped" && step.first_choice) {
    return (
      <div className="trace">
        <TraceRow
          item={step.first_choice}
          offer={step.first_choice.best}
          verdict="refused"
          codes={[]}
        />
        <div className="trace-turn">
          {step.ceiling !== null ? (
            <>
              <b className="num">{money(step.ceiling)}</b> would have cleared, so it
              looked again under that
            </>
          ) : (
            "It looked again"
          )}
        </div>
        <TraceRow item={step.item} offer={step.offer} verdict="bought" codes={[]} />
      </div>
    );
  }

  if (step.action === "bought") {
    return (
      <div className="trace">
        <TraceRow item={step.item} offer={step.offer} verdict="bought" codes={[]} />
      </div>
    );
  }

  if (step.action === "refused") {
    return (
      <div className="trace">
        <TraceRow
          item={step.item}
          offer={step.offer}
          verdict="refused"
          codes={codes}
        />
        {step.detail ? (
          <div className="trace-turn">{sentence(step.detail)}</div>
        ) : null}
      </div>
    );
  }

  return <div className="trace-turn">{sentence(step.summary)}</div>;
}

export function ShopPanel({ catalogName, busy, onShop }: ShopPanelProps) {
  const [query, setQuery] = useState("chair");
  const [items, setItems] = useState<CatalogItem[] | null>(null);
  const [steps, setSteps] = useState<ShopStep[]>([]);
  const [looking, setLooking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const look = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q) return;
      setLooking(true);
      setProblem(null);
      try {
        const found = await api.catalogSearch(q);
        setItems(found.items);
      } catch (error) {
        setProblem(error instanceof ApiError ? error.message : String(error));
        setItems([]);
      } finally {
        setLooking(false);
      }
    },
    [],
  );

  const send = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setProblem(null);
    try {
      setSteps(await onShop([q]));
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : String(error));
    }
  }, [onShop, query]);

  const working = busy || looking;

  return (
    <div className="shop">
      <form
        className="shop-form"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <label className="field" style={{ flex: 1, minWidth: 200 }}>
          <span>What the agent should buy</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Task chair"
            aria-label="What the agent should buy"
          />
        </label>
        <button
          className="btn"
          type="button"
          onClick={() => void look(query)}
          disabled={working}
        >
          {looking ? <span className="spin" /> : null}
          Look first
        </button>
        <button className="btn primary" type="submit" disabled={working}>
          {busy ? <span className="spin" /> : null}
          Send the agent
        </button>
        <span className="hint" style={{ marginLeft: "auto" }}>
          {catalogName === "channel3" ? "Channel3" : "Offline catalogue"}
        </span>
      </form>

      <div className="shop-tries">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            className="chip more"
            onClick={() => {
              setQuery(suggestion);
              void look(suggestion);
            }}
            disabled={working}
          >
            {suggestion}
          </button>
        ))}
      </div>

      {problem ? <div className="shop-problem">{problem}</div> : null}

      {items !== null ? (
        items.length ? (
          <div className="shelf">
            {items.map((item) => (
              <Product item={item} key={item.id} />
            ))}
          </div>
        ) : (
          <div className="shop-empty">Nothing in the catalogue matched that</div>
        )
      ) : null}

      {steps.length ? (
        <div className="shop-result">
          <span className="label">What it did</span>
          {steps.map((step, index) => (
            <Trace step={step} key={`${step.query}-${index}`} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
