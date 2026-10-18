import type { components } from "@sallimbook/api-client";
import { useMemo } from "react";
import { nativeAudit } from "../../platform/nativeAudit";
import { cancellableNative } from "../../platform/cancellableNative";
import { useAuth } from "../auth/AuthProvider";
import type { AuditQuery } from "./model";

export function useAuditApi() {
  const { domainApi } = useAuth();
  return useMemo(() => ({
    list: (query: AuditQuery, signal?: AbortSignal) => domainApi.read<components["schemas"]["AuditListResponse"]>(
      (client) => client.GET("/api/v1/audit-events", { params: { query }, signal }),
      () => cancellableNative(signal, () => nativeAudit.list({ query })),
    ),
  }), [domainApi]);
}
