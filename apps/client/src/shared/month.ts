export function seoulMonth(date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
  }).formatToParts(date);
  return `${parts.find((part) => part.type === "year")!.value}-${parts.find((part) => part.type === "month")!.value}`;
}

export function isValidMonth(month: string): boolean {
  return /^(?!0000)\d{4}-(0[1-9]|1[0-2])$/.test(month);
}

export function formatMonth(month: string): string {
  return `${month.slice(0, 4)}년 ${Number(month.slice(5))}월`;
}

/** The month `delta` months from a valid "YYYY-MM", or null when it leaves years 0001-9999. */
export function shiftMonth(month: string, delta: number): string | null {
  if (!isValidMonth(month)) return null;
  const index = Number(month.slice(0, 4)) * 12 + (Number(month.slice(5)) - 1) + delta;
  const year = Math.floor(index / 12);
  if (year < 1 || year > 9999) return null;
  return `${String(year).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}`;
}
