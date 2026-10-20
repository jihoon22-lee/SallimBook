import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { bytes, digest, documentRow, documentLink, mockDocuments } from "./support/documents";
import { uid } from "./support/finance";
const appliance = `/appliances/${uid(100)}`;
const panel = (page: Page, label = "가전") =>
  page.getByRole("region", { name: `${label} 첨부 문서`, exact: true });
async function open(page: Page, path = appliance, label = "가전") {
  await page.goto(path);
  await panel(page, label).getByRole("button", { name: "첨부 문서 열기" }).click();
  return panel(page, label);
}
async function select(page: Page, name = "합성 영수증.png") {
  await panel(page).getByRole("button", { name, exact: true }).click();
  return page.getByRole("region", { name: "문서 상세", exact: true });
}
async function file(page: Page) {
  const form = page.getByRole("region", { name: "새 문서 첨부", exact: true });
  await form
    .getByLabel("문서 파일", { exact: true })
    .setInputFiles({ name: "합성 새 문서.png", mimeType: "image/png", buffer: bytes });
  await form.getByRole("checkbox").check();
  return form;
}
for (const [kind, label, path, id] of [
  ["policy", "보험", `/insurance/policies/${uid(80)}`, 80],
  ["case", "사건", `/insurance/cases/${uid(90)}`, 90],
  ["medical_node", "진료·약국", `/insurance/cases/${uid(90)}/nodes/${uid(91)}`, 91],
  ["expense", "의료비", `/insurance/expenses/${uid(1000)}`, 1000],
  ["claim", "청구", `/insurance/claims/${uid(1200)}`, 1200],
  ["appliance", "가전", appliance, 100],
  ["asset", "자산", `/assets/${uid(10)}`, 10],
] as const)
  test(`document panel authorizes and lists ${kind} parent`, async ({ page }) => {
    const state = await mockDocuments(page);
    state.links[0]!.target = { kind, id: uid(id) };
    await page.goto(path);
    await expect(panel(page, label)).toBeVisible();
    expect(state.reads).toHaveLength(0);
    await panel(page, label).getByRole("button", { name: "첨부 문서 열기" }).click();
    await expect(
      panel(page, label).getByRole("button", { name: "합성 영수증.png", exact: true }),
    ).toBeVisible();
    const list = state.reads.find((r) => r.path === "/api/v1/documents")!;
    expect(list.query.get("target_kind")).toBe(kind);
    expect(list.query.get("target_id")).toBe(uid(id));
  });
test("web upload hashes same original bytes and sends typed metadata raw PUT CSRF version and keys", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  await open(page);
  const form = await file(page);
  await form.getByRole("button", { name: "문서 업로드", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "문서 상세", exact: true })
      .getByText("보관 완료", { exact: true }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(2);
  const [create, upload] = state.writes;
  expect(create!.body).toMatchObject({
    original_name: "합성 새 문서.png",
    checksum_sha256: digest,
    size_bytes: bytes.length,
    contains_no_card_data: true,
    target: { kind: "appliance", id: uid(100) },
  });
  expect(upload!.bytes).toEqual(bytes);
  expect(upload!.headers["content-type"]).toBe("application/octet-stream");
  expect(upload!.version).toBe('"1"');
  expect(state.writes.every((w) => w.key && w.headers["x-csrf-token"])).toBe(true);
  expect(new Set(state.writes.map((w) => w.key)).size).toBe(2);
});
for (const failure of ["create-before", "create-after", "upload-before", "upload-after"] as const)
  test(`lost ${failure} preserves operation and never creates duplicate`, async ({ page }) => {
    const state = await mockDocuments(page);
    state.failure = failure;
    await open(page);
    const form = await file(page);
    await form.getByRole("button", { name: "문서 업로드", exact: true }).click();
    await expect(form.getByRole("alert")).toBeVisible();
    await form.getByRole("button", { name: "같은 파일로 업로드 재시도" }).click();
    await expect(
      page
        .getByRole("region", { name: "문서 상세", exact: true })
        .getByText("보관 완료", { exact: true }),
    ).toBeVisible();
    expect(state.documents).toHaveLength(2);
    const creates = state.writes.filter(
      (w) => w.method === "POST" && w.path === "/api/v1/documents",
    );
    const uploads = state.writes.filter((w) => w.method === "PUT");
    expect(new Set(creates.map((w) => w.key)).size).toBe(1);
    expect(new Set(uploads.map((w) => w.key)).size).toBe(1);
    if (failure === "upload-after") expect(uploads).toHaveLength(1);
  });
test("attachment rejects invalid file type and requires explicit no-card acknowledgement", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  await open(page);
  const form = page.getByRole("region", { name: "새 문서 첨부", exact: true });
  await form
    .getByLabel("문서 파일", { exact: true })
    .setInputFiles({ name: "synthetic.pdf", mimeType: "image/png", buffer: bytes });
  await expect(form.getByRole("alert")).toContainText("형식");
  await expect(form.getByRole("button", { name: "문서 업로드" })).toBeDisabled();
  await form
    .getByLabel("문서 파일", { exact: true })
    .setInputFiles({ name: "synthetic.png", mimeType: "image/png", buffer: bytes });
  await expect(form.getByRole("button", { name: "문서 업로드" })).toBeDisabled();
  expect(state.writes).toHaveLength(0);
});
test("end preserves orphan original then relink preserves history and explicit delete ends all links", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  await open(page);
  const detail = await select(page);
  await detail.getByLabel("문서 연결 종료·삭제 사유").fill("합성 연결 종료");
  await detail.getByRole("button", { name: "이 문서 연결 종료" }).click();
  await expect(detail.getByText("연결 없는 보관 문서", { exact: true })).toBeVisible();
  expect(state.documents[0]!.state).toBe("ready");
  await expect(detail.getByRole("button", { name: "원본 파일 저장" })).toHaveCount(0);
  await detail.getByRole("button", { name: "현재 대상에 문서 연결" }).click();
  await expect(detail.getByText("보관 완료", { exact: true })).toBeVisible();
  expect(state.links).toHaveLength(2);
  await detail.getByLabel("문서 연결 종료·삭제 사유").fill("합성 삭제");
  await detail.getByLabel("모든 연결 대상에서 이 문서를 삭제하는 것을 확인했어요").check();
  await detail.getByRole("button", { name: "문서 삭제", exact: true }).click();
  await expect(detail.getByText("삭제됨", { exact: true })).toBeVisible();
  expect(state.links.every((r) => !r.active)).toBe(true);
  expect(state.writes.map((w) => w.version)).toEqual(['"1"', '"2"', '"3"']);
});
test("mutation response loss replays exact key and reason once", async ({ page }) => {
  const state = await mockDocuments(page);
  state.failure = "mutation-after";
  await open(page);
  const detail = await select(page);
  await detail.getByLabel("문서 연결 종료·삭제 사유").fill("합성 종료 원문");
  await detail.getByRole("button", { name: "이 문서 연결 종료" }).click();
  await expect(detail.getByRole("alert")).toBeVisible();
  await expect(detail.getByLabel("문서 연결 종료·삭제 사유")).toBeDisabled();
  await detail.getByRole("button", { name: "같은 문서 작업 재시도" }).click();
  await expect(detail.getByText("연결 없는 보관 문서", { exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(2);
  expect(state.writes[0]!.key).toBe(state.writes[1]!.key);
  expect(state.links[0]!.version).toBe(2);
});
test("409 retains reason and compares all link pages before explicit new action", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  state.conflict = true;
  state.pageSize = 1;
  state.links.push(
    documentLink(8101, {
      active: false,
      ended_at: "2026-10-17T00:00:00Z",
      end_reason: "합성 과거 종료",
      target: { kind: "case", id: uid(90) },
    }),
  );
  await open(page);
  const detail = await select(page);
  await detail.getByLabel("문서 연결 종료·삭제 사유").fill("합성 비교 사유");
  await detail.getByRole("button", { name: "이 문서 연결 종료" }).click();
  await expect(detail.getByRole("alert")).toBeVisible();
  await expect(detail.getByRole("button", { name: "같은 문서 작업 재시도" })).toBeDisabled();
  await detail.getByRole("button", { name: "현재 문서·연결 이력 비교" }).click();
  await expect(
    detail.getByText("현재 연결: 1개 · 전체 연결 이력 2개", { exact: true }),
  ).toBeVisible();
  await detail.getByRole("button", { name: "현재 내용을 확인하고 새 작업 준비" }).click();
  await expect(detail.getByLabel("문서 연결 종료·삭제 사유")).toHaveValue("합성 비교 사유");
  await detail.getByRole("button", { name: "이 문서 연결 종료" }).click();
  await expect(detail.getByText("연결 없는 보관 문서", { exact: true })).toBeVisible();
  expect(state.writes.map((w) => w.version)).toEqual(['"1"', '"2"']);
  expect(state.writes[0]!.key).not.toBe(state.writes[1]!.key);
});
test("global cursor picker finds orphan pending expired and escaped names without inline rendering", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  state.pageSize = 1;
  state.documents.push(
    documentRow(8001, {
      original_name: "<img src=x onerror=alert(1)>.png",
      active_link_count: 0,
      orphaned_at: "2026-10-17T00:00:00Z",
    }),
    documentRow(8002, {
      original_name: "합성 만료.png",
      state: "pending",
      active_link_count: 0,
      stored_at: null,
      pending_expires_at: "2020-01-01T00:00:00Z",
    }),
  );
  await open(page);
  await panel(page).getByRole("button", { name: "기존 문서에서 연결·대기 기록 찾기" }).click();
  await panel(page).getByRole("button", { name: "문서 더 보기", exact: true }).click();
  await panel(page)
    .getByRole("button", { name: "<img src=x onerror=alert(1)>.png", exact: true })
    .click();
  const detail = page.getByRole("region", { name: "문서 상세", exact: true });
  await expect(detail.locator("img,iframe,embed,object")).toHaveCount(0);
  await detail.getByRole("button", { name: "현재 대상에 문서 연결" }).click();
  await expect(detail.getByText("보관 완료", { exact: true })).toBeVisible();
  await panel(page).getByRole("button", { name: "문서 더 보기", exact: true }).click();
  await panel(page).getByRole("button", { name: "문서 더 보기", exact: true }).click();
  await panel(page).getByRole("button", { name: "합성 만료.png", exact: true }).click();
  await expect(detail.getByText("업로드 기한 만료", { exact: true })).toBeVisible();
  await expect(detail.getByRole("region", { name: "대기 파일 업로드" })).toHaveCount(0);
});
test("explicit original save verifies bytes and revokes opaque URL without storage or preview", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  await page.addInitScript(() => {
    const made: string[] = [];
    const revoked: string[] = [];
    Object.assign(window, { documentUrls: { made, revoked } });
    const create = URL.createObjectURL;
    const revoke = URL.revokeObjectURL;
    URL.createObjectURL = (blob) => {
      const url = create(blob);
      made.push(url);
      return url;
    };
    URL.revokeObjectURL = (url) => {
      revoked.push(url);
      revoke(url);
    };
  });
  await open(page);
  const detail = await select(page);
  await expect(detail.getByRole("button", { name: "원본 파일 저장" })).toBeDisabled();
  await detail
    .getByLabel("기기에 저장한 사본은 앱 잠금·문서 삭제 후에도 남는 것을 확인했어요")
    .check();
  const waiting = page.waitForEvent("download");
  await detail.getByRole("button", { name: "원본 파일 저장" }).click();
  const download = await waiting;
  expect(download.suggestedFilename()).toBe("합성 영수증.png");
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  expect(Buffer.concat(chunks)).toEqual(bytes);
  expect(state.reads.filter((r) => r.path.endsWith("/download"))).toHaveLength(1);
  await expect.poll(() => page.evaluate(() => (window as any).documentUrls.revoked.length)).toBe(1);
  const storage = await page.evaluate(async () => ({
    urls: (window as any).documentUrls,
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
    caches: await caches.keys(),
  }));
  expect(storage.urls.made).toEqual(storage.urls.revoked);
  expect(storage.local).toEqual([]);
  expect(storage.session).toEqual([]);
  expect(storage.caches).toEqual([]);
  await expect(detail.locator("iframe,object,embed,img")).toHaveCount(0);
});
for (const [code, status, message] of [
  ["DOCUMENT_STORAGE_QUOTA_EXCEEDED", 413, "보관 한도"],
  ["DOCUMENT_STORAGE_CAPACITY_UNAVAILABLE", 503, "보관할 공간"],
  ["DOCUMENT_UPLOAD_BUSY", 503, "다른 파일"],
  ["DOCUMENT_UPLOAD_TIMEOUT", 408, "전송 시간"],
  ["DOCUMENT_CARD_DATA", 422, "카드 사진"],
  ["DOCUMENT_UNREADABLE", 422, "읽기 어려워"],
  ["DOCUMENT_IMAGE_UNSUPPORTED", 422, "JPEG로 다시 저장"],
  ["DOCUMENT_SCAN_UNAVAILABLE", 503, "안전 검사"],
] as const)
  test(`safe ${status} ${code} feedback preserves selected attempt`, async ({ page }) => {
    const state = await mockDocuments(page);
    state.error = code;
    state.status = status;
    await open(page);
    const form = await file(page);
    await form.getByRole("button", { name: "문서 업로드", exact: true }).click();
    await expect(form.getByRole("alert")).toContainText(message);
    await expect(page.getByText("UNTRUSTED_DOCUMENT_ERROR")).toHaveCount(0);
    await expect(form.getByRole("button", { name: "같은 파일로 업로드 재시도" })).toBeEnabled();
  });
test("foreign and unauthenticated parents expose no attachment operations", async ({ page }) => {
  const state = await mockDocuments(page);
  await page.goto(`/appliances/${uid(999)}`);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
  await page.route("**/api/v1/me", (r) =>
    r.fulfill({
      status: 401,
      json: { error: { code: "UNAUTHENTICATED", message: "hidden", request_id: "synthetic" } },
    }),
  );
  await page.goto(appliance);
  await expect(page.getByText("로그인 후 함께 관리할 수 있어요.")).toHaveCount(0);
  await expect(panel(page)).toHaveCount(0);
  expect(state.writes).toHaveLength(0);
  expect(state.reads).toHaveLength(0);
});
test("pending upload resumes only matching bytes without a second metadata record", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  state.documents[0]!.state = "pending";
  state.documents[0]!.stored_at = null;
  await open(page);
  const detail = await select(page);
  const resume = detail.getByRole("region", { name: "대기 파일 업로드", exact: true });
  await expect(resume).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    page.viewportSize()!.width,
  );
  await resume.getByLabel("문서 파일", { exact: true }).setInputFiles({
    name: "합성 영수증.png",
    mimeType: "image/png",
    buffer: Buffer.from("DIFFERENT SYNTHETIC BYTES"),
  });
  await resume.getByRole("checkbox").check();
  await resume.getByRole("button", { name: "문서 업로드", exact: true }).click();
  await expect(resume.getByRole("alert")).toContainText("대기 기록과 파일이 달라요");
  expect(state.writes).toHaveLength(0);
  await resume
    .getByLabel("문서 파일", { exact: true })
    .setInputFiles({ name: "합성 영수증.png", mimeType: "image/png", buffer: bytes });
  await resume.getByRole("checkbox").check();
  await resume.getByRole("button", { name: "문서 업로드", exact: true }).click();
  await expect(detail.getByText("보관 완료", { exact: true })).toBeVisible();
  expect(state.documents).toHaveLength(1);
  expect(state.writes.map((w) => w.method)).toEqual(["PUT"]);
});
test("upload version conflict compares metadata and requires explicit current version adoption", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  state.conflict = true;
  await open(page);
  const form = await file(page);
  await form.getByRole("button", { name: "문서 업로드", exact: true }).click();
  await expect(form.getByRole("alert")).toBeVisible();
  await expect(form.getByRole("button", { name: "같은 파일로 업로드 재시도" })).toBeDisabled();
  await form.getByRole("button", { name: "현재 업로드 상태 비교" }).click();
  await expect(form.getByText(/현재: 합성 새 문서.png.*버전 2/)).toBeVisible();
  await expect(form.getByRole("button", { name: "같은 파일로 업로드 재시도" })).toBeDisabled();
  await form.getByRole("button", { name: "현재 버전으로 같은 파일 업로드 준비" }).click();
  await form.getByRole("button", { name: "같은 파일로 업로드 재시도" }).click();
  await expect(
    page
      .getByRole("region", { name: "문서 상세", exact: true })
      .getByText("보관 완료", { exact: true }),
  ).toBeVisible();
  const uploads = state.writes.filter((w) => w.method === "PUT");
  expect(uploads.map((w) => w.version)).toEqual(['"1"', '"2"']);
  expect(uploads[0]!.key).not.toBe(uploads[1]!.key);
  expect(state.documents).toHaveLength(2);
});
test("cancelled late web upload reconciles committed content without a duplicate PUT", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  state.delay = 600;
  await open(page);
  const form = await file(page);
  await form.getByRole("button", { name: "문서 업로드", exact: true }).click();
  await expect.poll(() => state.documents[1]?.state).toBe("ready");
  await form.getByRole("button", { name: "문서 요청 대기 중단" }).click();
  await expect(form.getByRole("alert")).toContainText("대기를 중단");
  state.delay = 0;
  await form.getByRole("button", { name: "같은 파일로 업로드 재시도" }).click();
  await expect(
    page
      .getByRole("region", { name: "문서 상세", exact: true })
      .getByText("보관 완료", { exact: true }),
  ).toBeVisible();
  expect(state.writes.filter((w) => w.method === "PUT")).toHaveLength(1);
  expect(state.documents).toHaveLength(2);
});
test("pagehide discards chosen file and acknowledgement", async ({ page }) => {
  const state = await mockDocuments(page);
  await open(page);
  const form = await file(page);
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  await expect(form.getByLabel("문서 파일", { exact: true })).toHaveValue("");
  await expect(form.getByRole("checkbox")).not.toBeChecked();
  await expect(form.getByRole("button", { name: "문서 업로드", exact: true })).toBeDisabled();
  expect(state.writes).toHaveLength(0);
});
test("web session loss unmounts attachment draft without rendering server details", async ({
  page,
}) => {
  const state = await mockDocuments(page);
  state.error = "UNAUTHENTICATED";
  state.status = 401;
  await open(page);
  const form = await file(page);
  await form.getByRole("button", { name: "문서 업로드", exact: true }).click();
  await expect(panel(page)).toHaveCount(0);
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await expect(page.getByText("UNTRUSTED_DOCUMENT_ERROR")).toHaveCount(0);
});
