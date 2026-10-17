import { expect, test } from "@playwright/test";
import { zip } from "./support/exports";
import { createHash } from "node:crypto";
test.use({ trace: "off", screenshot: "off", video: "off" });
for (const scenario of ["correct", "short", "overrun", "cancel", "hash", "save"]) test(`bounded archive stream ${scenario} cleans owned bytes`, async ({ page }) => {
  await page.route("**/__exports-stream", (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Synthetic export stream test</title>" })); await page.goto("/__exports-stream");
  const result = await page.evaluate(async ({ scenario, bytes, digest }) => {
    const source = "/src/features/exports/download.ts"; const { receiveExport, saveExport } = await import(source);
    const data = Uint8Array.from(bytes), chunk = data.slice(0, scenario === "short" ? -1 : undefined);
    const abort = new AbortController(); const id = "00000000-0000-4000-8000-000000009500";
    let phase = ""; let cancelled = false; let code = ""; let copied = false; let outputZero = false;
    const response = new Response(new ReadableStream({ start(controller) { controller.enqueue(chunk); if (scenario === "overrun") controller.enqueue(new Uint8Array([1])); controller.close(); }, cancel() { cancelled = true; } }), { headers: {
      "Content-Type": "application/zip", "Content-Length": String(data.length), "X-Export-ID": id, "X-Export-SHA256": scenario === "hash" ? "0".repeat(64) : digest, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": `attachment; filename="sallimbook-${id}.zip"`,
    } });
    try {
      const file = await receiveExport(response, abort.signal, (state: { phase: string; received: number }) => { phase = state.phase; if (scenario === "cancel" && state.received > 0) abort.abort(); });
      copied = file.bytes.every((byte: number, index: number) => byte === data[index]);
      if (scenario === "save") { HTMLAnchorElement.prototype.click = () => {}; saveExport(file, abort.signal); outputZero = file.bytes.every((value: number) => value === 0); }
      else file.bytes.fill(0);
    } catch (failure) { code = (failure as { code?: string; name: string }).code ?? (failure as Error).name; }
    return { code, copied, outputZero, chunkZero: chunk.every((byte) => byte === 0), phase, cancelled, anchors: document.querySelectorAll('a[download]').length };
  }, { scenario, bytes: [...zip], digest: createHash("sha256").update(zip).digest("hex") });
  expect(result.chunkZero).toBe(true); expect(result.anchors).toBe(0);
  if (["correct", "save"].includes(scenario)) { expect(result.code).toBe(""); expect(result.copied).toBe(true); expect(result.phase).toBe("verifying"); if (scenario === "save") expect(result.outputZero).toBe(true); }
  else { expect(result.code).not.toBe(""); expect(result.copied).toBe(false); }
});
