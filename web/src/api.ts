import type {
  AttackReport,
  Draft,
  MandateBody,
  AttemptBody,
  Balances,
  CatalogResults,
  Charge,
  DecisionRow,
  Health,
  MandateSummary,
  Payee,
  PayoutOutcome,
  ShopOutcome,
} from "./types";

// In development Vite proxies /api, so the browser only ever sees one origin.
// In production the API is its own service and VITE_API_BASE points at it.
// Empty means same-origin, for anyone serving the built files from the API.
const BASE = (
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  (import.meta.env.DEV ? "/api" : "")
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    // A dead backend is the most likely failure during a live demo, so it gets
    // a sentence a person can act on rather than a TypeError.
    throw new ApiError(
      BASE ? `Cannot reach the engine at ${BASE}` : "Cannot reach the engine",
      0,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* a non-JSON error body is not worth a second failure */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const post = <T,>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body ? JSON.stringify(body) : "{}" });

export const api = {
  health: () => call<Health>("/health"),
  payees: () => call<Payee[]>("/payees"),
  mandate: (id: string) => call<MandateSummary>(`/mandates/${id}`),
  decisions: (id: string) => call<DecisionRow[]>(`/mandates/${id}/decisions`),
  charges: (id: string) => call<Charge[]>(`/mandates/${id}/charges`),

  attempt: (id: string, body: AttemptBody) =>
    post<Record<string, unknown>>(`/mandates/${id}/attempts`, {
      currency: "USD",
      ...body,
    }),

  revoke: (id: string) =>
    post<{ released_charge_ids: string[]; summary: Balances }>(
      `/mandates/${id}/revoke`,
    ),

  payout: (id: string, chargeIds: string[]) =>
    post<PayoutOutcome>(`/mandates/${id}/payouts`, { charge_ids: chargeIds }),

  releaseHold: (chargeId: string) =>
    post<{ summary: Balances }>(`/charges/${chargeId}/release`),

  reset: () => post<Record<string, unknown>>("/demo/reset"),

  catalogSearch: (query: string, under?: number) => {
    const params = new URLSearchParams({ q: query });
    // The ceiling crosses the wire in major units, the way a price is read.
    if (under !== undefined) params.set("under", (under / 100).toFixed(2));
    return call<CatalogResults>(`/catalog/search?${params}`);
  },

  shop: (id: string, needs: string[], reshop = true) =>
    post<ShopOutcome>(`/mandates/${id}/shop`, { needs, reshop }),

  reconcile: (batchId: string) =>
    post<Record<string, unknown>>(`/payouts/${batchId}/reconcile`),

  /** Plain English to a checked, attacked, unsigned draft. */
  draft: (text: string) => post<Draft>("/mandates/draft", { text }),

  /** Sign a drafted mandate into the demo, replacing the default. */
  sign: (body: MandateBody) => post<Record<string, unknown>>("/demo/mandate", body),

  /** A red team run against the mandate, on a sandbox copy of it. */
  attack: (id: string, by: "strategy" | "model") =>
    post<AttackReport>(`/mandates/${id}/attack?by=${by}`),
};

/** Where an outside agent connects, as a person would paste it.
 *
 *  Never the dev proxy path: "/api/mcp" means nothing to Claude or ChatGPT.
 *  In development it is the local engine; deployed, it is the public API. */
export const MCP_URL = BASE.startsWith("http")
  ? `${BASE}/mcp`
  : BASE === "/api"
    ? "http://127.0.0.1:8000/mcp"
    : `${window.location.origin}/mcp`;

/** Decisions an outside agent made over MCP. The engine gives those
 *  attempts an `mcp_` id, which is the one field every view already has. */
export const viaMcp = (attemptId: string) => attemptId.startsWith("mcp_");
