import { useMemo } from "react";
import type { components } from "@sallimbook/api-client";
import { useAuth } from "../auth/AuthProvider";
import { nativeFinance } from "../../platform/nativeFinance";
import { cancellableNative } from "../../platform/cancellableNative";
type S = components["schemas"];
export function usePlanningApi() {
  const { domainApi } = useAuth();
  return useMemo(
    () => ({
      expected: (cursor?: string) =>
        domainApi.read(
          (c) =>
            c.GET("/api/v1/income-planning/expected", {
              params: { query: { cursor, limit: 200 } },
            }),
          () => nativeFinance.listExpectedIncome({ query: { cursor, limit: 200 } }),
        ),
      bonuses: (cursor?: string) =>
        domainApi.read(
          (c) =>
            c.GET("/api/v1/income-planning/bonuses", { params: { query: { cursor, limit: 200 } } }),
          () => nativeFinance.listBonusAwards({ query: { cursor, limit: 200 } }),
        ),
      saveExpected: (
        input: S["ExpectedInput"],
        source: S["ExpectedResponse"] | undefined,
        reason: string,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (c) =>
            source
              ? c.PUT("/api/v1/income-planning/expected/{record_id}", {
                  body: { ...input, reason },
                  params: {
                    path: { record_id: source.id },
                    header: { "If-Match": `"${source.version}"`, "Idempotency-Key": key },
                  },
                  signal,
                })
              : c.POST("/api/v1/income-planning/expected", {
                  body: input,
                  params: { header: { "Idempotency-Key": key } },
                  signal,
                }),
          () =>
            cancellableNative(signal, () =>
              source
                ? nativeFinance.changeExpectedIncome({
                    recordId: source.id,
                    input: { ...input, reason },
                    ifMatch: `"${source.version}"`,
                    idempotencyKey: key,
                  })
                : nativeFinance.createExpectedIncome({ input, idempotencyKey: key }),
            ),
        ),
      saveBonus: (
        input: S["BonusInput"],
        source: S["BonusResponse"] | undefined,
        reason: string,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (c) =>
            source
              ? c.PUT("/api/v1/income-planning/bonuses/{record_id}", {
                  body: { ...input, reason },
                  params: {
                    path: { record_id: source.id },
                    header: { "If-Match": `"${source.version}"`, "Idempotency-Key": key },
                  },
                  signal,
                })
              : c.POST("/api/v1/income-planning/bonuses", {
                  body: input,
                  params: { header: { "Idempotency-Key": key } },
                  signal,
                }),
          () =>
            cancellableNative(signal, () =>
              source
                ? nativeFinance.changeBonusAward({
                    recordId: source.id,
                    input: { ...input, reason },
                    ifMatch: `"${source.version}"`,
                    idempotencyKey: key,
                  })
                : nativeFinance.createBonusAward({ input, idempotencyKey: key }),
            ),
        ),
    }),
    [domainApi],
  );
}
