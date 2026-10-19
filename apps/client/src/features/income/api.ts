import { useMemo } from "react";
import type { components, operations } from "@sallimbook/api-client";
import { nativeFinance } from "../../platform/nativeFinance";
import { cancellableNative } from "../../platform/cancellableNative";
import { useAuth } from "../auth/AuthProvider";
import type {
  IncomeQuery,
  IncomeInput,
  IncomePatch,
  IncomeReturn,
  IncomeConversion,
} from "./model";
export function useIncomeApi() {
  const { domainApi } = useAuth();
  return useMemo(
    () => ({
      list: (query: IncomeQuery) =>
        domainApi.read(
          (client) => client.GET("/api/v1/income", { params: { query } }),
          () => nativeFinance.listIncome({ query }),
        ),
      summary: (month: string) =>
        domainApi.read(
          (client) => client.GET("/api/v1/income/summary", { params: { query: { month } } }),
          () => nativeFinance.incomeSummary({ query: { month } }),
        ),
      get: (id: string) =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/income/{record_id}", { params: { path: { record_id: id } } }),
          () => nativeFinance.getIncome({ recordId: id }),
        ),
      history: (id: string, cursor?: number) =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/income/{record_id}/history", {
              params: {
                path: { record_id: id },
                query: { limit: 50, ...(cursor === undefined ? {} : { cursor }) },
              },
            }),
          () =>
            nativeFinance.incomeHistory({
              recordId: id,
              query: { limit: 50, ...(cursor === undefined ? {} : { cursor }) },
            }),
        ),
      duplicates: (query: operations["incomeDuplicateCandidates"]["parameters"]["query"]) =>
        domainApi.read(
          (client) => client.GET("/api/v1/income/duplicates", { params: { query } }),
          () => nativeFinance.incomeDuplicateCandidates({ query }),
        ),
      create: (input: IncomeInput, key: string, signal: AbortSignal) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/income", {
              body: input,
              params: { header: { "Idempotency-Key": key } },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.createIncome({ input, idempotencyKey: key }),
            ),
        ),
      correct: (
        id: string,
        input: IncomePatch,
        version: number,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.PATCH("/api/v1/income/{record_id}", {
              body: input,
              params: {
                path: { record_id: id },
                header: { "Idempotency-Key": key, "If-Match": `"${version}"` },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.correctIncome({
                recordId: id,
                input,
                ifMatch: `"${version}"`,
                idempotencyKey: key,
              }),
            ),
        ),
      void: (
        id: string,
        input: components["schemas"]["IncomeVoid"],
        version: number,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/income/{record_id}/void", {
              body: input,
              params: {
                path: { record_id: id },
                header: { "Idempotency-Key": key, "If-Match": `"${version}"` },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.voidIncome({
                recordId: id,
                input,
                ifMatch: `"${version}"`,
                idempotencyKey: key,
              }),
            ),
        ),
      return: (
        id: string,
        input: IncomeReturn,
        version: number,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/income/{record_id}/returns", {
              body: input,
              params: {
                path: { record_id: id },
                header: { "Idempotency-Key": key, "If-Match": `"${version}"` },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.returnIncome({
                recordId: id,
                input,
                ifMatch: `"${version}"`,
                idempotencyKey: key,
              }),
            ),
        ),
      convert: (input: IncomeConversion, key: string, signal: AbortSignal) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/income/convert", {
              body: input,
              params: { header: { "Idempotency-Key": key } },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.convertIncomePrecision({ input, idempotencyKey: key }),
            ),
        ),
    }),
    [domainApi],
  );
}
