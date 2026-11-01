import { useMemo } from "react";
import type { components, operations } from "@sallimbook/api-client";
import { nativeFinance } from "../../platform/nativeFinance";
import { cancellableNative } from "../../platform/cancellableNative";
import { useAuth } from "../auth/AuthProvider";
type S = components["schemas"];
export function useExpensePlanApi() {
  const { domainApi } = useAuth();
  return useMemo(
    () => ({
      rules: (query: NonNullable<operations["listExpensePlans"]["parameters"]["query"]> = {}) =>
        domainApi.read(
          (client) => client.GET("/api/v1/expense-plans", { params: { query } }),
          () => nativeFinance.listExpensePlans({ query }),
        ),
      rule: (id: string) =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/expense-plans/{plan_id}", { params: { path: { plan_id: id } } }),
          () => nativeFinance.getExpensePlan({ planId: id }),
        ),
      createRule: (input: S["PlanCreate"], key: string, signal: AbortSignal) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/expense-plans", {
              body: input,
              params: { header: { "Idempotency-Key": key } },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.createExpensePlan({ input, idempotencyKey: key }),
            ),
        ),
      changeRule: (
        id: string,
        input: S["PlanChange"],
        version: number,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.PATCH("/api/v1/expense-plans/{plan_id}", {
              body: input,
              params: {
                path: { plan_id: id },
                header: { "Idempotency-Key": key, "If-Match": `"${version}"` },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.changeExpensePlan({
                planId: id,
                input,
                ifMatch: `"${version}"`,
                idempotencyKey: key,
              }),
            ),
        ),
      endRule: (
        id: string,
        input: S["RuleEnd"],
        version: number,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/expense-plans/{plan_id}/end", {
              body: input,
              params: {
                path: { plan_id: id },
                header: { "Idempotency-Key": key, "If-Match": `"${version}"` },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.endExpensePlan({
                planId: id,
                input,
                ifMatch: `"${version}"`,
                idempotencyKey: key,
              }),
            ),
        ),
      deleteRule: (id: string, version: number, key: string, signal: AbortSignal) =>
        domainApi.write(
          (client) =>
            client.DELETE("/api/v1/expense-plans/{plan_id}", {
              params: {
                path: { plan_id: id },
                header: { "Idempotency-Key": key, "If-Match": `"${version}"` },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.deleteExpensePlan({
                planId: id,
                ifMatch: `"${version}"`,
                idempotencyKey: key,
              }),
            ),
        ),
      summary: () =>
        domainApi.read(
          (client) => client.GET("/api/v1/expense-plan-summary"),
          () => nativeFinance.expensePlanSummary({}),
        ),
    }),
    [domainApi],
  );
}
