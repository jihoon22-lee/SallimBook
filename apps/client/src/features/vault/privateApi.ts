import { useMemo } from "react";
import type { components } from "@sallimbook/api-client";
import { ApiError, requireWebAuth } from "../../platform/api";
import { useAuth } from "../auth/AuthProvider";

type S = components["schemas"];
const headers = (key: string, value: number) => {
  if (!Number.isSafeInteger(value) || value < 1) throw new ApiError(409, "VERSION_CONFLICT");
  return { "Idempotency-Key": key, "If-Match": `"${value}"` };
};

/** Opaque responses stay inside a mounted web operation. This adapter has no native fallback. */
export function usePrivateVaultApi() {
  const { domainApi } = useAuth();
  return useMemo(() => {
    const read: typeof domainApi.read = (web) => { requireWebAuth(); return domainApi.read(web); };
    const write: typeof domainApi.write = (web) => { requireWebAuth(); return domainApi.write(web); };
    return {
      reauthenticate: (password: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/auth/web/reauthenticate", { body: { password }, signal })),
      status: (signal: AbortSignal) => read((c) => c.GET("/api/v1/vault/status", { signal })),
      own: (signal: AbortSignal) => read((c) => c.GET("/api/v1/vault/wrappings/me", { signal })),
      recovery: (signal: AbortSignal) => read((c) => c.GET("/api/v1/vault/recovery-wrap", { signal })),
      card: (id: string, signal: AbortSignal) => read((c) => c.GET("/api/v1/cards/{card_id}/secret-envelope", { params: { path: { card_id: id } }, signal })),
      cardMetadata: (id: string, signal: AbortSignal) => read((c) => c.GET("/api/v1/cards/{card_id}", { params: { path: { card_id: id } }, signal })),
      offer: (id: string, signal: AbortSignal) => read((c) => c.GET("/api/v1/vault/shares/{offer_id}/wrapping", { params: { path: { offer_id: id } }, signal })),
      shares: (signal: AbortSignal, cursor?: string) => read((c) => c.GET("/api/v1/vault/shares", { params: { query: { limit: 200, cursor } }, signal })),
      members: (signal: AbortSignal) => read((c) => c.GET("/api/v1/household/members", { signal })),
      rotation: (id: string, signal: AbortSignal) => read((c) => c.GET("/api/v1/vault/rotations/{rotation_id}", { params: { path: { rotation_id: id } }, signal })),
      stagedOwn: (id: string, signal: AbortSignal) => read((c) => c.GET("/api/v1/vault/rotations/{rotation_id}/wrappings/me", { params: { path: { rotation_id: id } }, signal })),
      stagedCard: (rotationId: string, cardId: string, signal: AbortSignal) => read((c) => c.GET("/api/v1/vault/rotations/{rotation_id}/cards/{card_id}", { params: { path: { rotation_id: rotationId, card_id: cardId } }, signal })),
      initialize: (body: S["VaultInitialize"], key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/initialize", { body, params: { header: { "Idempotency-Key": key } }, signal })),
      rewrap: (body: S["VaultMemberRewrap"], version: number, key: string, signal: AbortSignal) => write((c) => c.PUT("/api/v1/vault/wrappings/me", { body, params: { header: headers(key, version) }, signal })),
      recover: (body: S["VaultRecover"], version: number, key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/recover", { body, params: { header: headers(key, version) }, signal })),
      saveCard: (id: string, body: S["CardEnvelopeInput"], version: number, key: string, signal: AbortSignal) => write((c) => c.PUT("/api/v1/cards/{card_id}/secret-envelope", { body, params: { path: { card_id: id }, header: headers(key, version) }, signal })),
      purge: (id: string, version: number, key: string, signal: AbortSignal) => write((c) => c.DELETE("/api/v1/cards/{card_id}/secret-envelope", { params: { path: { card_id: id }, header: headers(key, version) }, signal })),
      share: (body: S["VaultShareCreate"], version: number, key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/shares", { body, params: { header: headers(key, version) }, signal })),
      accept: (id: string, body: S["VaultKeyConfirmation"], version: number, key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/shares/{offer_id}/accept", { body, params: { path: { offer_id: id }, header: headers(key, version) }, signal })),
      cancelOffer: (id: string, version: number, key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/shares/{offer_id}/cancel", { body: {}, params: { path: { offer_id: id }, header: headers(key, version) }, signal })),
      revoke: (id: string, version: number, key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/members/{member_id}/revoke", { body: {}, params: { path: { member_id: id }, header: headers(key, version) }, signal })),
      startRotation: (reason: S["VaultRotationStart"]["reason"], version: number, key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/rotations", { body: { reason }, params: { header: headers(key, version) }, signal })),
      prepare: (id: string, body: S["VaultRotationPrepare"], version: number, key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/rotations/{rotation_id}/prepare", { body, params: { path: { rotation_id: id }, header: headers(key, version) }, signal })),
      stage: (id: string, cardId: string, body: S["VaultRotationCardWrite"], version: number, key: string, signal: AbortSignal) => write((c) => c.PUT("/api/v1/vault/rotations/{rotation_id}/cards/{card_id}", { body, params: { path: { rotation_id: id, card_id: cardId }, header: headers(key, version) }, signal })),
      finalize: (id: string, body: S["VaultKeyConfirmation"], version: number, key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/rotations/{rotation_id}/finalize", { body, params: { path: { rotation_id: id }, header: headers(key, version) }, signal })),
      abort: (id: string, version: number, key: string, signal: AbortSignal) => write((c) => c.POST("/api/v1/vault/rotations/{rotation_id}/abort", { body: {}, params: { path: { rotation_id: id }, header: headers(key, version) }, signal })),
    };
  }, [domainApi]);
}
export type PrivateVaultApi = ReturnType<typeof usePrivateVaultApi>;
