import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockDocuments } from "./support/documents";
import { mockHomecare } from "./support/homecare";
import { mockInsurance } from "./support/insurance";
import { uid } from "./support/finance";
import { mockVaultOverview } from "./support/vault-overview";
test.use({ trace: "off", screenshot: "off", video: "off" });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date("2025-02-20T03:00:00Z"));
});

/** Holds matching GET requests, once armed, until released. Register after the API mocks. */
async function holdReads(page: Page, pattern: string | RegExp) {
  let armed = false;
  let release = () => {};
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route(pattern, async (route) => {
    if (armed && route.request().method() === "GET") await gate;
    await route.fallback();
  });
  return {
    arm: () => {
      armed = true;
    },
    release,
  };
}

test("a finished vault action keeps its message and the card section while the card reloads", async ({
  page,
}) => {
  const state = await mockVaultOverview(page, true);
  await page.goto(`/cards/${uid(50)}`);
  await page.getByText("암호 보관함 관리", { exact: true }).click();
  const vault = page.getByRole("region", { name: "카드 보관함", exact: true });
  await expect(vault).toBeVisible();
  const handle = await vault.elementHandle();
  const reads = () => state.calls.filter((call) => call.method === "getCard").length;
  const before = reads();
  state.cardDelay = 800;
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  const message = page.getByText("보관함 작업을 마쳤어요. 현재 상태를 다시 확인해요.", {
    exact: true,
  });
  await expect.poll(reads).toBe(before + 1);
  // The card is still being read again: the section stays, busy, and the message remains.
  await expect(message).toBeVisible();
  expect(await handle!.evaluate((node) => node.isConnected)).toBe(true);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(1);
  await expect(page.getByText("현재 카드 정보를 불러오고 있어요.", { exact: true })).toHaveCount(0);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  await expect(message).toBeVisible();
  expect(await handle!.evaluate((node) => node.isConnected)).toBe(true);
});

test("a finished vault action keeps its message when the card reload fails", async ({ page }) => {
  const state = await mockVaultOverview(page, true);
  await page.goto(`/cards/${uid(50)}`);
  await page.getByText("암호 보관함 관리", { exact: true }).click();
  await expect(page.getByRole("region", { name: "카드 보관함", exact: true })).toBeVisible();
  state.failRead = "getCard";
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  const retry = page.getByRole("button", { name: "카드 다시 확인", exact: true });
  await expect(retry).toBeVisible();
  const message = page.getByText("보관함 작업을 마쳤어요. 현재 상태를 다시 확인해요.", {
    exact: true,
  });
  await expect(message).toBeVisible();
  state.failRead = "";
  await retry.click();
  await expect(retry).toHaveCount(0);
  await expect(message).toBeVisible();
});

test("refreshing today's consumables keeps the list on screen and marks it busy", async ({
  page,
}) => {
  await mockHomecare(page);
  const hold = await holdReads(page, "**/api/v1/homecare/**");
  await page.goto("/consumables");
  const today = page.locator(".today-card");
  const rows = today.locator(".care-row");
  await expect(rows.first()).toBeVisible();
  const count = await rows.count();
  const refresh = today.getByRole("button", { name: "오늘 소모품 상태 새로 확인", exact: true });
  const handle = await refresh.elementHandle();
  hold.arm();
  await refresh.click();
  const busy = today.locator("[aria-busy]");
  await expect(busy).toHaveAttribute("aria-busy", "true");
  await expect(rows).toHaveCount(count);
  expect(await handle!.evaluate((node) => node.isConnected)).toBe(true);
  await expect(today.getByText("현재 기록을 확인하고 있어요.", { exact: true })).toHaveCount(0);
  hold.release();
  await expect(busy).toHaveAttribute("aria-busy", "false");
  await expect(rows).toHaveCount(count);
});

test("a finished document action keeps the detail and its notice while the document reloads", async ({
  page,
}) => {
  await mockDocuments(page);
  const hold = await holdReads(page, /\/api\/v1\/documents\/[^/]+(\/links)?(\?.*)?$/);
  await page.goto(`/appliances/${uid(100)}`);
  await page
    .getByRole("region", { name: "가전 첨부 문서", exact: true })
    .getByRole("button", { name: "첨부 문서 열기" })
    .click();
  await page.getByRole("button", { name: "합성 영수증.png", exact: true }).click();
  const detail = page.getByRole("region", { name: "문서 상세", exact: true });
  await expect(detail.getByText("보관 완료", { exact: true })).toBeVisible();
  await detail.getByLabel("문서 연결 종료·삭제 사유").fill("합성 연결 종료");
  const end = detail.getByRole("button", { name: "이 문서 연결 종료" });
  await expect(end).toBeEnabled();
  hold.arm();
  await end.click();
  await expect(detail).toHaveAttribute("aria-busy", "true");
  await expect(detail.getByText("문서 연결 종료 완료", { exact: true })).toBeVisible();
  await expect(detail.getByText("보관 완료", { exact: true })).toBeVisible();
  await expect(detail.getByText("문서를 확인하고 있어요.", { exact: true })).toHaveCount(0);
  hold.release();
  await expect(detail).toHaveAttribute("aria-busy", "false");
  await expect(detail.getByText("문서 연결 종료 완료", { exact: true })).toBeVisible();
});

test("saving a medical node keeps the tree on screen while it is read again", async ({ page }) => {
  await mockInsurance(page);
  const hold = await holdReads(page, /\/api\/v1\/insurance\/cases\/[^/]+\/nodes(\?.*)?$/);
  await page.goto(`/insurance/cases/${uid(90)}`);
  const tree = page.getByRole("region", { name: "사건 진료 트리", exact: true });
  await expect(tree.getByRole("link", { name: "합성 첫 외래", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "사건 아래 진료 추가", exact: true }).click();
  await page.getByLabel("진료 이름", { exact: true }).fill("합성 새 외래");
  hold.arm();
  await page.getByRole("button", { name: "진료 기록 저장", exact: true }).click();
  await expect(tree).toHaveAttribute("aria-busy", "true");
  await expect(tree.getByRole("link", { name: "합성 첫 외래", exact: true })).toBeVisible();
  await expect(tree.getByText("전체 진료 연결을 불러오고 있어요.", { exact: true })).toHaveCount(0);
  hold.release();
  await expect(
    tree
      .getByRole("navigation", { name: "같은 단계 진료" })
      .getByRole("link", { name: "합성 새 외래", exact: true, current: "page" }),
  ).toBeVisible();
  await expect(tree).toHaveAttribute("aria-busy", "false");
});
