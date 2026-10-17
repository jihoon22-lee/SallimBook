import { useMemo } from "react";
import { nativeVault } from "../../platform/nativeVault";
import { useAuth } from "../auth/AuthProvider";

/** Only public vault metadata belongs in the overview's React state. */
export function useVaultOverviewApi() {
  const { domainApi } = useAuth();
  return useMemo(() => ({
    status: () => domainApi.read((client) => client.GET("/api/v1/vault/status"), () => nativeVault.getVaultStatus()),
    shares: (cursor?: string) => {
      const query = { limit: 50, ...(cursor ? { cursor } : {}) };
      return domainApi.read((client) => client.GET("/api/v1/vault/shares", { params: { query } }), () => nativeVault.listVaultShares({ query }));
    },
    rotation: (rotationId: string) => domainApi.read((client) => client.GET("/api/v1/vault/rotations/{rotation_id}", { params: { path: { rotation_id: rotationId } } }), () => nativeVault.getVaultRotation({ rotationId })),
  }), [domainApi]);
}
