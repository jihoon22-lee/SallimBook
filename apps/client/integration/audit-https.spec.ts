import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { BrowserContext, Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
type S = components["schemas"];
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as {
  login: string;
  password: string;
  control: string;
  foreign_login: string;
  foreign_password: string;
};
test.setTimeout(180_000);
test.use({ actionTimeout: 15_000, navigationTimeout: 20_000 });
async function login(page: Page, foreign = false) {
  await page.goto("/login");
  await page
    .getByLabel("로그인 이름", { exact: true })
    .fill(foreign ? fixture.foreign_login : fixture.login);
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill(foreign ? fixture.foreign_password : fixture.password);
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 감사 HTTPS");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
}
async function read<T>(page: Page, path: string): Promise<T> {
  return page.evaluate(async (path) => {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error("Synthetic metadata read failed");
    return response.json();
  }, path);
}
async function seed(page: Page, count: number, foreign = false) {
  return page.evaluate(
    async ({ count, foreign }) => {
      const csrf = await fetch("/api/v1/auth/web/csrf", { cache: "no-store" }).then((response) =>
        response.json(),
      );
      const ids: string[] = [];
      for (let i = 0; i < count; i++) {
        const response = await fetch("/api/v1/appliances", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf.csrf_token,
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify({
            name: foreign ? "FOREIGN_AUDIT_VALUE" : "SYNTHETIC_PRIVATE_AUDIT_VALUE",
            purchased_on: "2025-01-01",
            note: "SYNTHETIC_PRIVATE_AUDIT_NOTE",
          }),
        });
        if (response.status !== 201) throw new Error("Synthetic audit seed failed");
        ids.push((await response.json()).id);
      }
      if (!foreign) {
        const response = await fetch(`/api/v1/appliances/${ids[0]}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf.csrf_token,
            "Idempotency-Key": crypto.randomUUID(),
            "If-Match": '"1"',
          },
          body: JSON.stringify({ note: "SYNTHETIC_PRIVATE_AUDIT_UPDATED" }),
        });
        if (!response.ok) throw new Error("Synthetic audit update failed");
      }
      return ids;
    },
    { count, foreign },
  );
}

test("real audit UI paginates metadata filters current household and rejects expired sessions", async ({
  page,
  browser,
}) => {
  let foreignContext: BrowserContext | undefined;
  const requests: { method: string; query: Record<string, string> }[] = [];
  const noStore: boolean[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/audit-events")
      requests.push({ method: request.method(), query: Object.fromEntries(url.searchParams) });
  });
  page.on("response", (response) => {
    if (new URL(response.url()).pathname === "/api/v1/audit-events")
      noStore.push(response.headers()["cache-control"] === "no-store");
  });
  try {
    await login(page);
    const member = await read<S["MemberResponse"]>(page, "/api/v1/me");
    const own = await seed(page, 51);
    foreignContext = await browser.newContext({ baseURL: process.env.SALLIMBOOK_HTTPS_ORIGIN });
    const foreign = await foreignContext.newPage();
    await login(foreign, true);
    const other = await read<S["MemberResponse"]>(foreign, "/api/v1/me");
    const foreignIds = await seed(foreign, 1, true);
    console.log("SAFE_PHASE=AUDIT_SEEDED");
    await page.goto("/settings");
    await expect(page.getByRole("main").getByText(/웹 클라이언트 버전/)).toBeVisible();
    await page
      .getByRole("main")
      .getByRole("link", { name: /^감사 이력/ })
      .click();
    const list = page.getByRole("region", { name: "감사 기록 목록", exact: true });
    await expect(list.getByRole("listitem")).toHaveCount(50);
    await page.getByRole("button", { name: "감사 기록 더 보기", exact: true }).click();
    // Sign-ins are audited too, so the second page holds the seeded rows plus this user's logins.
    await expect(page.getByRole("button", { name: "감사 기록 더 보기", exact: true })).toHaveCount(
      0,
    );
    const shown = await list.getByRole("listitem").count();
    expect(requests.slice(0, 2).map((item) => !!item.query.cursor)).toEqual([false, true]);
    for (const value of [
      "SYNTHETIC_PRIVATE_AUDIT_VALUE",
      "SYNTHETIC_PRIVATE_AUDIT_NOTE",
      "SYNTHETIC_PRIVATE_AUDIT_UPDATED",
      "FOREIGN_AUDIT_VALUE",
      foreignIds[0]!,
    ])
      await expect(page.getByText(value, { exact: true })).toHaveCount(0);
    const metadata = await read<S["AuditListResponse"]>(page, "/api/v1/audit-events?limit=200");
    // Security events (sign-ins, the setup invitation) sit beside the seeded appliance rows.
    const seeded = metadata.items.filter((row) => row.entity_type === "appliance");
    const security = metadata.items.filter((row) => row.entity_type !== "appliance");
    expect(shown).toBe(metadata.items.length);
    expect(seeded).toHaveLength(52);
    expect(security.some((row) => row.entity_type === "registered_device")).toBe(true);
    expect(
      security.every(
        (row) =>
          ["registered_device", "invitation", "passkey"].includes(row.entity_type) &&
          row.actor_member_id === member.member_id,
      ),
    ).toBe(true);
    expect(
      seeded.every(
        (row) => row.actor_member_id === member.member_id && own.includes(row.entity_id),
      ),
    ).toBe(true);
    expect(
      metadata.items.every(
        (row) =>
          !Object.hasOwn(row, "safe_diff") &&
          !Object.hasOwn(row, "before") &&
          !Object.hasOwn(row, "after"),
      ),
    ).toBe(true);
    console.log("SAFE_PHASE=AUDIT_PAGINATION_METADATA");
    await page.getByLabel("대상 종류", { exact: true }).selectOption("appliance");
    await page.getByLabel("작업 종류", { exact: true }).selectOption("update");
    await page.getByLabel("작업 구성원", { exact: true }).selectOption(member.member_id);
    await page.getByLabel("대상 ID (선택)").fill(own[0]!);
    await page.getByRole("button", { name: "조건 적용", exact: true }).click();
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await expect(list.getByText("변경 필드: note", { exact: true })).toBeVisible();
    await expect(list.getByText("버전: 1 → 2", { exact: true })).toBeVisible();
    const cross = await page.evaluate(async (id) => {
      const response = await fetch(`/api/v1/audit-events?actor_member_id=${id}`, {
        cache: "no-store",
      });
      return { status: response.status, body: await response.json() };
    }, other.member_id);
    expect(cross.status).toBe(404);
    expect(Object.hasOwn(cross.body, "items")).toBe(false);
    console.log("SAFE_PHASE=AUDIT_FILTERS_HOUSEHOLD");
    expect(
      await page.evaluate(
        async (control) =>
          (
            await fetch("/__test/expire-freshness", {
              method: "POST",
              headers: { "X-Test-Control": control },
            })
          ).status,
        fixture.control,
      ),
    ).toBe(200);
    await page.getByRole("button", { name: "처음부터 다시 불러오기", exact: true }).click();
    await expect(list.getByRole("listitem")).toHaveCount(1);
    expect(requests.every((item) => item.method === "GET")).toBe(true);
    expect(noStore.length).toBeGreaterThanOrEqual(5);
    expect(noStore.every(Boolean)).toBe(true);
    await page.evaluate(async () => {
      const csrf = await fetch("/api/v1/auth/web/csrf", { cache: "no-store" }).then((response) =>
        response.json(),
      );
      const response = await fetch("/api/v1/auth/web/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf.csrf_token },
      });
      if (!response.ok) throw new Error("Synthetic logout failed");
    });
    await page.getByRole("button", { name: "처음부터 다시 불러오기", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "로그인이 필요해요", exact: true }),
    ).toBeVisible();
    await expect(list).toHaveCount(0);
    expect(
      await page.evaluate(async () => ({
        local: localStorage.length,
        session: sessionStorage.length,
        cache: (await caches.keys()).length,
      })),
    ).toEqual({ local: 0, session: 0, cache: 0 });
    console.log("SAFE_PHASE=AUDIT_SESSION_STORAGE");
  } finally {
    await foreignContext?.close();
  }
});
