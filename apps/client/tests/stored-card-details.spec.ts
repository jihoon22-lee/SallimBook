import { expect, test } from "@playwright/test";
import { mockCashflow } from "./support/cashflow";
import { uid } from "./support/finance";

test.use({ trace: "off", screenshot: "off", video: "off" });

async function setup(page: import("@playwright/test").Page, stored = false) {
  const state = await mockCashflow(page);
  Object.assign(state.cards[0]!, { has_stored_details: stored });
  const writes: Record<string, unknown>[] = [];
  let fail = false;
  await page.route("**/api/v1/cards/*/stored-details**", async (route) => {
    const request = route.request();
    if (request.url().endsWith("/reveal")) {
      await route.fulfill({
        json: {
          card_id: uid(50),
          household_id: uid(3),
          pan: "4242424242424242",
          expiry_year: 2032,
          expiry_month: 12,
          cvc: "007",
          checksum_valid: true,
          version: 1,
        },
      });
    } else if (request.method() === "PUT") {
      writes.push(request.postDataJSON());
      if (fail)
        return route.fulfill({
          status: 409,
          json: { error: { code: "VERSION_CONFLICT", message: "unsafe", request_id: "synthetic" } },
        });
      Object.assign(state.cards[0]!, { has_stored_details: true, version: 2 });
      await route.fulfill({ json: state.cards[0] });
    } else await route.fulfill({ status: 204 });
  });
  await page.goto(`/cards/${uid(50)}`);
  return {
    writes,
    state,
    conflict: () => {
      fail = true;
    },
  };
}

test("card details save without vault password and preserve unverified digits", async ({
  page,
}) => {
  const { writes } = await setup(page);
  await page.getByRole("button", { name: "번호·유효기간·CVC 입력", exact: true }).click();
  await expect(page.getByLabel("현재 보관함 암호")).toHaveCount(0);
  await page.getByLabel("카드번호", { exact: true }).fill("4242 4242-4242 4241");
  await page.getByLabel("유효기간 연도", { exact: true }).fill("2032");
  await page.getByLabel("유효기간 월", { exact: true }).fill("12");
  await page.getByLabel("CVC (선택)", { exact: true }).fill("007");
  await page.getByRole("button", { name: "카드 상세정보 저장", exact: true }).click();
  await expect(page.getByText("카드 상세정보를 저장했어요.", { exact: true })).toBeVisible();
  expect(writes).toEqual([
    { pan: "4242424242424241", expiry_year: 2032, expiry_month: 12, cvc: "007" },
  ]);
  await expect(page.getByRole("region", { name: "카드 상세정보 보호 화면" })).toHaveCount(0);
});

test("format errors preserve other entered fields without a network write", async ({ page }) => {
  const { writes } = await setup(page);
  await page.getByRole("button", { name: "번호·유효기간·CVC 입력", exact: true }).click();
  await page.getByLabel("카드번호", { exact: true }).fill("4242424242424242");
  await page.getByLabel("유효기간 연도", { exact: true }).fill("2032");
  await page.getByLabel("유효기간 월", { exact: true }).fill("13");
  await page.getByLabel("CVC (선택)", { exact: true }).fill("007");
  await page.getByRole("button", { name: "카드 상세정보 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("유효기간 월");
  await expect(page.getByLabel("카드번호", { exact: true })).toHaveValue("4242424242424242");
  await expect(page.getByLabel("CVC (선택)", { exact: true })).toHaveValue("007");
  expect(writes).toHaveLength(0);
});

test("stored details reveal temporarily without a password and blur wipes the DOM", async ({
  page,
}) => {
  await setup(page, true);
  await page.getByRole("button", { name: "전체 카드정보 보기", exact: true }).click();
  await expect(page.getByLabel("일시적으로 표시하는 카드 상세정보")).toContainText(
    "4242424242424242",
  );
  await expect(page.getByLabel("일시적으로 표시하는 카드 상세정보")).toContainText("007");
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(page.getByLabel("일시적으로 표시하는 카드 상세정보")).toHaveText("");
  await expect(page.getByText("화면을 잠갔어요.", { exact: true })).toBeVisible();
});

test("a late reveal cannot display after the protected screen closes", async ({ page }) => {
  await setup(page, true);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/stored-details/reveal", async (route) => {
    await gate;
    await route
      .fulfill({
        json: {
          card_id: uid(50),
          household_id: uid(3),
          pan: "4242424242424242",
          expiry_year: 2032,
          expiry_month: 12,
          cvc: "007",
          checksum_valid: true,
          version: 1,
        },
      })
      .catch(() => {});
  });
  await page.getByRole("button", { name: "전체 카드정보 보기", exact: true }).click();
  await page.getByRole("button", { name: "카드 상세정보 닫기", exact: true }).click();
  release();
  await expect(page.getByLabel("일시적으로 표시하는 카드 상세정보")).toHaveCount(0);
  await expect(page.getByText("4242424242424242")).toHaveCount(0);
});

test("editing stored details waits for prefill and failed prefill stays read-only", async ({
  page,
}) => {
  await setup(page, true);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/stored-details/reveal", async (route) => {
    await gate;
    await route.fulfill({
      status: 503,
      json: { error: { code: "REQUEST_FAILED", message: "unsafe", request_id: "synthetic" } },
    });
  });
  await page.getByRole("button", { name: "번호·유효기간·CVC 입력", exact: true }).click();
  await expect(page.getByLabel("카드번호", { exact: true })).toBeDisabled();
  release();
  await expect(page.getByRole("alert")).toContainText("불러오지 못했어요");
  await expect(page.getByLabel("카드번호", { exact: true })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "카드 상세정보 저장", exact: true }),
  ).toBeDisabled();
});
