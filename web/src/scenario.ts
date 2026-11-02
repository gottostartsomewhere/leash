// The scripted run, so a demo is one click instead of eleven pieces of typing.
//
// The order is deliberate and every beat is load-bearing. Two of them depend
// on real wall-clock timing against the demo mandate's 60-second pace window,
// so the pauses are part of the script rather than pacing for comfort.
//
// Against the seeded mandate (500 total, 100 per item, 200 per counterparty,
// 6 charges per minute, office and hardware only) this produces six holds and
// five refusals.

export interface Beat {
  payee: string;
  category: string;
  amount: string;
  description: string;
  /** What a presenter should say while this row lands. */
  note: string;
  /** Milliseconds to wait before the next beat. */
  pause?: number;
}

export const SCENARIO: Beat[] = [
  {
    payee: "northwind",
    category: "office-supplies",
    amount: "40.00",
    description: "A4 paper, 5 reams",
    note: "Inside every rule. This is the normal case and it should look boring.",
    pause: 1100,
  },
  {
    payee: "globex",
    category: "furniture",
    amount: "150.00",
    description: "Task chair, adjustable arms",
    note: "Over the per-item cap. Look at what it offers back: 100.00 would clear.",
    pause: 1400,
  },
  {
    payee: "globex",
    category: "furniture",
    amount: "100.00",
    description: "Task chair, fixed arms instead",
    note: "The agent takes the counter-offer. A boundary, not a wall.",
    pause: 1200,
  },
  {
    payee: "acme_us",
    category: "furniture",
    amount: "75.00",
    description: "Desk organiser",
    note: "75 to Acme. Under the cap, so it clears.",
    pause: 1300,
  },
  {
    payee: "acme_eu",
    category: "furniture",
    amount: "75.00",
    description: "Monitor arm",
    note:
      "Same merchant, second receiver address, another 75. Two ordinary items. " +
      "Each clears the per-item check on its own. Only the cluster does not.",
    pause: 2600,
  },
  {
    payee: "initech",
    category: "electronics",
    amount: "60.00",
    description: "Bluetooth speaker",
    note: "Out of scope. No amount fixes being the wrong category, so nothing is offered.",
    pause: 1400,
  },
  {
    payee: "northwind",
    category: "office-supplies",
    amount: "20.00",
    description: "Pens",
    note: "Now it starts moving fast.",
    pause: 420,
  },
  {
    payee: "globex",
    category: "office-supplies",
    amount: "20.00",
    description: "Printer labels",
    note: "",
    pause: 420,
  },
  {
    payee: "initech",
    category: "office-supplies",
    amount: "20.00",
    description: "Business cards",
    note: "",
    pause: 420,
  },
  {
    payee: "acme_us",
    category: "office-supplies",
    amount: "20.00",
    description: "Notebooks",
    note: "Seventh hold inside a minute. The pace limit, on its own.",
    pause: 1600,
  },
  {
    payee: "globex",
    category: "furniture",
    amount: "500.00",
    description: "Standing desk",
    note:
      "Every check runs on every attempt, so a refusal names every reason " +
      "rather than the first one it found.",
  },
];

export const SCENARIO_SHAPE = {
  attempts: SCENARIO.length,
  expectedHolds: 6,
  expectedRefusals: 5,
} as const;
