/** The one won-amount grammar for typed input; the server keeps the final say on amounts. */
export type KrwInputResult =
  { ok: true; krw: string } | { ok: false; reason: "empty" | "format" | "too_long" };

export const krwMessages = {
  empty: "금액을 입력해 주세요.",
  format:
    "원 단위 숫자로 입력해 주세요. 세 자리마다 쉼표를 쓸 수 있지만 소수점·부호는 쓸 수 없어요.",
  too_long: "금액은 20자리 이하로 입력해 주세요.",
  zero: "0원보다 큰 금액을 입력해 주세요.",
} as const;

// Groups must be exact thousands; "35,00,000" or "1,5" are refused rather than reread.
const PLAIN = /^\d+$/;
const COMMA_GROUPS = /^[1-9]\d{0,2}(?:,\d{3})+$/;
const SPACE_GROUPS = /^[1-9]\d{0,2}(?: \d{3})+$/;

export function parseKrwInput(value: string): KrwInputResult {
  const text = value.normalize("NFKC").trim();
  if (!text) return { ok: false, reason: "empty" };
  const body = text.replace(/\s*원$/, "");
  if (!PLAIN.test(body) && !COMMA_GROUPS.test(body) && !SPACE_GROUPS.test(body))
    return { ok: false, reason: "format" };
  const digits = body.replace(/[, ]/g, "");
  if (digits.length > 20) return { ok: false, reason: "too_long" };
  return { ok: true, krw: BigInt(digits).toString() };
}

export function krwFieldError(
  value: string,
  rule: { required: boolean; positive: boolean },
): string | null {
  const result = parseKrwInput(value);
  if (!result.ok)
    return result.reason === "empty" && !rule.required ? null : krwMessages[result.reason];
  return rule.positive && result.krw === "0" ? krwMessages.zero : null;
}
