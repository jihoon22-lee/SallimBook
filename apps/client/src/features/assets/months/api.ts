import { useMemo } from "react";
import type { components, operations } from "@sallimbook/api-client";
import { nativeFinance } from "../../../platform/nativeFinance";
import { cancellableNative } from "../../../platform/cancellableNative";
import { ApiError } from "../../../platform/api";
import { useAuth } from "../../auth/AuthProvider";
import type { MonthRecord } from "./model";
type PageQuery = NonNullable<operations["getAssetMonth"]["parameters"]["query"]>;
type HistoryQuery = NonNullable<operations["listAssetMonthRevisions"]["parameters"]["query"]>;
export function useAssetMonthsApi() {
  const { domainApi } = useAuth();
  return useMemo(() => {
    const page = (
      month: string,
      query: PageQuery = {},
      signal?: AbortSignal,
      revisionNo?: number,
    ) =>
      domainApi.read(
        (client) =>
          revisionNo === undefined
            ? client.GET("/api/v1/asset-months/{month}", {
                params: { path: { month }, query },
                signal,
              })
            : client.GET("/api/v1/asset-months/{month}/revisions/{revision_no}", {
                params: { path: { month, revision_no: revisionNo }, query },
                signal,
              }),
        () =>
          cancellableNative(signal, () =>
            revisionNo === undefined
              ? nativeFinance.getAssetMonth({ month, query })
              : nativeFinance.getAssetMonthRevision({ month, revisionNo, query }),
          ),
      );
    const history = (month: string, query: HistoryQuery = {}, signal?: AbortSignal) =>
      domainApi.read(
        (client) =>
          client.GET("/api/v1/asset-months/{month}/revisions", {
            params: { path: { month }, query },
            signal,
          }),
        () =>
          cancellableNative(signal, () => nativeFinance.listAssetMonthRevisions({ month, query })),
      );
    async function all(
      month: string,
      signal?: AbortSignal,
      revisionNo?: number,
    ): Promise<MonthRecord> {
      const first = await page(month, { limit: 200 }, signal, revisionNo);
      const values = [...first.values];
      let cursor = first.next_cursor;
      const seen = new Set<string>();
      while (cursor) {
        if (signal?.aborted) throw new ApiError(0, "REQUEST_CANCELLED");
        if (seen.has(cursor)) throw new ApiError(0, "REQUEST_FAILED");
        seen.add(cursor);
        const next = await page(month, { limit: 200, cursor }, signal, revisionNo);
        if (next.revision_id !== first.revision_id || next.version !== first.version)
          throw new ApiError(409, "REVISION_CONFLICT");
        for (const value of next.values) {
          if (values.some((row) => row.asset_id === value.asset_id))
            throw new ApiError(409, "VALUE_CONFLICT");
          values.push(value);
        }
        cursor = next.next_cursor;
      }
      return { ...first, values, next_cursor: null };
    }
    return {
      all,
      history,
      draft: (
        month: string,
        body: components["schemas"]["MonthDraft"],
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/asset-months/{month}/draft", {
              body,
              params: { path: { month }, header: { "Idempotency-Key": key } },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.createAssetMonthDraft({ month, input: body, idempotencyKey: key }),
            ),
        ),
      update: (
        month: string,
        assetId: string,
        body: components["schemas"]["MonthValueUpdate"],
        version: number,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.PATCH("/api/v1/asset-months/{month}/values/{asset_id}", {
              body,
              params: {
                path: { month, asset_id: assetId },
                header: { "If-Match": `"${version}"` },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.updateAssetMonthValue({
                month,
                assetId,
                input: body,
                ifMatch: `"${version}"`,
              }),
            ),
        ),
      sync: (
        month: string,
        body: components["schemas"]["MonthScopeSync"],
        version: number,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/asset-months/{month}/sync-scope", {
              body,
              params: { path: { month }, header: { "If-Match": `"${version}"` } },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.synchronizeAssetMonthScope({
                month,
                input: body,
                ifMatch: `"${version}"`,
              }),
            ),
        ),
      confirm: (
        month: string,
        body: components["schemas"]["MonthConfirm"],
        version: number,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/asset-months/{month}/confirm", {
              body,
              params: {
                path: { month },
                header: { "If-Match": `"${version}"`, "Idempotency-Key": key },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.confirmAssetMonth({
                month,
                input: body,
                ifMatch: `"${version}"`,
                idempotencyKey: key,
              }),
            ),
        ),
      reopen: (
        month: string,
        body: components["schemas"]["MonthReopen"],
        version: number,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/asset-months/{month}/reopen", {
              body,
              params: {
                path: { month },
                header: { "If-Match": `"${version}"`, "Idempotency-Key": key },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.reopenAssetMonth({
                month,
                input: body,
                ifMatch: `"${version}"`,
                idempotencyKey: key,
              }),
            ),
        ),
      carry: (
        month: string,
        body: components["schemas"]["MonthCarryPrevious"],
        version: number,
        key: string,
        signal: AbortSignal,
      ) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/asset-months/{month}/carry-previous", {
              body,
              params: {
                path: { month },
                header: { "If-Match": `"${version}"`, "Idempotency-Key": key },
              },
              signal,
            }),
          () =>
            cancellableNative(signal, () =>
              nativeFinance.carryPreviousAssetMonth({
                month,
                input: body,
                ifMatch: `"${version}"`,
                idempotencyKey: key,
              }),
            ),
        ),
    };
  }, [domainApi]);
}
