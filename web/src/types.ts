// Mirrors of what the API actually returns. Amounts arrive as integer minor
// units, exactly as the engine holds them, so nothing is rounded on the way
// to the screen.

export type Outcome = "pass" | "fail" | "skip";
export type Severity = "medium" | "high" | "critical";

export interface CheckRow {
  code: string;
  outcome: Outcome;
  severity: Severity;
  detail: string;
  evidence: Record<string, unknown>;
}

export interface DecisionRow {
  attempt_id: string;
  mandate_id: string;
  verdict: "allow" | "block";
  evaluated_at: string;
  reason: string;
  amount: number;
  currency: string;
  payee: string;
  category: string;
  available: number;
  remaining_after: number;
  max_allowable: number;
  failed_codes: string[];
  trace: CheckRow[];
}

export interface MandateTerms {
  per_item_limit: number | null;
  per_payee_limit: number | null;
  allowed_categories: string[] | null;
  allowed_payees: string[] | null;
  velocity: {
    window_seconds: number;
    max_count: number | null;
    max_amount: number | null;
  } | null;
  concentration_max_share: number | null;
  concentration_floor: number | null;
  structuring_window_seconds: number;
  starts_at: string;
  ends_at: string;
  revoked_at: string | null;
}

/** What the balance-only endpoints return (an attempt, a revoke, a payout). */
export interface Balances {
  mandate_id: string;
  agent_id: string;
  status: "active" | "revoked" | "expired";
  currency: string;
  total_limit: number;
  committed: number;
  held: number;
  available: number;
  attempts: number;
  blocked: number;
}

/** What `GET /mandates/{id}` returns: balances plus the authority itself. */
export interface MandateSummary extends Balances {
  terms: MandateTerms;
}

export type ChargeState = "pending" | "settled" | "released" | "failed";

export interface Charge {
  id: string;
  payee: string;
  category: string;
  amount: { minor: number; currency: string; display: string };
  state: ChargeState;
  created_at: string;
  description: string;
}

export interface Payee {
  id: string;
  name: string;
  email: string;
  counterparty: string;
}

export interface Health {
  status: string;
  gateway: string;
  paypal_configured: boolean;
}

export interface PayoutItemResult {
  charge_id: string;
  status: string;
  receiver: string;
  amount: number;
  currency: string;
  error: string | null;
}

export interface PayoutResultRow {
  batch_id: string;
  status: string;
  items: PayoutItemResult[];
  [key: string]: unknown;
}

export interface PayoutOutcome {
  batch: PayoutResultRow;
  settled_charge_ids: string[];
  failed_charge_ids: string[];
  summary: Balances;
}

export interface AttemptBody {
  payee: string;
  category: string;
  amount: string | number;
  currency?: string;
  description?: string;
  idempotency_key?: string;
}

/** What a decision looks like once the charge it produced is joined onto it. */
export interface LogRow extends DecisionRow {
  kind: "decision";
  sequence: number;
  charge_state: ChargeState | null;
  charge_id: string | null;
}

/** The expandable band underneath a decision, carrying the rule evidence. */
export interface EvidenceRow {
  kind: "evidence";
  attempt_id: string;
  parent: LogRow;
}

export type GridRow = LogRow | EvidenceRow;
