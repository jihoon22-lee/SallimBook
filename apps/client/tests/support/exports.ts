import { createHash } from "node:crypto";
import type { Page } from "@playwright/test";
import { mockDocuments } from "./documents";
import { members, uid } from "./finance";
export const zip = Buffer.from("UEsDBBQAAAAIAFE4Ul0QsQmORAAAAEQAAAANAAAAbWFuaWZlc3QuanNvbqtWSssvyk0sUbJSUCpOzMnJzE3Kz8/WLS1OLdJNrSjILyrRLTNU0lFQSsusKCktSgWpC470C/FwDfF0VvD384lUqgUAUEsDBBQAAAAIAFE4Ul3mQFQhKAAAACYAAAATAAAAanNvbi9zeW50aGV0aWMuanNvbouuVkrMzS/NK4nPLipXslIyNDAwUNJRys0sLs7MS1eyyivNyamNBQBQSwECFAMUAAAACABROFJdELEJjkQAAABEAAAADQAAAAAAAAAAAAAAgAEAAAAAbWFuaWZlc3QuanNvblBLAQIUAxQAAAAIAFE4Ul3mQFQhKAAAACYAAAATAAAAAAAAAAAAAACAAW8AAABqc29uL3N5bnRoZXRpYy5qc29uUEsFBgAAAAACAAIAfAAAAMgAAAAAAA==", "base64");
export async function mockExports(page: Page, native = false) {
  const documents = await mockDocuments(page);
  const state = { documents, writes: [] as { body: any; headers: Record<string, string> }[], issued: 0, failure: "", status: 503,
    headers: {} as Record<string, string | null>, corrupt: false, delay: 0, csrfOnce: false,
    nativeStatus: "exported", nativeFailure: "", calls: [] as { method: string; args: any }[], http: [] as string[] };
  await page.route("**/api/v1/exports", async (route) => {
    const request = route.request(); state.writes.push({ body: request.postDataJSON(), headers: request.headers() });
    if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay));
    if (state.failure === "network") return route.abort("failed").catch(() => {});
    if (state.csrfOnce) { state.csrfOnce = false; return route.fulfill({ status: 403, json: { error: { code: "CSRF_FAILED", message: "UNTRUSTED_EXPORT_MESSAGE", request_id: "synthetic" } } }).catch(() => {}); }
    if (state.failure) return route.fulfill({ status: state.status, json: { error: { code: state.failure, message: "UNTRUSTED_EXPORT_MESSAGE", request_id: "synthetic" } } }).catch(() => {});
    const id = uid(9500 + ++state.issued);
    const headers: Record<string, string> = { "Content-Type": "application/zip", "Content-Length": String(zip.length), "Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff", "X-Export-ID": id, "X-Export-SHA256": createHash("sha256").update(zip).digest("hex"), "Content-Disposition": `attachment; filename="sallimbook-${id}.zip"` };
    for (const [key, value] of Object.entries(state.headers)) { if (value === null) delete headers[key]; else headers[key] = value; }
    const body = Buffer.from(zip); if (state.corrupt) body[body.length - 1] = body[body.length - 1]! ^ 1;
    return route.fulfill({ status: 200, headers, body }).catch(() => {});
  });
  await page.addInitScript(() => {
    const observed = { created: 0, revoked: 0 };
    Object.assign(window, { __exportURLs: observed });
    const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = (blob) => { observed.created++; return create(blob); };
    URL.revokeObjectURL = (url) => { observed.revoked++; revoke(url); };
  });
  if (!native) return state;
  page.on("request", (request) => { if (new URL(request.url()).pathname.startsWith("/api/")) state.http.push(request.url()); });
  const metadata = (body: unknown, status = 200) => ({ ok: true, value: { status, body } });
  await page.exposeFunction("syntheticExportsNative", async (method: string, args: any) => {
    state.calls.push({ method, args });
    if (method === "getSession") return { ok: true, value: { available: true, authenticated: true } };
    if (method === "request") return metadata(args.path === "/api/v1/me" ? members[0] : members);
    if (method === "exportArchiveUI") {
      if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay));
      return state.nativeFailure ? { ok: false, code: state.nativeFailure } : { ok: true, value: { status: state.nativeStatus } };
    }
    const path = method === "listDocuments" ? "/api/v1/documents" : method === "getDocument" ? `/api/v1/documents/${args.documentId}` : "";
    if (!path) return { ok: false, code: "INVALID_REQUEST" };
    const query = new URLSearchParams(Object.entries(args.query ?? {}).filter(([, value]) => value != null).map(([key, value]) => [key, String(value)]));
    const result = await documents.handle("GET", path, query);
    return result ? metadata(result.body, result.status) : { ok: false, code: "INVALID_REQUEST" };
  });
  await page.addInitScript(() => Object.assign(window, { CapacitorCustomPlatform: { name: "android" }, Capacitor: {
    PluginHeaders: [{ name: "SallimBookAuth", methods: ["getSession", "request", "exportArchiveUI", "listDocuments", "getDocument"].map((name) => ({ name, rtype: "promise" })).concat([{ name: "addListener", rtype: "callback" }, { name: "removeListener", rtype: "promise" }]) }],
    nativeCallback: () => "synthetic-listener", nativePromise: (_plugin: string, method: string, args = {}) => method === "removeListener" ? Promise.resolve() : (window as any).syntheticExportsNative(method, args),
  } }));
  return state;
}
