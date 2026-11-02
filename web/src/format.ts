// Display only. The integers that arrive from the engine are never turned into
// floats and never arithmetic'd here; the server owns the maths.

const EXPONENTS: Record<string, number> = {
  JPY: 0,
  KRW: 0,
  VND: 0,
  CLP: 0,
  ISK: 0,
  BHD: 3,
  JOD: 3,
  KWD: 3,
  OMR: 3,
  TND: 3,
};

export const exponent = (currency: string) => EXPONENTS[currency] ?? 2;

/** `12345` USD becomes `123.45`. String maths, so no float ever sees it. */
export function money(minor: number, currency = "USD"): string {
  const places = exponent(currency);
  const sign = minor < 0 ? "-" : "";
  const digits = Math.abs(minor).toString().padStart(places + 1, "0");
  if (places === 0) return `${sign}${withGroups(digits)}`;
  const whole = digits.slice(0, -places);
  const frac = digits.slice(-places);
  return `${sign}${withGroups(whole)}.${frac}`;
}

function withGroups(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export const withCurrency = (minor: number, currency = "USD") =>
  `${money(minor, currency)} ${currency}`;

export function clockTime(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "--:--:--";
  return at.toLocaleTimeString("en-GB", { hour12: false });
}

/** `per_item_limit` reads as `Per item limit` in a header or a chip. */
export function label(code: string): string {
  const words = code.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Capitalise a sentence without touching the rest of it, so identifiers and
 *  amounts inside it keep the case they are supposed to have. */
export function sentence(text: string): string {
  const trimmed = text.trim();
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

export const percent = (share: number) => `${Math.round(share * 100)}%`;
