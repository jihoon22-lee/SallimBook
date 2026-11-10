const KRW = /^(0|-?[1-9][0-9]{0,19})$/;

/**
 * "6억 3,847만원" for reading a large amount at a glance, rounded to 만원. The exact won amount
 * stays the source: show it beside this or in the same element's title.
 */
export function formatKrwShort(value: string | null): string {
  if (value === null) return "미입력";
  if (!KRW.test(value)) return "금액 확인 필요";
  const amount = BigInt(value);
  const size = amount < 0n ? -amount : amount;
  if (size < 10_000n) return `${amount.toLocaleString("ko-KR")}원`;
  const man = (size + 5_000n) / 10_000n;
  const eok = man / 10_000n;
  const rest = man % 10_000n;
  const parts = [
    eok > 0n ? `${eok.toLocaleString("ko-KR")}억` : "",
    rest > 0n ? `${rest.toLocaleString("ko-KR")}만` : "",
  ].filter(Boolean);
  return `${amount < 0n ? "-" : ""}${parts.join(" ")}원`;
}

/** A signed change such as "+412만원"; zero has no sign. */
export function formatKrwChange(value: string): string {
  const text = formatKrwShort(value);
  return KRW.test(value) && BigInt(value) > 0n ? `+${text}` : text;
}

/** Exact difference of two decimal KRW strings, for display only. */
export function krwDifference(later: string, earlier: string): string | null {
  return KRW.test(later) && KRW.test(earlier) ? (BigInt(later) - BigInt(earlier)).toString() : null;
}

/** A share of `whole` as a CSS percentage; layout only, never shown as a number. */
export function sharePercent(part: string, whole: string): number {
  if (!KRW.test(part) || !KRW.test(whole)) return 0;
  const total = BigInt(whole);
  const size = BigInt(part) < 0n ? -BigInt(part) : BigInt(part);
  if (total <= 0n) return 0;
  return Math.min(100, Number((size * 10_000n) / total) / 100);
}
