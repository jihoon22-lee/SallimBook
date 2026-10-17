import { useMemo } from "react";
import type { components } from "@sallimbook/api-client";
import { nativeFinance } from "../../platform/nativeFinance";
import { useAuth } from "../auth/AuthProvider";
import type { CardInput, CardPatch, CardQuery } from "./model";
export function useCardsApi() {
  const { domainApi } = useAuth();
  return useMemo(() => ({
    list: (query: CardQuery) => domainApi.read((client) => client.GET("/api/v1/cards", { params: { query } }), () => nativeFinance.listCards({ query })),
    get: (id: string) => domainApi.read((client) => client.GET("/api/v1/cards/{card_id}", { params: { path: { card_id: id } } }), () => nativeFinance.getCard({ cardId: id })),
    create: (input: CardInput) => domainApi.write((client) => client.POST("/api/v1/cards", { body: input }), () => nativeFinance.createCard({ input })),
    update: (id: string, input: CardPatch, version: number) => domainApi.write((client) => client.PATCH("/api/v1/cards/{card_id}", { body: input, params: { path: { card_id: id }, header: { "If-Match": `"${version}"` } } }), () => nativeFinance.updateCard({ cardId: id, input, ifMatch: `"${version}"` })),
    archive: (id: string, input: components["schemas"]["CardArchive"], version: number) => domainApi.write((client) => client.POST("/api/v1/cards/{card_id}/archive", { body: input, params: { path: { card_id: id }, header: { "If-Match": `"${version}"` } } }), () => nativeFinance.archiveCard({ cardId: id, input, ifMatch: `"${version}"` })),
    delete: (id: string, version: number) => domainApi.write((client) => client.DELETE("/api/v1/cards/{card_id}", { params: { path: { card_id: id }, header: { "If-Match": `"${version}"` } } }), () => nativeFinance.deleteCard({ cardId: id, ifMatch: `"${version}"` })),
  }), [domainApi]);
}
