import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import type { BrowserContext, Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
type S = components["schemas"];
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as { login: string; password: string; control: string; foreign_login: string; foreign_password: string };
const ack = "민감한 업무 기록이 포함될 수 있고 저장한 파일을 앱에서 회수할 수 없음을 확인했어요";
test.setTimeout(300_000); test.use({ actionTimeout: 15_000, navigationTimeout: 20_000 });
async function login(page: Page, foreign = false) { await page.goto("/login"); await page.getByLabel("로그인 이름", { exact: true }).fill(foreign ? fixture.foreign_login : fixture.login); await page.getByLabel("비밀번호", { exact: true }).fill(foreign ? fixture.foreign_password : fixture.password); await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 내보내기 HTTPS"); await page.getByRole("button", { name: "로그인", exact: true }).click(); await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible(); }
async function read<T>(page: Page, path: string): Promise<T> { return page.evaluate(async (path) => { const response = await fetch(path, { cache: "no-store" }); if (!response.ok) throw new Error("Synthetic metadata read failed"); return response.json(); }, path); }
async function write<T>(page: Page, path: string, input: unknown, version?: number): Promise<T> { return page.evaluate(async ({ path, input, version }) => { const csrf = await fetch("/api/v1/auth/web/csrf", { cache: "no-store" }).then((response) => response.json()); const response = await fetch(path, { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf.csrf_token, "Idempotency-Key": crypto.randomUUID(), ...(version ? { "If-Match": `"${version}"` } : {}) }, body: JSON.stringify(input) }); if (!response.ok) throw new Error("Synthetic metadata write failed"); return response.json(); }, { path, input, version }); }
async function png(page: Page) { const data = await page.evaluate(() => { const canvas = document.createElement("canvas"); canvas.width = 1200; canvas.height = 440; const ctx = canvas.getContext("2d")!; ctx.fillStyle = "white"; ctx.fillRect(0, 0, 1200, 440); ctx.fillStyle = "black"; ctx.font = "44px Arial"; for (const [i, line] of ["SYNTHETIC EXPORT RECEIPT", "Household appliance purchase record", "This fixture contains no personal data", "Original document export test sample"].entries()) ctx.fillText(line, 40, 80 + i * 85); return canvas.toDataURL("image/png").split(",")[1]!; }); return Buffer.from(data, "base64"); }
function inspectZip(bytes: Buffer) {
  return JSON.parse(execFileSync("python3", ["-c", `import sys,io,zipfile,json,hashlib,csv
with zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())) as archive:
 out={"names":archive.namelist(),"json":{},"csv":{},"hashes":{}}
 for name in archive.namelist():
  data=archive.read(name)
  out["hashes"][name]={"size":len(data),"sha256":hashlib.sha256(data).hexdigest()}
  if name.endswith(".json"):out["json"][name]=json.loads(data)
  elif name.endswith(".csv"):out["csv"][name]=list(csv.DictReader(io.StringIO(data.decode("utf8"))))
 print(json.dumps(out))`], { input: bytes, maxBuffer: 8 * 1024 * 1024 }).toString()) as { names: string[]; json: Record<string, any>; csv: Record<string, Record<string, string>[]>; hashes: Record<string, { size: number; sha256: string }> };
}
async function archive(page: Page) {
  await page.getByLabel(ack).check(); const waiting = page.waitForEvent("download", { timeout: 45_000 }).catch(() => null); const responseWait = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/exports", { timeout: 45_000 });
  console.log("SAFE_PHASE=EXPORT_DOWNLOAD_START");
  await page.getByRole("button", { name: "ZIP 내보내기·저장", exact: true }).click(); const response = await responseWait;
  if (response.status() !== 200) {
    const category = response.status() === 403 ? "AUTH" : response.status() === 409 ? "CONFLICT" : response.status() === 408 ? "TIMEOUT" : response.status() >= 500 ? "SERVER" : "OTHER";
    console.log(`SAFE_PHASE=EXPORT_HTTP_${category}`);
  } else console.log("SAFE_PHASE=EXPORT_HTTP_OK");
  expect(response.status()).toBe(200);
  const file = await waiting;
  if (!file) {
    const text = await page.getByRole("alert").allTextContents();
    console.log(text.some((item) => item.includes("체크섬")) ? "SAFE_PHASE=EXPORT_INTEGRITY_REJECTED" : "SAFE_PHASE=EXPORT_DOWNLOAD_MISSING");
  }
  expect(file).not.toBeNull(); console.log("SAFE_PHASE=EXPORT_DOWNLOAD_RECEIVED"); const stream = await file!.createReadStream(); const parts: Buffer[] = []; for await (const part of stream!) parts.push(Buffer.from(part)); const bytes = Buffer.concat(parts);
  const headers = response.headers(); expect(headers["cache-control"]).toBe("no-store"); expect(headers["content-type"]).toBe("application/zip"); expect(headers["x-content-type-options"]).toBe("nosniff"); expect(Number(headers["content-length"])).toBe(bytes.length); expect(headers["x-export-sha256"]).toBe(createHash("sha256").update(bytes).digest("hex")); expect(file!.suggestedFilename()).toBe(`sallimbook-${headers["x-export-id"]}.zip`);
  const decoded = inspectZip(bytes); const manifest = decoded.json["manifest.json"]; expect(manifest.export_id).toBe(headers["x-export-id"]); expect(manifest.format).toBe("sallimbook-user-export-v1");
  for (const entry of manifest.entries) expect(decoded.hashes[entry.path]).toEqual({ size: entry.size_bytes, sha256: entry.sha256 });
  return decoded;
}
async function blockedExport(page: Page, documentId: string) { return page.evaluate(async (id) => { const csrf = await fetch("/api/v1/auth/web/csrf", { cache: "no-store" }).then((response) => response.json()); const response = await fetch("/api/v1/exports", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf.csrf_token }, body: JSON.stringify({ formats: ["json"], document_ids: [id] }) }); return { status: response.status, type: response.headers.get("Content-Type"), cache: response.headers.get("Cache-Control"), disposition: response.headers.get("Content-Disposition") }; }, documentId); }

test("real authenticated ZIP preserves selected originals and excludes secret fields with late access checks", async ({ page, browser }) => {
  let foreignContext: BrowserContext | undefined; let downloads = 0; const writes: { csrf: boolean; idempotency: boolean; input: S["ExportRequest"] }[] = [];
  page.on("response", async (response) => {
    if (/^\/api\/v1\/documents(?:\/[^/]+\/content)?$/.test(new URL(response.url()).pathname) && response.request().method() !== "GET") {
      console.log(response.ok() ? "SAFE_PHASE=EXPORT_DOCUMENT_WRITE_OK" : "SAFE_PHASE=EXPORT_DOCUMENT_WRITE_FAILED");
      if (!response.ok()) {
        const body = await response.json().catch(() => ({}));
        const code = body.error?.code ?? body.code;
        const known = ["DOCUMENT_CONTENT_MISMATCH", "DOCUMENT_CONTENT_REJECTED", "DOCUMENT_SCANNER_UNAVAILABLE", "DOCUMENT_OCR_UNAVAILABLE", "DOCUMENT_INSPECTION_UNAVAILABLE", "DOCUMENT_QUOTA_EXCEEDED", "DOCUMENT_TOO_LARGE", "VALIDATION_ERROR", "REAUTHENTICATION_REQUIRED", "CSRF_INVALID"];
        if (known.includes(code)) console.log(`SAFE_PHASE=${code}`);
      }
    }
  });
  page.on("download", () => downloads++); page.on("request", (request) => { if (new URL(request.url()).pathname === "/api/v1/exports") writes.push({ csrf: !!request.headers()["x-csrf-token"], idempotency: !!request.headers()["idempotency-key"], input: request.postDataJSON() }); });
  try {
    await login(page); const member = await read<S["MemberResponse"]>(page, "/api/v1/me");
    const appliance = await write<S["ApplianceResponse"]>(page, "/api/v1/appliances", { name: "합성 내보내기 가전", purchased_on: "2025-01-01", note: "SYNTHETIC EXPORT NOTE RETAINED" });
    await write<S["AccountResponse"]>(page, "/api/v1/accounts", { institution_name: "합성 내보내기 계좌", account_type: "irp", account_number: "000123-4567890", asset: { name: "합성 내보내기 연금 자산", kind: "asset", category: "financial", ownership_kind: "individual", owner_member_id: member.member_id, household_share: "1", amount_basis: "owned", started_on: "2025-01-01" } });
    await write<S["PolicyResponse"]>(page, "/api/v1/insurance/policies", { insurer: "합성 내보내기 보험사", product_name: "합성 내보내기 보험", coverage_start: "2025-01-01", policy_number: "SYNTHETIC-POLICY-0001" });
    await write<S["CashResponse"]>(page, "/api/v1/income", { member_id: member.member_id, kind: "salary", amount_krw: "1234567", period_month: "2025-01", date_precision: "month", note: "=SYNTHETIC_FORMULA()" });
    foreignContext = await browser.newContext({ baseURL: process.env.SALLIMBOOK_HTTPS_ORIGIN }); const foreign = await foreignContext.newPage(); await login(foreign, true); await write(foreign, "/api/v1/appliances", { name: "FOREIGN_EXPORT_CANARY", purchased_on: "2025-01-01" });
    console.log("SAFE_PHASE=EXPORT_SEEDED");
    const original = await png(page); await page.goto(`/appliances/${appliance.id}`); await page.getByRole("button", { name: "첨부 문서 열기", exact: true }).click(); const upload = page.getByRole("region", { name: "새 문서 첨부", exact: true }); await upload.getByLabel("문서 파일", { exact: true }).setInputFiles({ name: "합성 내보내기 원본.png", mimeType: "image/png", buffer: original }); await upload.getByRole("checkbox").check(); await upload.getByRole("button", { name: "문서 업로드", exact: true }).click(); await expect(page.getByRole("region", { name: "문서 상세", exact: true }).getByText("보관 완료", { exact: true })).toBeVisible({ timeout: 90_000 });
    const documents = await read<S["DocumentListResponse"]>(page, "/api/v1/documents"); const document = documents.items.find((row) => row.original_name === "합성 내보내기 원본.png")!; expect(document.checksum_sha256).toBe(createHash("sha256").update(original).digest("hex")); console.log("SAFE_PHASE=EXPORT_REAL_DOCUMENT");
    await page.goto("/exports"); console.log("SAFE_PHASE=EXPORT_PAGE_READY"); await page.getByRole("button", { name: "문서 원본 선택 열기", exact: true }).click(); console.log("SAFE_PHASE=EXPORT_PICKER_READY"); await page.getByLabel("합성 내보내기 원본.png", { exact: true }).check(); console.log("SAFE_PHASE=EXPORT_DOCUMENT_SELECTED"); const complete = await archive(page);
    expect(complete.names).toContain(`documents/${document.id}.png`); expect(complete.hashes[`documents/${document.id}.png`]).toEqual({ size: original.length, sha256: createHash("sha256").update(original).digest("hex") });
    expect(complete.json["json/cash_records.json"].find((row: any) => row.kind === "salary").amount_krw).toBe("1234567"); expect(complete.csv["csv/cash_records.csv"]!.find((row) => row.kind === "text:salary")!.amount_krw).toBe("text:1234567"); expect(complete.csv["csv/cash_records.csv"]!.find((row) => row.kind === "text:salary")!.note).toBe("text:=SYNTHETIC_FORMULA()");
    const text = JSON.stringify({ json: complete.json, csv: complete.csv }); expect(text).toContain("SYNTHETIC EXPORT NOTE RETAINED"); for (const forbidden of ["FOREIGN_EXPORT_CANARY", "000123-4567890", "SYNTHETIC-POLICY-0001", "account_number_ciphertext", "policy_number_ciphertext", "password_hash", "wrapped_hvk", "storage_key"]) expect(text).not.toContain(forbidden); expect(complete.names.some((name) => /vault|card_secret|auth_sessions|users\./.test(name))).toBe(false); console.log("SAFE_PHASE=EXPORT_CONTENT_AND_EXCLUSIONS");
    const cross = await blockedExport(foreign, document.id); expect(cross.status).toBe(404); expect(cross.type).toContain("application/json"); expect(cross.disposition).toBeNull(); expect(cross.cache).toBe("no-store"); console.log("SAFE_PHASE=EXPORT_HOUSEHOLD_ACCESS");
    const links = await read<S["DocumentLinkListResponse"]>(page, `/api/v1/documents/${document.id}/links`); const linked = links.items.find((row) => row.active)!; await write(page, `/api/v1/document-links/${linked.id}/end`, { reason: "합성 내보내기 연결 변경" }, linked.version);
    await page.getByLabel(ack).check(); await page.getByRole("button", { name: "ZIP 내보내기·저장", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("선택한 문서의 내용이나 연결 상태"); expect(downloads).toBe(1); await page.getByRole("button", { name: "선택 문서 새로 확인", exact: true }).click(); await expect(page.getByText(/선택에서 제외했어요/)).toBeVisible();
    await page.getByLabel("JSON — 원래 값과 구조를 보존하는 교환용", { exact: true }).uncheck(); const csvOnly = await archive(page); expect(csvOnly.names.some((name) => name.startsWith("json/") || name.startsWith("documents/"))).toBe(false); expect(csvOnly.names.some((name) => name.startsWith("csv/"))).toBe(true); console.log("SAFE_PHASE=EXPORT_CHANGED_DOCUMENT_AND_CSV");
    await page.request.post("/__test/expire-freshness", { headers: { "X-Test-Control": fixture.control } }); await page.getByLabel(ack).check(); await page.getByRole("button", { name: "ZIP 내보내기·저장", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("최근 5분"); expect(downloads).toBe(2);
    await page.getByRole("link", { name: "비밀번호로 다시 인증", exact: true }).click(); await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password); await page.getByRole("button", { name: "다시 인증", exact: true }).click(); await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible(); await page.goto("/exports"); await page.getByLabel("CSV — 표로 살펴보기", { exact: true }).uncheck(); const jsonOnly = await archive(page); expect(jsonOnly.names.some((name) => name.startsWith("csv/") || name.startsWith("documents/"))).toBe(false); expect(downloads).toBe(3); console.log("SAFE_PHASE=EXPORT_RECENT_AUTH");
    await page.evaluate(async () => { const csrf = await fetch("/api/v1/auth/web/csrf", { cache: "no-store" }).then((response) => response.json()); const response = await fetch("/api/v1/auth/web/logout", { method: "POST", headers: { "X-CSRF-Token": csrf.csrf_token } }); if (!response.ok) throw new Error("Synthetic logout failed"); });
    await page.getByLabel(ack).check(); await page.getByRole("button", { name: "ZIP 내보내기·저장", exact: true }).click(); await expect(page.getByRole("heading", { name: "로그인이 필요해요", exact: true })).toBeVisible(); expect(downloads).toBe(3); expect(writes.every((row) => row.csrf && !row.idempotency)).toBe(true); expect(writes[0]!.input.document_ids).toEqual([document.id]);
    expect(await page.evaluate(async () => ({ local: localStorage.length, session: sessionStorage.length, cache: (await caches.keys()).length }))).toEqual({ local: 0, session: 0, cache: 0 }); console.log("SAFE_PHASE=EXPORT_SESSION_AND_STORAGE");
  } finally { await foreignContext?.close(); }
});
