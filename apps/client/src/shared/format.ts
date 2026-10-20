const seoul = { timeZone: "Asia/Seoul" } as const;
const dateTime = new Intl.DateTimeFormat("ko-KR", {
  ...seoul,
  dateStyle: "medium",
  timeStyle: "short",
});
const dateTimeSeconds = new Intl.DateTimeFormat("ko-KR", {
  ...seoul,
  dateStyle: "medium",
  timeStyle: "medium",
});
const dateOnly = new Intl.DateTimeFormat("ko-KR", { ...seoul, dateStyle: "medium" });

/** Shows a stored UTC timestamp in Seoul time; an unreadable value never throws. */
export function formatSeoulDateTime(
  value: string,
  { seconds = false, fallback = "시각 확인 필요" }: { seconds?: boolean; fallback?: string } = {},
): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? (seconds ? dateTimeSeconds : dateTime).format(date)
    : fallback;
}

export function formatSeoulDate(value: string, fallback = "날짜 확인 필요"): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? dateOnly.format(date) : fallback;
}
