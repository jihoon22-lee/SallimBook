import { useMemo } from "react";
import { nativeFinance } from "../../../platform/nativeFinance";
import { cancellableNative } from "../../../platform/cancellableNative";
import { ApiError } from "../../../platform/api";
import { useAuth } from "../../auth/AuthProvider";
import { comparisonIdentity } from "./model";
import type { ComparisonQuery, TrendQuery } from "./model";
export function useAssetComparisonApi() {
  const { domainApi } = useAuth();
  return useMemo(() => {
    const comparison = (query: ComparisonQuery, signal?: AbortSignal) =>
      domainApi.read(
        (client) => client.GET("/api/v1/asset-comparison", { params: { query }, signal }),
        () => cancellableNative(signal, () => nativeFinance.getAssetComparison({ query })),
      );
    return {
      comparison,
      trend: (query: TrendQuery, signal?: AbortSignal) =>
        domainApi.read(
          (client) => client.GET("/api/v1/asset-trends", { params: { query }, signal }),
          () => cancellableNative(signal, () => nativeFinance.getAssetTrends({ query })),
        ),
      all: async (query: ComparisonQuery, signal?: AbortSignal) => {
        const first = await comparison({ ...query, limit: 200 }, signal);
        const items = [...first.items];
        const identity = comparisonIdentity(first);
        let cursor = first.next_cursor;
        const seen = new Set<string>();
        while (cursor) {
          if (signal?.aborted) throw new ApiError(0, "REQUEST_CANCELLED");
          if (seen.has(cursor)) throw new ApiError(0, "REQUEST_FAILED");
          seen.add(cursor);
          const next = await comparison({ ...query, limit: 200, cursor }, signal);
          if (comparisonIdentity(next) !== identity) throw new ApiError(409, "REVISION_CONFLICT");
          for (const item of next.items) {
            if (items.some((row) => row.asset_id === item.asset_id))
              throw new ApiError(409, "REVISION_CONFLICT");
            items.push(item);
          }
          cursor = next.next_cursor;
        }
        return { ...first, items, next_cursor: null };
      },
    };
  }, [domainApi]);
}
