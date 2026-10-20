import { openDisclosure } from "./support/task-ui";
import { expect, test } from "@playwright/test";
import { mockFinance, uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });

test("accounts filter by pension type and owner, and show masked metadata without duplicated balances", async ({
  page,
}) => {
  const state = await mockFinance(page);
  await page.goto("/accounts");
  await expect(page.getByRole("link", { name: "합성 개인 금융 자산", exact: true })).toHaveCount(1);
  await expect(page.getByText("••••ONLY", { exact: true })).toBeVisible();
  await openDisclosure(page, "계좌 찾기");
  await page.getByLabel("계좌 유형 필터", { exact: true }).selectOption("irp");
  await page.getByLabel("계좌 소유자 필터", { exact: true }).selectOption(uid(5));
  await expect.poll(() => state.accountQueries.at(-1)?.get("owner_member_id")).toBe(uid(5));
  expect(state.accountQueries.at(-1)?.get("account_type")).toBe("irp");
  await page.getByRole("button", { name: "계좌 필터 초기화", exact: true }).click();
  await page.getByLabel("계좌 상태 필터", { exact: true }).selectOption("closed");
  await expect(
    page.getByRole("heading", { name: "조건에 맞는 계좌가 없어요", exact: true }),
  ).toBeVisible();
  expect(state.accountQueries.at(-1)?.has("owner_member_id")).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("create pension account with one nested financial asset and no full number field", async ({
  page,
}) => {
  const state = await mockFinance(page);
  await page.goto("/accounts/new");
  await expect(page.getByLabel("계좌 유형", { exact: true }).locator("option")).toHaveCount(11);
  await page.getByLabel("금융기관", { exact: true }).fill("합성 연금 기관");
  await page.getByLabel("계좌 유형", { exact: true }).selectOption("pension_savings");
  await page.getByLabel("자산 이름", { exact: true }).fill("합성 새 연금저축");
  await page.getByLabel("소유 방식", { exact: true }).selectOption("individual");
  await page.getByLabel("소유자", { exact: true }).selectOption(uid(2));
  await page.getByLabel("금액 입력 기준", { exact: true }).selectOption("owned");
  await page.getByLabel("보유 시작일", { exact: true }).fill("2025-01-01");
  await expect(page.locator("input[type=password]")).toHaveCount(0);
  await page.getByRole("button", { name: "계좌 등록", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 새 연금저축", exact: true })).toBeVisible();
  expect(state.accountCreates).toHaveLength(1);
  expect(state.accountCreates[0]?.asset?.category).toBe("financial");
  expect(state.accountCreates[0]?.asset?.kind).toBe("asset");
  expect(Object.hasOwn(state.accountCreates[0]!, "account_number")).toBe(false);
  expect(state.assets.filter((item) => item.name === "합성 새 연금저축")).toHaveLength(1);
});

test("existing financial asset linking rejects duplicate linkage and preserves all metadata", async ({
  page,
}) => {
  const state = await mockFinance(page);
  // The picker hides linked assets, so the duplicate comes from a spouse linking it meanwhile.
  const linked = state.accounts.splice(0);
  await page.goto("/accounts/new");
  await page.getByLabel("금융기관", { exact: true }).fill("합성 연결 기관");
  await page.getByLabel("계좌 유형", { exact: true }).selectOption("brokerage");
  await page.getByLabel("금융 자산 연결", { exact: true }).selectOption("existing");
  await page.getByLabel("연결할 금융 자산", { exact: true }).selectOption(uid(11));
  state.accounts.push(...linked);
  await page.getByRole("button", { name: "계좌 등록", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("이미 다른 계좌와 연결된");
  await expect(page.getByLabel("금융기관", { exact: true })).toHaveValue("합성 연결 기관");
  expect(state.accountCreates[0]?.asset_id).toBe(uid(11));
  expect(Object.hasOwn(state.accountCreates[0]!, "asset")).toBe(false);
});

test("account version conflict preserves draft and adopts unrelated changes only after review", async ({
  page,
}) => {
  const state = await mockFinance(page);
  state.accountConflictOnce = true;
  await page.goto(`/accounts/${uid(30)}/edit`);
  await page.getByLabel("금융기관", { exact: true }).fill("합성 내 금융기관");
  await page.getByRole("button", { name: "계좌 수정 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("작성한 내용은 그대로");
  await expect(page.getByLabel("금융기관", { exact: true })).toHaveValue("합성 내 금융기관");
  await expect(page.getByRole("button", { name: "계좌 수정 저장", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "서버의 최신 계좌 정보 확인", exact: true }).click();
  await expect(page.getByRole("cell", { name: "합성 서버 금융기관", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "비교한 내 계좌 수정 유지", exact: true }).click();
  await expect(page.getByLabel("용도 (선택)", { exact: true })).toHaveValue(
    "합성 다른 편집자의 용도",
  );
  await page.getByRole("button", { name: "계좌 수정 저장", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 개인 금융 자산", exact: true }),
  ).toBeVisible();
  expect(state.accountPatches.map((item) => item.version)).toEqual(['"1"', '"2"']);
  expect(state.accountPatches[1]?.body).toEqual({ institution_name: "합성 내 금융기관" });
});

test("closing an account archives the linked asset and preserves the chosen date after conflict", async ({
  page,
}) => {
  const state = await mockFinance(page);
  state.archiveConflictOnce = true;
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "계좌 사용 종료하기", exact: true }).click();
  await page.getByLabel("계좌 종료일", { exact: true }).fill("2026-09-10");
  await page.getByRole("button", { name: "계좌 사용 종료 확인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("다른 곳에서 정보가 변경");
  await page.getByRole("button", { name: "종료 전 최신 계좌 정보 확인", exact: true }).click();
  await expect.poll(() => state.accountGets).toBeGreaterThan(1);
  await expect(page.getByLabel("계좌 종료일", { exact: true })).toHaveValue("2026-09-10");
  await page.getByRole("button", { name: "계좌 사용 종료 확인", exact: true }).click();
  await expect(page.getByRole("button", { name: "계좌 사용 종료하기", exact: true })).toHaveCount(
    0,
  );
  expect(state.assets.find((item) => item.id === uid(11))?.ended_on).toBe("2026-09-10");
  expect(state.accounts).toHaveLength(1);
});

test("web full number clears after 30 seconds, blur, pagehide and navigation", async ({ page }) => {
  await mockFinance(page);
  await page.clock.install();
  await page.goto(`/accounts/${uid(30)}`);
  await page.bringToFront();
  const reveal = page.getByRole("button", { name: "전체 계좌번호 30초 보기", exact: true });
  await reveal.click();
  await expect
    .poll(() => page.evaluate(() => Boolean(document.querySelector("output")?.textContent)))
    .toBe(true);
  await page.clock.fastForward(30_001);
  await expect
    .poll(() => page.evaluate(() => !document.querySelector("output")?.textContent))
    .toBe(true);
  for (const event of ["blur", "pagehide"]) {
    await reveal.click();
    await expect
      .poll(() => page.evaluate(() => Boolean(document.querySelector("output")?.textContent)))
      .toBe(true);
    await page.evaluate((name) => dispatchEvent(new Event(name)), event);
    expect(await page.evaluate(() => !document.querySelector("output")?.textContent)).toBe(true);
  }
  await reveal.click();
  await expect
    .poll(() => page.evaluate(() => Boolean(document.querySelector("output")?.textContent)))
    .toBe(true);
  await page.getByRole("link", { name: "계좌 정보 수정", exact: true }).click();
  await expect(page.getByRole("heading", { name: "계좌 정보 수정", exact: true })).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          !document.querySelector("output")?.textContent &&
          localStorage.length === 0 &&
          sessionStorage.length === 0,
      ),
    )
    .toBe(true);
});

test("web number editing uses a separate request, clears on save, and rejects stale writes safely", async ({
  page,
}) => {
  const state = await mockFinance(page);
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "계좌번호 등록·변경", exact: true }).click();
  await page.getByLabel("새 계좌번호", { exact: true }).fill("SYNTHETIC-ACCOUNT-ONLY");
  await page.getByRole("button", { name: "계좌번호 저장", exact: true }).click();
  await expect(page.getByLabel("새 계좌번호", { exact: true })).toHaveCount(0);
  expect(state.accountPatches[0]?.keys).toEqual(["account_number"]);
  state.accountConflictOnce = true;
  await page.getByRole("button", { name: "계좌번호 등록·변경", exact: true }).click();
  await page.getByLabel("새 계좌번호", { exact: true }).fill("SYNTHETIC-ACCOUNT-ONLY");
  await page.getByRole("button", { name: "계좌번호 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("다른 곳에서 정보가 변경");
  expect(
    await page
      .getByLabel("새 계좌번호", { exact: true })
      .evaluate((element) => (element as HTMLInputElement).value.length === 0),
  ).toBe(true);
  await page.getByRole("button", { name: "최신 계좌 정보 다시 확인", exact: true }).click();
  await expect.poll(() => state.accountGets).toBeGreaterThan(2);
  await page.getByRole("button", { name: "저장된 계좌번호 삭제", exact: true }).click();
  await expect(page.getByText("계좌번호 미등록", { exact: true })).toBeVisible();
});

test("late reveal cannot restore plaintext after blur and reauthentication failure exposes no number", async ({
  page,
}) => {
  const state = await mockFinance(page);
  state.revealDelay = 250;
  await page.goto(`/accounts/${uid(30)}`);
  await page.bringToFront();
  await page.getByRole("button", { name: "전체 계좌번호 30초 보기", exact: true }).click();
  await expect.poll(() => state.revealCalls).toBe(1);
  await page.evaluate(() => dispatchEvent(new Event("blur")));
  await page.waitForTimeout(350);
  expect(await page.evaluate(() => !document.querySelector("output")?.textContent)).toBe(true);
  state.revealDelay = 0;
  state.revealDenied = true;
  await page.getByRole("button", { name: "전체 계좌번호 30초 보기", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "패스키로 이 계좌번호만 확인", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => !document.querySelector("output")?.textContent)).toBe(true);
});

test("foreign account never offers edit or sensitive controls", async ({ page }) => {
  await mockFinance(page);
  await page.goto(`/accounts/${uid(999)}`);
  await expect(page.getByRole("alert")).toContainText("찾을 수 없거나 볼 권한이 없어요");
  await expect(
    page.getByRole("button", { name: "전체 계좌번호 30초 보기", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("link", { name: "계좌 정보 수정", exact: true })).toHaveCount(0);
});

test("new account linking lists active financial assets and preserves inputs on later closure", async ({
  page,
}) => {
  const state = await mockFinance(page);
  state.assets.push({
    ...state.assets[1]!,
    id: uid(71),
    name: "합성 사용 종료 금융 자산",
    status: "archived",
    ended_on: "2026-01-01",
  });
  state.assets.push({ ...state.assets[1]!, id: uid(72), name: "합성 새 연결 후보" });
  await page.goto("/accounts/new");
  await page.getByLabel("금융기관", { exact: true }).fill("합성 보존 기관");
  await page.getByLabel("계좌 유형", { exact: true }).selectOption("brokerage");
  await page.getByLabel("금융 자산 연결", { exact: true }).selectOption("existing");
  await expect(page.getByLabel("연결할 금융 자산", { exact: true }).locator("option")).toHaveCount(
    2,
  );
  await expect(page.getByRole("option", { name: "합성 사용 종료 금융 자산" })).toHaveCount(0);
  // sampleAccount already links uid(11).
  await expect(page.getByRole("option", { name: "합성 개인 금융 자산" })).toHaveCount(0);
  expect(state.queries.at(-1)?.get("status")).toBe("active");
  expect(state.accountQueries.at(-1)?.get("status")).toBe("all");
  expect(state.accountQueries.at(-1)?.get("limit")).toBe("200");
  await page.getByLabel("연결할 금융 자산", { exact: true }).selectOption(uid(72));
  await page.route("**/api/v1/accounts", async (route) => {
    if (route.request().method() === "POST")
      return route.fulfill({
        status: 422,
        json: { error: { code: "ASSET_UNAVAILABLE", message: "synthetic", request_id: uid(99) } },
      });
    return route.fallback();
  });
  state.assets.find((item) => item.id === uid(72))!.status = "archived";
  state.assets.find((item) => item.id === uid(72))!.ended_on = "2026-01-01";
  await page.getByRole("button", { name: "계좌 등록", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("사용 종료된 자산");
  await expect(page.getByLabel("금융기관", { exact: true })).toHaveValue("합성 보존 기관");
  await page.getByRole("button", { name: "금융 자산 다시 불러오기", exact: true }).click();
  await expect(page.getByRole("option", { name: "합성 새 연결 후보" })).toHaveCount(0);
});

test("account misregistration delete needs confirmation and treats a retried 404 as deleted", async ({
  page,
}) => {
  const state = await mockFinance(page);
  state.deleteFailureAfter = true;
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "오등록 삭제 검토", exact: true }).click();
  const remove = page.getByRole("button", { name: "오등록 계좌 삭제", exact: true });
  await expect(remove).toBeDisabled();
  await page
    .getByLabel("잘못 등록한 계좌이며 연결된 금융 자산과 함께 삭제할 것을 확인했어요.", {
      exact: true,
    })
    .check();
  await remove.click();
  await expect(page.getByRole("alert")).toBeVisible();
  await remove.click();
  await expect(page).toHaveURL(/\/accounts$/);
  await expect(
    page.getByText("계좌와 연결된 금융 자산이 삭제된 것을 확인했어요.", { exact: true }),
  ).toBeVisible();
  expect(state.deletes).toEqual([
    { path: `/api/v1/accounts/${uid(30)}`, version: '"1"' },
    { path: `/api/v1/accounts/${uid(30)}`, version: '"1"' },
  ]);
  expect(state.accounts).toHaveLength(0);
  expect(state.assets.some((asset) => asset.id === uid(11))).toBe(false);
});

test("a referenced account explains why it stays and offers closure instead", async ({ page }) => {
  const state = await mockFinance(page);
  state.deleteInUse = true;
  await page.goto(`/accounts/${uid(30)}`);
  await page.getByRole("button", { name: "오등록 삭제 검토", exact: true }).click();
  await page
    .getByLabel("잘못 등록한 계좌이며 연결된 금융 자산과 함께 삭제할 것을 확인했어요.", {
      exact: true,
    })
    .check();
  await page.getByRole("button", { name: "오등록 계좌 삭제", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("계좌 사용 종료로 과거 기록을 보존해 주세요");
  await expect(page.getByRole("button", { name: "오등록 계좌 삭제", exact: true })).toBeDisabled();
  expect(state.accounts).toHaveLength(1);
});
