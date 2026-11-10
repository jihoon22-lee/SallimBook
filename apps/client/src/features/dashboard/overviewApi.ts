import { useCallback, useMemo } from "react";
import type { components } from "@sallimbook/api-client";
import { nativeFinance } from "../../platform/nativeFinance";
import { cancellableNative } from "../../platform/cancellableNative";
import { useAuth } from "../auth/AuthProvider";
import { useResource } from "../finance/queries";

export type HouseholdOverview = components["schemas"]["HouseholdOverviewResponse"];
export type HouseholdTrends = components["schemas"]["HouseholdTrendsResponse"];
export type InsuranceSummary = components["schemas"]["InsuranceSummaryResponse"];
export type HoldingGroup = components["schemas"]["HoldingGroup"];
export type OverviewResource = ReturnType<typeof useHouseholdOverview>;

export const holdingGroups: Record<HoldingGroup, { label: string; to: string }> = {
  accounts: { label: "계좌·연금", to: "/accounts" },
  financial: { label: "투자·금융 자산", to: "/assets?category=financial" },
  real_estate: { label: "부동산", to: "/assets?category=real_estate" },
  deposit: { label: "보증금", to: "/assets?category=deposit" },
  loan: { label: "대출", to: "/assets?category=loan" },
  other: { label: "기타 자산·부채", to: "/assets?category=other" },
};

export function useOverviewApi() {
  const { domainApi } = useAuth();
  return useMemo(
    () => ({
      overview: (month: string, signal?: AbortSignal) =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/household-overview", { params: { query: { month } }, signal }),
          () =>
            cancellableNative(signal, () => nativeFinance.householdOverview({ query: { month } })),
        ),
      trends: (to: string, months: number, signal?: AbortSignal) =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/household-trends", { params: { query: { to, months } }, signal }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.householdTrends({ query: { to, months } }),
            ),
        ),
      insurance: (signal?: AbortSignal) =>
        domainApi.read(
          (client) => client.GET("/api/v1/insurance/summary", { signal }),
          () => cancellableNative(signal, () => nativeFinance.insuranceSummary()),
        ),
    }),
    [domainApi],
  );
}

/** One read for the household status; the server picks each item's latest entered amount. */
export function useHouseholdOverview(month: string) {
  const api = useOverviewApi();
  return useResource(useCallback(() => api.overview(month), [api, month]));
}

/** Month-by-month totals and plan estimates ending at `to`; read-only like the status itself. */
export function useHouseholdTrends(to: string, months: number) {
  const api = useOverviewApi();
  return useResource(useCallback(() => api.trends(to, months), [api, to, months]));
}

/** Premiums paid (entered and estimated) against benefits actually received. */
export function useInsuranceSummary() {
  const api = useOverviewApi();
  return useResource(useCallback(() => api.insurance(), [api]));
}
