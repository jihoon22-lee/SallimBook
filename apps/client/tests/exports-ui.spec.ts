import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockExports, zip } from "./support/exports";
import { documentRow } from "./support/documents";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });
const ack = "민감한 업무 기록이 포함될 수 있고 저장한 파일을 앱에서 회수할 수 없음을 확인했어요";
const download = (page: Page) => page.getByRole("button", { name: "ZIP 내보내기·저장", exact: true });
async function saved(page: Page) { await page.getByLabel(ack).check(); const waiting = page.waitForEvent("download"); await download(page).click(); const result = await waiting; const stream = await result.createReadStream(); const parts: Buffer[] = []; for await (const part of stream!) parts.push(Buffer.from(part)); expect(Buffer.concat(parts)).toEqual(zip); return result; }

test("default ZIP requires informed acknowledgement and uses generated authenticated POST without idempotency", async ({ page }) => {
  const state = await mockExports(page); await page.goto("/exports"); await expect(download(page)).toBeDisabled(); expect(state.writes).toHaveLength(0);
  const result = await saved(page); expect(result.suggestedFilename()).toBe(`sallimbook-${uid(9501)}.zip`);
  expect(state.writes[0]!.body).toEqual({ formats: ["csv", "json"], document_ids: [] }); expect(state.writes[0]!.headers["x-csrf-token"]).toMatch(/^synthetic-finance-csrf-/); expect(state.writes[0]!.headers).not.toHaveProperty("idempotency-key");
  await expect(page.getByText(/브라우저의 다운로드 목록에서 실제 저장 결과/)).toBeVisible(); await expect(page.getByLabel(ack)).not.toBeChecked();
  expect(await page.evaluate(async () => ({ urls: (window as any).__exportURLs, local: localStorage.length, session: sessionStorage.length, cache: (await caches.keys()).length, anchors: document.querySelectorAll('a[download]').length }))).toEqual({ urls: { created: 1, revoked: 1 }, local: 0, session: 0, cache: 0, anchors: 0 });
});

test("format and document selections reset consent and only ready linked documents can be selected", async ({ page }) => {
  const state = await mockExports(page); state.documents.documents.push(documentRow(8001, { original_name: "합성 대기.pdf", state: "pending", stored_at: null }), documentRow(8002, { original_name: "합성 연결 없음.pdf", active_link_count: 0 }));
  await page.goto("/exports"); await page.getByLabel(ack).check(); await page.getByLabel("CSV — 표로 살펴보기", { exact: true }).uncheck(); await expect(page.getByLabel(ack)).not.toBeChecked();
  await page.getByRole("button", { name: "문서 원본 선택 열기", exact: true }).click(); await expect(page.getByLabel("합성 대기.pdf", { exact: true })).toBeDisabled(); await expect(page.getByLabel("합성 연결 없음.pdf", { exact: true })).toBeDisabled();
  await page.getByLabel("합성 영수증.png", { exact: true }).check(); await saved(page); expect(state.writes[0]!.body).toEqual({ formats: ["json"], document_ids: [uid(8000)] });
  await page.getByLabel("JSON — 원래 값과 구조를 보존하는 교환용", { exact: true }).uncheck(); await expect(download(page)).toBeDisabled(); await expect(page.getByRole("alert")).toContainText("하나 이상");
});

test("document pages preserve selection and reject an eleventh original", async ({ page }) => {
  const state = await mockExports(page); state.documents.documents = Array.from({ length: 11 }, (_, i) => documentRow(8000 + i, { original_name: `합성 문서 ${i}.pdf` })); state.documents.pageSize = 5;
  await page.goto("/exports"); await page.getByRole("button", { name: "문서 원본 선택 열기", exact: true }).click();
  for (let i = 0; i < 11; i++) { if (i === 5 || i === 10) await page.getByRole("button", { name: "문서 더 보기", exact: true }).click(); await page.getByLabel(`합성 문서 ${i}.pdf`, { exact: true }).click(); }
  await expect(page.getByLabel("합성 문서 10.pdf", { exact: true })).not.toBeChecked(); await expect(page.getByRole("alert")).toContainText("10개까지"); await saved(page); expect(state.writes[0]!.body.document_ids).toHaveLength(10);
});

test("original bytes sum stops above 40MiB and long names fit narrow screens", async ({ page }) => {
  const state = await mockExports(page); const long = "s".repeat(245) + ".pdf"; state.documents.documents = [documentRow(8000, { original_name: long, size_bytes: 20 * 1024 * 1024 }), documentRow(8001, { original_name: "합성 20MiB.pdf", size_bytes: 20 * 1024 * 1024 }), documentRow(8002, { original_name: "합성 초과.pdf", size_bytes: 1 })];
  await page.goto("/exports"); await page.getByRole("button", { name: "문서 원본 선택 열기", exact: true }).click(); await page.getByLabel(long, { exact: true }).check(); await page.getByLabel("합성 20MiB.pdf", { exact: true }).check(); await page.getByLabel("합성 초과.pdf", { exact: true }).click(); await expect(page.getByLabel("합성 초과.pdf", { exact: true })).not.toBeChecked(); await expect(page.getByRole("alert")).toContainText("40MiB"); expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
});

for (const [code, status, text] of [["EXPORT_BUSY", 503, "다른 내보내기"], ["EXPORT_TIMEOUT", 408, "준비 시간이 초과"], ["EXPORT_TOO_LARGE", 413, "한도를 초과"], ["EXPORT_CONFLICT", 409, "기록이 변경"], ["REAUTHENTICATION_REQUIRED", 403, "최근 5분"], ["network", 0, "연결이 끊겨"]] as const) test(`failure ${code} explains a new request without automatic replay`, async ({ page }) => {
  const state = await mockExports(page); state.failure = code; state.status = status; let files = 0; page.on("download", () => files++); await page.goto("/exports"); await page.getByLabel(ack).check(); await download(page).click(); await expect(page.getByRole("alert")).toContainText(text); expect(state.writes).toHaveLength(1); expect(files).toBe(0); await expect(page.getByText("UNTRUSTED_EXPORT_MESSAGE")).toHaveCount(0); await expect(page.getByLabel(ack)).not.toBeChecked();
});

test("changed original is explicitly refreshed and removed before a new snapshot", async ({ page }) => {
  const state = await mockExports(page); await page.goto("/exports"); await page.getByRole("button", { name: "문서 원본 선택 열기", exact: true }).click(); await page.getByLabel("합성 영수증.png", { exact: true }).check(); state.failure = "EXPORT_DOCUMENT_CHANGED"; state.status = 409;
  await page.getByLabel(ack).check(); await download(page).click(); await expect(page.getByRole("alert")).toContainText("문서의 내용이나 연결 상태"); state.documents.documents[0]!.active_link_count = 0; await page.getByRole("button", { name: "선택 문서 새로 확인", exact: true }).click(); await expect(page.getByText(/선택에서 제외했어요/)).toBeVisible(); state.failure = ""; await saved(page); expect(state.writes.map((row) => row.body.document_ids)).toEqual([[uid(8000)], []]);
});

for (const [header, value] of [["X-Export-SHA256", "0".repeat(64)], ["X-Export-ID", "invalid"], ["Cache-Control", "public"], ["Content-Disposition", 'attachment; filename="../other.zip"'], ["Content-Type", "text/html"], ["Content-Length", String(64 * 1024 * 1024 + 1)]] as const) test(`invalid download header ${header} never creates a local file`, async ({ page }) => {
  const state = await mockExports(page); state.headers[header] = value; let files = 0; page.on("download", () => files++); await page.goto("/exports"); await page.getByLabel(ack).check(); await download(page).click(); await expect(page.getByRole("alert")).toBeVisible(); expect(files).toBe(0); expect(await page.evaluate(() => (window as any).__exportURLs.created)).toBe(0);
});

test("cancelled or departed request ignores delayed response and requires fresh acknowledgement", async ({ page }) => {
  const state = await mockExports(page); state.delay = 600; let files = 0; page.on("download", () => files++); await page.goto("/exports"); await page.getByLabel(ack).check(); await download(page).click(); await expect.poll(() => state.writes.length).toBe(1); await page.getByRole("button", { name: "내보내기 대기 중단", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("대기를 중단"); await page.waitForTimeout(700); expect(files).toBe(0); expect(state.writes).toHaveLength(1);
  state.delay = 0; await saved(page); expect(state.writes).toHaveLength(2);
});

test("pagehide aborts the private archive response without creating a blob URL", async ({ page }) => {
  const state = await mockExports(page); state.delay = 600; await page.goto("/exports"); await page.getByLabel(ack).check(); await download(page).click(); await expect.poll(() => state.writes.length).toBe(1); await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide"))); await expect(page.getByRole("alert")).toContainText("대기를 중단"); await page.waitForTimeout(700); expect(await page.evaluate(() => (window as any).__exportURLs.created)).toBe(0);
});

test("401 export clears authenticated selection and never produces a file", async ({ page }) => {
  const state = await mockExports(page); state.failure = "UNAUTHENTICATED"; state.status = 401; await page.goto("/exports"); await page.getByLabel(ack).check(); await download(page).click(); await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible(); await expect(download(page)).toHaveCount(0); expect(await page.evaluate(() => (window as any).__exportURLs.created)).toBe(0);
});

test("pre-handler CSRF rejection refreshes the token once without double issuance", async ({ page }) => {
  const state = await mockExports(page); state.csrfOnce = true; await page.goto("/exports"); await saved(page); expect(state.writes).toHaveLength(2); expect(state.issued).toBe(1); expect(state.writes[0]!.body).toEqual(state.writes[1]!.body); expect(state.writes[0]!.headers["x-csrf-token"]).not.toBe(state.writes[1]!.headers["x-csrf-token"]);
});

for (const result of ["success", "wrong-target", "cancelled"]) test(`export passkey proof ${result} is bound to current household only`, async ({ page }) => {
  const state = await mockExports(page); const proofs: any[] = []; let verifies = 0;
  await page.addInitScript((cancelled) => {
    Object.defineProperty(navigator.credentials, "get", { value: async () => {
      if (cancelled) throw new DOMException("Synthetic cancellation", "NotAllowedError");
      const response = Object.create(AuthenticatorAssertionResponse.prototype);
      Object.defineProperties(response, { clientDataJSON: { value: new Uint8Array([1]).buffer }, authenticatorData: { value: new Uint8Array([2]).buffer }, signature: { value: new Uint8Array([3]).buffer }, userHandle: { value: null } });
      const credential = Object.create(PublicKeyCredential.prototype);
      Object.defineProperties(credential, { id: { value: "AQ" }, rawId: { value: new Uint8Array([1]).buffer }, type: { value: "public-key" }, response: { value: response }, authenticatorAttachment: { value: "platform" }, getClientExtensionResults: { value: () => ({}) } });
      return credential;
    } });
  }, result === "cancelled");
  await page.route("**/api/v1/auth/step-up/options", (route) => { proofs.push(route.request().postDataJSON()); return route.fulfill({ json: { challenge_id: uid(9800), expires_at: "2099-01-01T00:00:00Z", public_key: { challenge: "c3ludGhldGlj", rpId: "127.0.0.1", userVerification: "required" } } }); });
  await page.route("**/api/v1/auth/step-up/verify", (route) => { verifies++; return route.fulfill({ json: { purpose: "data.export", target_id: result === "wrong-target" ? uid(4) : uid(3), grant_token: "synthetic-export-proof", expires_at: "2099-01-01T00:00:00Z" } }); });
  await page.goto("/exports"); await page.getByLabel(ack).check(); const waiting = result === "success" ? page.waitForEvent("download") : null; await page.getByRole("button", { name: "패스키로 확인하고 ZIP 내보내기", exact: true }).click();
  if (waiting) { await waiting; expect(state.writes).toHaveLength(1); expect(state.writes[0]!.headers["x-step-up-token"]).toBe("synthetic-export-proof"); expect(state.writes[0]!.body).toEqual({ formats: ["csv", "json"], document_ids: [] }); }
  else { await expect(page.getByRole("alert")).toBeVisible(); expect(state.writes).toHaveLength(0); }
  expect(proofs).toEqual([{ purpose: "data.export", target_id: uid(3) }]); expect(verifies).toBe(result === "cancelled" ? 0 : 1); expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
});

test("settings exposes export entry while a signed-out deep link never loads data", async ({ page }) => {
  const state = await mockExports(page); await page.goto("/settings"); await page.getByRole("link", { name: /^자료 내보내기/ }).click(); await expect(page.getByRole("heading", { name: "자료 내보내기", exact: true })).toBeVisible();
  await page.route("**/api/v1/me", (route) => route.fulfill({ status: 401, json: { error: { code: "UNAUTHENTICATED", message: "synthetic", request_id: "synthetic" } } }));
  await page.reload(); await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible(); await expect(download(page)).toHaveCount(0); expect(state.writes).toEqual([]); expect(state.documents.reads).toEqual([]);
});
