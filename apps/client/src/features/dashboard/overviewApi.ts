import { useCallback, useMemo } from "react";
import type { components } from "@sallimbook/api-client";
import { nativeFinance } from "../../platform/nativeFinance";
import { cancellableNative } from "../../platform/cancellableNative";
import { useAuth } from "../auth/AuthProvider";
import { useResource } from "../finance/queries";

export type HouseholdOverview = components["schemas"]["HouseholdOverviewResponse"];
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
    }),
    [domainApi],
  );
}

/** One read for the household status; the server picks each item's latest entered amount. */
export function useHouseholdOverview(month: string) {
  const api = useOverviewApi();
  return useResource(useCallback(() => api.overview(month), [api, month]));
}
