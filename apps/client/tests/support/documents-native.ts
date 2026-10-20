import type { Page } from "@playwright/test";
import { members } from "./finance";
import type { mockDocuments } from "./documents";
export async function mockNativeDocuments(
  page: Page,
  state: Awaited<ReturnType<typeof mockDocuments>>,
) {
  const calls: { method: string; args: Record<string, any> }[] = [];
  const http: string[] = [];
  const control = { failure: "", method: "", status: "", delay: 0 };
  const mapping: Record<string, [string, string]> = {
    listDocuments: ["GET", "/documents"],
    getDocument: ["GET", "/documents/{documentId}"],
    listDocumentLinks: ["GET", "/documents/{documentId}/links"],
    createDocumentLink: ["POST", "/document-links"],
    endDocumentLink: ["POST", "/document-links/{linkId}/end"],
    deleteDocument: ["POST", "/documents/{documentId}/delete"],
    getAppliance: ["GET", "/appliances/{applianceId}"],
    listApplianceConsumables: ["GET", "/appliance-consumables"],
    listConsumables: ["GET", "/consumables"],
  };
  const metadata = (body: unknown, status = 200) => ({ ok: true, value: { status, body } });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) http.push(request.url());
  });
  await page.exposeFunction(
    "syntheticDocumentsNative",
    async (method: string, args: Record<string, any>) => {
      calls.push({ method, args });
      if (method === "getSession")
        return { ok: true, value: { available: true, authenticated: true } };
      if (method === "request") return metadata(args.path === "/api/v1/me" ? members[0] : members);
      if (control.failure && control.method === method) return { ok: false, code: control.failure };
      if (method === "uploadDocumentUI" || method === "downloadDocumentUI")
        return {
          ok: true,
          value: {
            status: control.status || (method === "uploadDocumentUI" ? "uploaded" : "downloaded"),
          },
        };
      const mappingRow = mapping[method];
      if (!mappingRow) return { ok: false, code: "INVALID_REQUEST" };
      let path = `/api/v1${mappingRow[1]}`;
      for (const [key, value] of Object.entries(args))
        if (typeof value === "string") path = path.replace(`{${key}}`, value);
      const query = new URLSearchParams(
        Object.fromEntries(
          Object.entries(args.query ?? {})
            .filter(([, value]) => value !== undefined && value !== null)
            .map(([key, value]) => [key, String(value)]),
        ),
      );
      const headers = {
        ...(args.ifMatch ? { "if-match": args.ifMatch } : {}),
        ...(args.idempotencyKey ? { "idempotency-key": args.idempotencyKey } : {}),
      };
      const result =
        (await state.handle(mappingRow[0], path, query, args.input ?? {}, headers)) ??
        (await state.homecare.handle(mappingRow[0], path, query, args.input ?? {}, headers));
      if (control.method === method && control.delay)
        await new Promise((r) => setTimeout(r, control.delay));
      return result?.abort
        ? { ok: false, code: "NETWORK_UNAVAILABLE" }
        : result
          ? metadata(result.body, result.status)
          : { ok: false, code: "INVALID_REQUEST" };
    },
  );
  await page.addInitScript(
    (methods) =>
      Object.assign(window, {
        CapacitorCustomPlatform: { name: "android" },
        Capacitor: {
          PluginHeaders: [
            {
              name: "SallimBookAuth",
              methods: [
                ...methods,
                "getSession",
                "request",
                "uploadDocumentUI",
                "downloadDocumentUI",
              ]
                .map((name) => ({ name, rtype: "promise" }))
                .concat([
                  { name: "addListener", rtype: "callback" },
                  { name: "removeListener", rtype: "promise" },
                ]),
            },
          ],
          nativeCallback: () => "synthetic-listener",
          nativePromise: (_plugin: string, method: string, args = {}) =>
            method === "removeListener"
              ? Promise.resolve()
              : (window as any).syntheticDocumentsNative(method, args),
        },
      }),
    Object.keys(mapping),
  );
  return { calls, http, control };
}
