import { expect, test } from "@playwright/test";
import { formatSeoulDate, formatSeoulDateTime } from "../src/shared/format";

const legacy = (options: Intl.DateTimeFormatOptions) => (value: string) =>
  new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", ...options }).format(new Date(value));
test("Seoul formatters match the previous inline output and cross Seoul midnight", () => {
  for (const value of ["2026-09-30T14:59:59Z", "2026-09-30T15:00:00Z", "2024-02-29T00:00:00Z"]) {
    expect(formatSeoulDateTime(value)).toBe(
      legacy({ dateStyle: "medium", timeStyle: "short" })(value),
    );
    expect(formatSeoulDateTime(value, { seconds: true })).toBe(
      legacy({ dateStyle: "medium", timeStyle: "medium" })(value),
    );
    expect(formatSeoulDate(value)).toBe(legacy({ dateStyle: "medium" })(value));
  }
  expect(formatSeoulDate("2026-09-30T14:59:59Z")).not.toBe(formatSeoulDate("2026-09-30T15:00:00Z"));
});
test("unreadable timestamps show a fallback instead of throwing", () => {
  expect(formatSeoulDateTime("not-a-time")).toBe("시각 확인 필요");
  expect(formatSeoulDateTime("", { fallback: "확인되지 않음" })).toBe("확인되지 않음");
  expect(formatSeoulDate("2026-13-01")).toBe("날짜 확인 필요");
});
