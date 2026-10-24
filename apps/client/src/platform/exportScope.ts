import type { components } from "@sallimbook/api-client";
import { ApiError } from "./api";
export type ReadableExport = components["schemas"]["ReadableExport"];
export const exportDomains: Record<ReadableExport["domains"][number], string> = {
  assets: "자산",
  accounts: "계좌",
  cards: "카드",
  income: "수입",
  fixed: "고정 납부",
  insurance: "보험·의료",
  homecare: "가전·소모품",
};
export function validExportDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
/** Copy only the generated request's reviewed fields across the native boundary. */
export function readableSelection(value: unknown): ReadableExport {
  const invalid = (): never => {
    throw new ApiError(422, "VALIDATION_ERROR");
  };
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    return invalid();
  const input = value as Record<string, unknown>;
  if (
    Object.keys(input).some(
      (key) => !["domains", "from_date", "through_date", "annual_year"].includes(key),
    )
  )
    return invalid();
  const domains = input.domains;
  if (
    !Array.isArray(domains) ||
    domains.length < 1 ||
    domains.length > 7 ||
    domains.some((domain) => typeof domain !== "string" || !Object.hasOwn(exportDomains, domain)) ||
    new Set(domains).size !== domains.length
  )
    return invalid();
  for (const field of ["from_date", "through_date"])
    if (input[field] != null && !validExportDate(input[field])) return invalid();
  const from = input.from_date as string | null | undefined;
  const through = input.through_date as string | null | undefined;
  if (from && through && from > through) return invalid();
  const year = input.annual_year;
  if (
    year != null &&
    (typeof year !== "number" ||
      !Number.isInteger(year) ||
      year < 1 ||
      year > 9999 ||
      !domains.includes("insurance"))
  )
    return invalid();
  return {
    domains: [...domains] as ReadableExport["domains"],
    ...(from != null ? { from_date: from } : {}),
    ...(through != null ? { through_date: through } : {}),
    ...(year != null ? { annual_year: year as number } : {}),
  };
}
