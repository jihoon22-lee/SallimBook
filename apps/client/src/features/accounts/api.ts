import { useMemo } from "react";
import { nativeFinance } from "../../platform/nativeFinance";
import { useAuth } from "../auth/AuthProvider";
import type { AccountInput, AccountPatch, AccountQuery } from "./model";
export function useAccountsApi() {
  const { domainApi } = useAuth();
  return useMemo(
    () => ({
      list: (query: AccountQuery) =>
        domainApi.read(
          (client) => client.GET("/api/v1/accounts", { params: { query } }),
          () => nativeFinance.listAccounts(query),
        ),
      get: (id: string) =>
        domainApi.read(
          (client) =>
            client.GET("/api/v1/accounts/{account_id}", { params: { path: { account_id: id } } }),
          () => nativeFinance.getAccount(id),
        ),
      create: (body: AccountInput) =>
        domainApi.write(
          (client) => client.POST("/api/v1/accounts", { body }),
          () => nativeFinance.createAccount(body),
        ),
      update: (id: string, body: AccountPatch, version: number) =>
        domainApi.write(
          (client) =>
            client.PATCH("/api/v1/accounts/{account_id}", {
              body,
              params: { path: { account_id: id }, header: { "If-Match": `"${version}"` } },
            }),
          () => nativeFinance.updateAccount(id, body, `"${version}"`),
        ),
      delete: (id: string, version: number) =>
        domainApi.write(
          (client) =>
            client.DELETE("/api/v1/accounts/{account_id}", {
              params: { path: { account_id: id }, header: { "If-Match": `"${version}"` } },
            }),
          () => nativeFinance.deleteAccount(id, `"${version}"`),
        ),
    }),
    [domainApi],
  );
}
