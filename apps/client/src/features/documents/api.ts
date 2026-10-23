import { useMemo } from "react";
import { useAuth } from "../auth/AuthProvider";
import { nativeFinance } from "../../platform/nativeFinance";
import { cancellableNative } from "../../platform/cancellableNative";
import type { CreateDocument } from "./model";
export function useDocumentsApi() {
  const { domainApi } = useAuth();
  return useMemo(
    () => ({
      list: (o: Parameters<typeof nativeFinance.listDocuments>[0], signal?: AbortSignal) =>
        domainApi.read(
          (c) => c.GET("/api/v1/documents", { params: { query: o.query }, signal }),
          () => cancellableNative(signal, () => nativeFinance.listDocuments(o)),
        ),
      get: (documentId: string, signal?: AbortSignal) =>
        domainApi.read(
          (c) =>
            c.GET("/api/v1/documents/{document_id}", {
              params: { path: { document_id: documentId } },
              signal,
            }),
          () => cancellableNative(signal, () => nativeFinance.getDocument({ documentId })),
        ),
      links: (o: Parameters<typeof nativeFinance.listDocumentLinks>[0], signal?: AbortSignal) =>
        domainApi.read(
          (c) =>
            c.GET("/api/v1/documents/{document_id}/links", {
              params: { path: { document_id: o.documentId }, query: o.query },
              signal,
            }),
          () => cancellableNative(signal, () => nativeFinance.listDocumentLinks(o)),
        ),
      link: (o: Parameters<typeof nativeFinance.createDocumentLink>[0], signal?: AbortSignal) =>
        domainApi.write(
          (c) =>
            c.POST("/api/v1/document-links", {
              params: { header: { "If-Match": o.ifMatch, "Idempotency-Key": o.idempotencyKey } },
              body: o.input,
              signal,
            }),
          () => cancellableNative(signal, () => nativeFinance.createDocumentLink(o)),
        ),
      end: (o: Parameters<typeof nativeFinance.endDocumentLink>[0], signal?: AbortSignal) =>
        domainApi.write(
          (c) =>
            c.POST("/api/v1/document-links/{link_id}/end", {
              params: {
                path: { link_id: o.linkId },
                header: { "If-Match": o.ifMatch, "Idempotency-Key": o.idempotencyKey },
              },
              body: o.input,
              signal,
            }),
          () => cancellableNative(signal, () => nativeFinance.endDocumentLink(o)),
        ),
      remove: (o: Parameters<typeof nativeFinance.deleteDocument>[0], signal?: AbortSignal) =>
        domainApi.write(
          (c) =>
            c.POST("/api/v1/documents/{document_id}/delete", {
              params: {
                path: { document_id: o.documentId },
                header: { "If-Match": o.ifMatch, "Idempotency-Key": o.idempotencyKey },
              },
              body: o.input,
              signal,
            }),
          () => cancellableNative(signal, () => nativeFinance.deleteDocument(o)),
        ),
      // An attachment draft holds the chosen file, so an ended session clears it instead of
      // keeping it on screen behind the sign-in dialog.
      create: (input: CreateDocument, key: string, signal: AbortSignal) =>
        domainApi.write(
          (c) =>
            c.POST("/api/v1/documents", {
              body: input,
              params: { header: { "Idempotency-Key": key } },
              signal,
            }),
          undefined,
          undefined,
          { clearOnExpiry: true },
        ),
      upload: (id: string, version: string, key: string, bytes: ArrayBuffer, signal: AbortSignal) =>
        domainApi.write(
          (c) =>
            c.PUT("/api/v1/documents/{document_id}/content", {
              params: {
                path: { document_id: id },
                header: { "If-Match": version, "Idempotency-Key": key },
              },
              headers: { "Content-Type": "application/octet-stream" },
              body: "",
              bodySerializer: () => bytes,
              signal,
            }),
          undefined,
          undefined,
          { clearOnExpiry: true },
        ),
      download: async (id: string, signal: AbortSignal) => {
        let received: ArrayBuffer | undefined;
        try {
          return await domainApi.read(async (c) => {
            const result = await c.GET("/api/v1/documents/{document_id}/download", {
              params: { path: { document_id: id } },
              parseAs: "arrayBuffer",
              signal,
            });
            received = result.data;
            return result;
          });
        } catch (error) {
          if (received) new Uint8Array(received).fill(0);
          throw error;
        }
      },
      nativeUpload: (o: Parameters<typeof nativeFinance.uploadDocument>[0], signal: AbortSignal) =>
        domainApi.write(undefined, () =>
          cancellableNative(signal, () => nativeFinance.uploadDocument(o)),
        ),
      nativeDownload: (
        o: Parameters<typeof nativeFinance.downloadDocument>[0],
        signal: AbortSignal,
      ) =>
        domainApi.read(undefined, () =>
          cancellableNative(signal, () => nativeFinance.downloadDocument(o)),
        ),
    }),
    [domainApi],
  );
}
export type DocumentsApi = ReturnType<typeof useDocumentsApi>;
