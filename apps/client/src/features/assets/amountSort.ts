/** Server KRW strings only. Missing values stay last in either direction. */
export function compareAmounts(a: string | null, b: string | null, absolute = false): number {
  if (a === null) return b === null ? 0 : 1;
  if (b === null) return -1;
  let left = BigInt(a),
    right = BigInt(b);
  if (absolute) {
    left = left < 0n ? -left : left;
    right = right < 0n ? -right : right;
  }
  return left > right ? -1 : left < right ? 1 : 0;
}
