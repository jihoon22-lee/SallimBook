import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
type S = components["schemas"];
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as {
  login: string;
  password: string;
};
test.setTimeout(480_000);
test.use({ actionTimeout: 10_000, navigationTimeout: 15_000 });
const read = <T>(page: Page, path: string): Promise<T> =>
  page.evaluate(async (path) => {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error("Synthetic metadata read failed");
    return response.json();
  }, path);
const write = <T>(page: Page, path: string, input: unknown, version?: number): Promise<T> =>
  page.evaluate(
    async ({ path, input, version }) => {
      const csrf = await fetch("/api/v1/auth/web/csrf", { cache: "no-store" }).then((r) =>
        r.json(),
      );
      const response = await fetch(path, {
        method: "POST",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf.csrf_token,
          "Idempotency-Key": crypto.randomUUID(),
          ...(version ? { "If-Match": `"${version}"` } : {}),
        },
        body: JSON.stringify(input),
      });
      if (!response.ok) throw new Error("Synthetic metadata setup failed");
      return response.json();
    },
    { path, input, version },
  );
function pdf() {
  const content =
    "BT /F1 22 Tf 40 260 Td (SYNTHETIC DOCUMENT RECEIPT) Tj 0 -45 Td (Household appliance purchase record) Tj 0 -45 Td (This fixture contains no personal data) Tj 0 -45 Td (Original document validation sample) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 360] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
  ];
  let body = "%PDF-1.4\n";
  const offsets = [0];
  for (const [i, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(body));
    body += `${i + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xref = Buffer.byteLength(body);
  body += `xref\n0 6\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((n) => `${String(n).padStart(10, "0")} 00000 n \n`)
    .join("")}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body);
}
async function image(page: Page, forbidden = false) {
  const data = await page.evaluate((forbidden) => {
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 440;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "white";
    context.fillRect(0, 0, 1200, 440);
    context.fillStyle = "black";
    context.font = "44px Arial";
    for (const [i, line] of [
      // A label printed only on cards is refused even when OCR misreads the date beside it.
      forbidden ? "SYNTHETIC CARD VALID THRU 12/28" : "SYNTHETIC DOCUMENT RECEIPT",
      "Household appliance purchase record",
      "This fixture contains no personal data",
      "Original document validation sample",
    ].entries())
      context.fillText(line, 40, 80 + i * 85);
    return canvas.toDataURL("image/png").split(",")[1]!;
  }, forbidden);
  return Buffer.from(data, "base64");
}
async function open(page: Page, path: string, kind: string) {
  await page.goto(path);
  const panel = page.getByRole("region", { name: `${kind} 첨부 문서`, exact: true });
  await panel.getByRole("button", { name: "첨부 문서 열기" }).click();
  return panel;
}
async function upload(page: Page, name: string, mimeType: string, buffer: Buffer) {
  const form = page.getByRole("region", { name: "새 문서 첨부", exact: true });
  await form.getByLabel("문서 파일", { exact: true }).setInputFiles({ name, mimeType, buffer });
  await form.getByRole("checkbox").check();
  await form.getByRole("button", { name: "문서 업로드", exact: true }).click();
  return page.getByRole("region", { name: "문서 상세", exact: true });
}

test("real scanner OCR original-byte attachments seven parents history conflicts pending and deletion", async ({
  page,
  context,
}) => {
  const responses: boolean[] = [];
  const mutations: { method: string; csrf: boolean; idem: boolean; version: boolean }[] = [];
  page.on("response", (response) => {
    if (/\/api\/v1\/(documents|document-links)(\/|\?|$)/.test(new URL(response.url()).pathname))
      responses.push(response.headers()["cache-control"]?.includes("no-store") === true);
  });
  page.on("request", (request) => {
    if (
      /\/api\/v1\/(documents|document-links)(\/|$)/.test(new URL(request.url()).pathname) &&
      request.method() !== "GET"
    ) {
      const h = request.headers();
      mutations.push({
        method: request.method(),
        csrf: !!h["x-csrf-token"],
        idem: !!h["idempotency-key"],
        version: !!h["if-match"],
      });
    }
  });
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
  await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 첨부 HTTPS");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "오늘의 살림", exact: true }),
  ).toBeVisible();
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  const member = await read<S["MemberResponse"]>(page, "/api/v1/me");
  const a = await write<S["ApplianceResponse"]>(page, "/api/v1/appliances", {
    name: "합성 첨부 가전",
    purchased_on: "2025-01-01",
  });
  const asset = await write<S["AssetResponse"]>(page, "/api/v1/assets", {
    name: "합성 첨부 자산",
    kind: "asset",
    category: "other",
    ownership_kind: "joint",
    household_share: "1",
    amount_basis: "owned",
    started_on: "2025-01-01",
  });
  const policy = await write<S["PolicyResponse"]>(page, "/api/v1/insurance/policies", {
    insurer: "합성 보험사",
    product_name: "합성 첨부 보험",
    coverage_start: "2025-01-01",
  });
  const medical = await write<S["CaseResponse"]>(page, "/api/v1/insurance/cases", {
    title: "합성 첨부 사건",
    patient_member_id: member.member_id,
    start_on: "2025-01-01",
  });
  const node = await write<S["MedicalNodeResponse"]>(
    page,
    `/api/v1/insurance/cases/${medical.id}/nodes`,
    { kind: "outpatient", label: "합성 첨부 외래" },
  );
  const expense = await write<S["EventReference"]>(page, "/api/v1/insurance/medical-expenses", {
    case_id: medical.id,
    node_id: node.id,
    amount_krw: "10000",
    occurred_on: "2025-01-01",
  });
  const claim = await write<S["ClaimResponse"]>(page, "/api/v1/insurance/claims", {
    case_id: medical.id,
    policy_id: policy.id,
    expense_ids: [expense.id],
  });
  console.log("SAFE_PHASE=DOCUMENT_PARENTS");
  const png = await image(page);
  const appliancePath = `/appliances/${a.id}`;
  await open(page, appliancePath, "가전");
  let detail = await upload(page, "합성 원본 영수증.png", "image/png", png);
  await expect(detail.getByText("보관 완료", { exact: true })).toBeVisible({ timeout: 90_000 });
  let documents = await read<S["DocumentListResponse"]>(page, "/api/v1/documents");
  const original = documents.items.find((r) => r.original_name === "합성 원본 영수증.png")!;
  expect(original.checksum_sha256).toBe(createHash("sha256").update(png).digest("hex"));
  expect(original.size_bytes).toBe(png.length);
  await detail
    .getByLabel("기기에 저장한 사본은 앱 잠금·문서 삭제 후에도 남는 것을 확인했어요")
    .check();
  const downloadWait = page.waitForEvent("download");
  await detail.getByRole("button", { name: "원본 파일 저장" }).click();
  const download = await downloadWait;
  const stream = await download.createReadStream();
  const parts: Buffer[] = [];
  for await (const part of stream!) parts.push(Buffer.from(part));
  expect(Buffer.concat(parts)).toEqual(png);
  console.log("SAFE_PHASE=DOCUMENT_ORIGINAL_BYTES");
  for (const [label, path] of [
    ["보험", `/insurance/policies/${policy.id}`],
    ["사건", `/insurance/cases/${medical.id}`],
    ["진료·약국", `/insurance/cases/${medical.id}/nodes/${node.id}`],
    ["의료비", `/insurance/expenses/${expense.id}`],
    ["청구", `/insurance/claims/${claim.id}`],
    ["자산", `/assets/${asset.id}`],
  ]) {
    const panel = await open(page, path!, label!);
    await panel.getByRole("button", { name: "기존 문서에서 연결·대기 기록 찾기" }).click();
    await panel.getByRole("button", { name: "합성 원본 영수증.png", exact: true }).click();
    detail = panel.getByRole("region", { name: "문서 상세", exact: true });
    await detail.getByRole("button", { name: "현재 대상에 문서 연결" }).click();
    await expect(detail.getByText("현재 대상에 연결 완료", { exact: true })).toBeVisible();
  }
  const seven = await read<S["DocumentResponse"]>(page, `/api/v1/documents/${original.id}`);
  expect(seven.active_link_count).toBe(7);
  expect(seven.version).toBe(8);
  console.log("SAFE_PHASE=DOCUMENT_SEVEN_LINKS");
  await open(page, appliancePath, "가전");
  await page.getByRole("button", { name: "합성 원본 영수증.png", exact: true }).click();
  detail = page.getByRole("region", { name: "문서 상세", exact: true });
  await detail.getByLabel("문서 연결 종료·삭제 사유").fill("합성 가전 연결 종료");
  const currentLink = detail.getByRole("listitem").filter({ hasText: "가전 · 현재 대상" });
  await currentLink.getByRole("button", { name: "이 문서 연결 종료" }).click();
  await expect(detail.getByText("문서 연결 종료 완료", { exact: true })).toBeVisible();
  const second = await context.newPage();
  await open(second, appliancePath, "가전");
  await second.getByRole("button", { name: "기존 문서에서 연결·대기 기록 찾기" }).click();
  await second.getByRole("button", { name: "합성 원본 영수증.png", exact: true }).click();
  const secondDetail = second.getByRole("region", { name: "문서 상세", exact: true });
  await secondDetail.getByRole("button", { name: "현재 대상에 문서 연결" }).click();
  await expect(secondDetail.getByText("현재 대상에 연결 완료", { exact: true })).toBeVisible();
  await second.close();
  await detail.getByLabel("문서 연결 종료·삭제 사유").fill("합성 동시 수정 삭제 사유");
  await detail.getByLabel("모든 연결 대상에서 이 문서를 삭제하는 것을 확인했어요").check();
  await detail.getByRole("button", { name: "문서 삭제", exact: true }).click();
  await expect(detail.getByRole("alert")).toBeVisible();
  await detail.getByRole("button", { name: "현재 문서·연결 이력 비교" }).click();
  await expect(
    detail.getByText("현재 연결: 7개 · 전체 연결 이력 8개", { exact: true }),
  ).toBeVisible();
  await detail.getByRole("button", { name: "현재 내용을 확인하고 새 작업 준비" }).click();
  await expect(detail.getByLabel("문서 연결 종료·삭제 사유")).toHaveValue(
    "합성 동시 수정 삭제 사유",
  );
  console.log("SAFE_PHASE=DOCUMENT_CONFLICT");
  detail = await upload(page, "합성 원본 문서.pdf", "application/pdf", pdf());
  await expect(detail.getByText("합성 원본 문서.pdf", { exact: true })).toBeVisible({
    timeout: 90_000,
  });
  await expect(detail.getByText("보관 완료", { exact: true })).toBeVisible({ timeout: 90_000 });
  documents = await read<S["DocumentListResponse"]>(page, "/api/v1/documents");
  const pdfRow = documents.items.find((r) => r.original_name === "합성 원본 문서.pdf")!;
  expect(pdfRow.checksum_sha256).toBe(createHash("sha256").update(pdf()).digest("hex"));
  console.log("SAFE_PHASE=DOCUMENT_PDF");
  await upload(page, "합성 제한 문서.png", "image/png", await image(page, true));
  await expect(
    page.getByRole("region", { name: "새 문서 첨부", exact: true }).getByRole("alert"),
  ).toContainText("카드 사진", { timeout: 90_000 });
  // The server removes a refused upload instead of leaving a pending record to clean up.
  documents = await read<S["DocumentListResponse"]>(page, "/api/v1/documents");
  expect(documents.items.some((r) => r.original_name === "합성 제한 문서.png")).toBe(false);
  await expect(page.getByRole("button", { name: "합성 제한 문서.png", exact: true })).toHaveCount(
    0,
  );
  console.log("SAFE_PHASE=DOCUMENT_REJECTION_REMOVED");
  await page.getByRole("button", { name: "합성 원본 영수증.png", exact: true }).click();
  detail = page.getByRole("region", { name: "문서 상세", exact: true });
  await detail.getByLabel("문서 연결 종료·삭제 사유").fill("합성 원본 삭제 정리");
  await detail.getByLabel("모든 연결 대상에서 이 문서를 삭제하는 것을 확인했어요").check();
  await detail.getByRole("button", { name: "문서 삭제", exact: true }).click();
  await expect(detail.getByText("삭제됨", { exact: true })).toBeVisible();
  const history = await read<S["DocumentLinkListResponse"]>(
    page,
    `/api/v1/documents/${original.id}/links`,
  );
  expect(history.items).toHaveLength(8);
  expect(history.items.every((r) => !r.active)).toBe(true);
  const blocked = await page.evaluate(
    async (id) => (await fetch(`/api/v1/documents/${id}/download`, { cache: "no-store" })).status,
    original.id,
  );
  expect(blocked).toBe(409);
  const untouched = await read<S["ExpenseResponse"]>(
    page,
    `/api/v1/insurance/medical-expenses/${expense.id}`,
  );
  expect(untouched.cash.amount_krw).toBe("10000");
  const storage = await page.evaluate(async () => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
    caches: await caches.keys(),
  }));
  expect(storage).toEqual({ local: [], session: [], caches: [] });
  expect(responses.length).toBeGreaterThan(20);
  expect(responses.every(Boolean)).toBe(true);
  expect(mutations.every((m) => m.csrf && m.idem)).toBe(true);
  expect(mutations.filter((m) => m.method === "PUT").every((m) => m.version)).toBe(true);
  console.log("SAFE_PHASE=DOCUMENT_DELETE_ACCESS");
});
