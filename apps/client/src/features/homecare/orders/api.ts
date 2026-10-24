import { useMemo } from "react";
import { useAuth } from "../../auth/AuthProvider";
import { nativeFinance } from "../../../platform/nativeFinance";
import { cancellableNative } from "../../../platform/cancellableNative";
export function usePurchaseApi() {
  const { domainApi } = useAuth();
  return useMemo(
    () => ({
      getPurchasePlan: (
        options: Parameters<typeof nativeFinance.getPurchasePlan>[0],
        signal?: AbortSignal,
      ) =>
        domainApi.read(
          (c) =>
            c.GET("/api/v1/homecare/purchase-plan", { signal, params: { query: options.query } }),
          () => cancellableNative(signal, () => nativeFinance.getPurchasePlan(options)),
        ),
      listConsumableOrders: (
        options: Parameters<typeof nativeFinance.listConsumableOrders>[0],
        signal?: AbortSignal,
      ) =>
        domainApi.read(
          (c) => c.GET("/api/v1/consumable-orders", { signal, params: { query: options.query } }),
          () => cancellableNative(signal, () => nativeFinance.listConsumableOrders(options)),
        ),
      createConsumableOrder: (
        options: Parameters<typeof nativeFinance.createConsumableOrder>[0],
        signal?: AbortSignal,
      ) =>
        domainApi.write(
          (c) =>
            c.POST("/api/v1/consumable-orders", {
              signal,
              params: { header: { "Idempotency-Key": options.idempotencyKey } },
              body: options.input,
            }),
          () => cancellableNative(signal, () => nativeFinance.createConsumableOrder(options)),
        ),
      getConsumableOrder: (
        options: Parameters<typeof nativeFinance.getConsumableOrder>[0],
        signal?: AbortSignal,
      ) =>
        domainApi.read(
          (c) =>
            c.GET("/api/v1/consumable-orders/{order_id}", {
              signal,
              params: { path: { order_id: options.orderId } },
            }),
          () => cancellableNative(signal, () => nativeFinance.getConsumableOrder(options)),
        ),
      updateConsumableOrder: (
        options: Parameters<typeof nativeFinance.updateConsumableOrder>[0],
        signal?: AbortSignal,
      ) =>
        domainApi.write(
          (c) =>
            c.PATCH("/api/v1/consumable-orders/{order_id}", {
              signal,
              params: {
                path: { order_id: options.orderId },
                header: { "If-Match": options.ifMatch },
              },
              body: options.input,
            }),
          () => cancellableNative(signal, () => nativeFinance.updateConsumableOrder(options)),
        ),
      submitConsumableOrder: (
        options: Parameters<typeof nativeFinance.submitConsumableOrder>[0],
        signal?: AbortSignal,
      ) =>
        domainApi.write(
          (c) =>
            c.POST("/api/v1/consumable-orders/{order_id}/submit", {
              signal,
              params: {
                path: { order_id: options.orderId },
                header: { "If-Match": options.ifMatch, "Idempotency-Key": options.idempotencyKey },
              },
              body: options.input,
            }),
          () => cancellableNative(signal, () => nativeFinance.submitConsumableOrder(options)),
        ),
      receiveConsumableOrder: (
        options: Parameters<typeof nativeFinance.receiveConsumableOrder>[0],
        signal?: AbortSignal,
      ) =>
        domainApi.write(
          (c) =>
            c.POST("/api/v1/consumable-orders/{order_id}/receive", {
              signal,
              params: {
                path: { order_id: options.orderId },
                header: { "If-Match": options.ifMatch, "Idempotency-Key": options.idempotencyKey },
              },
              body: options.input,
            }),
          () => cancellableNative(signal, () => nativeFinance.receiveConsumableOrder(options)),
        ),
      cancelConsumableOrder: (
        options: Parameters<typeof nativeFinance.cancelConsumableOrder>[0],
        signal?: AbortSignal,
      ) =>
        domainApi.write(
          (c) =>
            c.POST("/api/v1/consumable-orders/{order_id}/cancel", {
              signal,
              params: {
                path: { order_id: options.orderId },
                header: { "If-Match": options.ifMatch, "Idempotency-Key": options.idempotencyKey },
              },
              body: options.input,
            }),
          () => cancellableNative(signal, () => nativeFinance.cancelConsumableOrder(options)),
        ),
    }),
    [domainApi],
  );
}
