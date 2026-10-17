import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { uid } from "./support/finance";
test.use({ actionTimeout: 5_000, trace: "off", screenshot: "off", video: "off" });
type Snapshot = { id: string; version: number; note: string };
const original: Snapshot = { id: uid(9900), version: 1, note: "합성 최초 내용" };
const current: Snapshot = { ...original, version: 2, note: "합성 수정 내용" };
const review = (page: Page) => page.getByTestId("homecare-delete-regression");
const confirmation = (page: Page) => review(page).getByLabel("오등록 합성 항목의 실제 삭제를 확인했어요", { exact: true });
const submit = (page: Page) => review(page).getByRole("button", { name: "오등록 항목 실제 삭제", exact: true });
async function open(page: Page) { await review(page).getByRole("button", { name: "오등록 항목 삭제 검토", exact: true }).click(); }
async function replace(page: Page, next: Snapshot) {
  await page.evaluate((next) => (window as any).__homecareDeleteRegression.replace(next), next);
  await expect(review(page).getByLabel("부모의 현재 버전", { exact: true })).toHaveText(`${next.id}:${next.version}`);
}
async function server(page: Page, next: Snapshot) { await page.evaluate((next) => (window as any).__homecareDeleteRegression.server(next), next); }
async function snapshot(page: Page) { return page.evaluate(() => (window as any).__homecareDeleteRegression.snapshot() as { requests: Snapshot[]; deleted: number; aborted: boolean[] }); }

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/me", (route) => route.fulfill({ status: 401, json: { error: { code: "UNAUTHENTICATED", message: "Synthetic fixture", request_id: "synthetic" } } }));
  // Load the usual Vite React runtime/preamble, then mount the real reusable component separately.
  await page.goto("/__homecare-delete-regression"); await expect(page.getByRole("heading", { level: 1 })).toHaveText("페이지를 찾을 수 없어요");
  await page.evaluate(async (initial: Snapshot) => {
    const moduleUrl = (path: string) => performance.getEntriesByType("resource").find((entry) => new URL(entry.name).pathname === path)?.name ?? path;
    const reactPath = moduleUrl("/node_modules/.vite/deps/react.js"), domPath = moduleUrl("/node_modules/.vite/deps/react-dom_client.js"), routerPath = moduleUrl("/node_modules/.vite/deps/react-router.js");
    const componentPath = "/src/features/homecare/DeleteHomecare.tsx", authPath = "/src/features/auth/AuthProvider.tsx", apiPath = "/src/platform/api.ts";
    const [{ default: React }, { default: { createRoot } }, { MemoryRouter }, { DeleteHomecare }, { AuthProvider }, { ApiError }] = await Promise.all([import(reactPath), import(domPath), import(routerPath), import(componentPath), import(authPath), import(apiPath)]);
    document.getElementById("root")!.style.display = "none";
    const element = document.createElement("div"); element.style.padding = "24px"; element.dataset.testid = "homecare-delete-regression"; document.body.append(element); const root = createRoot(element);
    const state = { latest: { ...initial }, requests: [] as Snapshot[], signals: [] as AbortSignal[], deleted: 0, wait: false, pending: [] as (() => void)[] };
    const draw = (row: Snapshot) => root.render(React.createElement(MemoryRouter, null, React.createElement(AuthProvider, null,
      React.createElement("output", { "aria-label": "부모의 현재 버전" }, `${row.id}:${row.version}`),
      React.createElement(DeleteHomecare, {
        initial: { ...row }, label: "항목", name: "합성 항목", listPath: "/consumables",
        read: async () => ({ ...state.latest }),
        remove: async (value: Snapshot, signal: AbortSignal) => {
          state.requests.push({ ...value }); state.signals.push(signal);
          if (value.id !== state.latest.id || value.version !== state.latest.version) throw new ApiError(409, "VERSION_CONFLICT");
          if (state.wait) await new Promise<void>((resolve) => state.pending.push(resolve));
        },
        render: (value: Snapshot) => React.createElement("p", null, `비교한 내용: ${value.note}`),
        deleted: () => { state.deleted++; },
      }),
    )));
    Object.assign(window, { __homecareDeleteRegression: {
      replace: draw, server: (row: Snapshot) => { state.latest = { ...row }; }, hold: () => { state.wait = true; },
      release: () => { state.wait = false; state.pending.splice(0).forEach((resolve) => resolve()); },
      snapshot: () => ({ requests: state.requests, deleted: state.deleted, aborted: state.signals.map((signal) => signal.aborted) }),
    } });
    draw(initial);
  }, original);
  await expect(review(page).getByRole("button", { name: "오등록 항목 삭제 검토", exact: true })).toBeVisible();
});

test("idle deletion uses a new parent version without an intermediate unmount", async ({ page }) => {
  await server(page, current); await replace(page, current); await open(page); await confirmation(page).check(); await submit(page).click();
  await expect.poll(async () => (await snapshot(page)).requests.map((row) => row.version)).toEqual([2]);
  await expect.poll(async () => (await snapshot(page)).deleted).toBe(1);
});

for (const change of ["version", "identity"] as const) test(`a new ${change} closes acknowledged review and requires fresh consent`, async ({ page }) => {
  const next = change === "version" ? current : { ...original, id: uid(9901), note: "합성 다른 항목" };
  await open(page); await confirmation(page).check(); await server(page, next); await replace(page, next);
  await expect(confirmation(page)).toHaveCount(0); await expect(review(page).getByRole("button", { name: "오등록 항목 삭제 검토", exact: true })).toBeVisible();
  expect((await snapshot(page)).requests).toHaveLength(0);
  await open(page); await expect(confirmation(page)).not.toBeChecked(); await expect(submit(page)).toBeDisabled(); await confirmation(page).check(); await submit(page).click();
  await expect.poll(async () => (await snapshot(page)).requests).toEqual([next]);
});

test("same snapshot rerenders preserve explicit conflict comparison and renewed consent", async ({ page }) => {
  await open(page); await confirmation(page).check(); await replace(page, original); await expect(confirmation(page)).toBeChecked();
  await server(page, current); await submit(page).click(); await expect(review(page).getByRole("alert")).toContainText("다른 곳에서 정보가 변경");
  await replace(page, original); await expect(submit(page)).toBeDisabled();
  await review(page).getByRole("button", { name: "삭제 전 현재 내용 비교", exact: true }).click(); await expect(review(page).getByText("비교한 내용: 합성 수정 내용", { exact: true })).toBeVisible();
  await review(page).getByRole("button", { name: "현재 내용 확인 후 삭제 다시 검토", exact: true }).click(); await expect(confirmation(page)).not.toBeChecked();
  await replace(page, original); await expect(submit(page)).toBeDisabled(); await confirmation(page).check(); await submit(page).click();
  await expect.poll(async () => (await snapshot(page)).requests.map((row) => row.version)).toEqual([1, 2]); await expect.poll(async () => (await snapshot(page)).deleted).toBe(1);
});

test("snapshot replacement cancels an outstanding wait and ignores its late completion", async ({ page }) => {
  await page.evaluate(() => (window as any).__homecareDeleteRegression.hold()); await open(page); await confirmation(page).check(); await submit(page).click(); await expect.poll(async () => (await snapshot(page)).requests.length).toBe(1);
  await server(page, current); await replace(page, current); await expect.poll(async () => (await snapshot(page)).aborted).toEqual([true]);
  await page.evaluate(() => (window as any).__homecareDeleteRegression.release()); expect((await snapshot(page)).deleted).toBe(0);
  await open(page); await confirmation(page).check(); await submit(page).click(); await expect.poll(async () => (await snapshot(page)).deleted).toBe(1); expect((await snapshot(page)).requests.map((row) => row.version)).toEqual([1, 2]);
});
