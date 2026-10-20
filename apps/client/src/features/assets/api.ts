import { useMemo } from "react";
import type { components } from "@sallimbook/api-client";
import { nativeFinance } from "../../platform/nativeFinance";
import { useAuth } from "../auth/AuthProvider";
import type { AssetInput, AssetPatch, AssetQuery } from "./model";

export function useAssetsApi() {
  const { domainApi } = useAuth();
  return useMemo(
    () => ({
      list: (query: AssetQuery) =>
        domainApi.read(
          (client) => client.GET("/api/v1/assets", { params: { query } }),
          () => nativeFinance.listAssets(query),
        ),
      get: (id: string) =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/assets/{asset_id}", { params: { path: { asset_id: id } } }),
          () => nativeFinance.getAsset(id),
        ),
      create: (body: AssetInput) =>
        domainApi.write(
          (client) => client.POST("/api/v1/assets", { body }),
          () => nativeFinance.createAsset(body),
        ),
      update: (id: string, body: AssetPatch, version: number) =>
        domainApi.write(
          (client) =>
            client.PATCH("/api/v1/assets/{asset_id}", {
              body,
              params: { path: { asset_id: id }, header: { "If-Match": `"${version}"` } },
            }),
          () => nativeFinance.updateAsset(id, body, `"${version}"`),
        ),
      archive: (id: string, body: components["schemas"]["AssetArchive"], version: number) =>
        domainApi.write(
          (client) =>
            client.POST("/api/v1/assets/{asset_id}/archive", {
              body,
              params: { path: { asset_id: id }, header: { "If-Match": `"${version}"` } },
            }),
          () => nativeFinance.archiveAsset(id, body, `"${version}"`),
        ),
      delete: (id: string, version: number) =>
        domainApi.write(
          (client) =>
            client.DELETE("/api/v1/assets/{asset_id}", {
              params: { path: { asset_id: id }, header: { "If-Match": `"${version}"` } },
            }),
          () => nativeFinance.deleteAsset(id, `"${version}"`),
        ),
    }),
    [domainApi],
  );
}
