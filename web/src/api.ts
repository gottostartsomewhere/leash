import type {
  AttemptBody,
  Balances,
  Charge,
  DecisionRow,
  Health,
  MandateSummary,
  Payee,
  PayoutOutcome,
} from "./types";

const BASE = "/api";

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
    throw new ApiError("cannot reach the engine on 127.0.0.1:8000", 0);
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
};
