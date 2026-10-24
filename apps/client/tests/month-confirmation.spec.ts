import { expect, test } from "@playwright/test";
import { mockMonths, total } from "./support/months";
import { uid } from "./support/finance";
test.use({ trace: "off", screenshot: "off", video: "off" });

test("twenty carried assets require explicit selection and date, preserve ownership and do not confirm the month", async ({
  page,
}) => {
  const state = await mockMonths(page);
  const template = state.record!.values[0]!;
  state.record!.values = Array.from({ length: 20 }, (_, i) => ({
    ...template,
    id: uid(500 + i),
    asset_id: uid(600 + i),
    name: `합성 자산 ${i + 1}`,
    input_amount_krw: i === 0 ? "0" : "1001",
    owned_amount_krw: i === 0 ? "0" : "501",
  }));
  state.record!.totals = total(state.record!.values);
  state.pageSize = 7;
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "선택한 항목 변동 없음 확인", exact: true }).click();
  const panel = page.getByRole("region", { name: "선택한 항목 변동 없음", exact: true });
  await expect(panel.getByRole("checkbox", { checked: true })).toHaveCount(0);
  await expect(panel.getByLabel("공통 실제 확인 기준일", { exact: true })).toHaveValue("");
  await expect(
    panel.getByRole("button", { name: "선택한 금액 확인 저장", exact: true }),
  ).toBeDisabled();
  await panel.getByRole("checkbox", { name: "합성 자산 1 선택", exact: true }).check();
  await panel.getByRole("checkbox", { name: "합성 자산 20 선택", exact: true }).check();
  await panel.getByLabel("공통 실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await panel
    .getByLabel("선택한 금액이 기준일에도 같음을 직접 확인했어요.", { exact: true })
    .check();
  await panel.getByRole("button", { name: "선택한 금액 확인 저장", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("2 / 2개 저장 완료");
  expect(state.writes).toHaveLength(2);
  for (const write of state.writes) {
    expect(write.body).toMatchObject({
      unchanged: true,
      as_of_date: "2025-02-28",
      revision_id: state.record!.revision_id,
    });
    expect(write.version).toBe('"1"');
    expect(write.body).not.toHaveProperty("input_amount_krw");
  }
  expect(state.record!.totals.verified_count).toBe(2);
  expect(state.record!.totals.carried_count).toBe(18);
  expect(state.record!.values[0]!.owned_amount_krw).toBe("0");
  expect(state.record!.values[19]!.owned_amount_krw).toBe("501");
  expect(state.record!.state).toBe("draft");
  await panel.getByRole("button", { name: "결과 확인하고 닫기" }).click();
  await page.getByLabel("확인 상태 필터", { exact: true }).selectOption("unverified");
  await expect(page.locator("[data-month-row]")).toHaveCount(18);
  await page.getByRole("button", { name: "미확인 항목 확인하기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 자산 2 금액 확인", exact: true }),
  ).toBeVisible();
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.getByRole("button", { name: "저장 후 다음 미확인 항목", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 자산 3 금액 확인", exact: true }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(3);
  await expect(page.getByLabel("실제 확인 기준일", { exact: true })).toHaveValue("");
  for (let i = 3; i <= 19; i++) {
    await expect(
      page.getByRole("heading", { name: `합성 자산 ${i} 금액 확인`, exact: true }),
    ).toBeVisible();
    await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
    await page.getByRole("button", { name: "저장 후 다음 미확인 항목", exact: true }).click();
  }
  await expect(
    page.getByText("금액을 저장했어요. 선택한 소유 조건에 다음 미확인 항목이 없어요.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(20);
  expect(new Set(state.writes.map((write) => write.body.value_id)).size).toBe(20);
  expect(state.record!.totals.verified_count).toBe(20);
  expect(state.record!.state).toBe("draft");
});

test("batch retry preserves succeeded rows and a conflict needs individual review", async ({
  page,
}) => {
  const state = await mockMonths(page);
  const row = state.record!.values[0]!;
  state.record!.values = [row, { ...row, id: uid(510), asset_id: uid(610), name: "합성 두 번째" }];
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "선택한 항목 변동 없음 확인", exact: true }).click();
  const panel = page.getByRole("region", { name: "선택한 항목 변동 없음", exact: true });
  await panel.getByLabel("합성 공동 주택 선택", { exact: true }).check();
  await panel.getByLabel("합성 두 번째 선택", { exact: true }).check();
  await panel.getByLabel("공통 실제 확인 기준일", { exact: true }).fill("2025-02-20");
  await panel
    .getByLabel("선택한 금액이 기준일에도 같음을 직접 확인했어요.", { exact: true })
    .check();
  state.writeFailure = "before";
  await panel.getByRole("button", { name: "선택한 금액 확인 저장", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("1 / 2개 저장 완료");
  row.version++;
  await panel.getByRole("button", { name: "미완료 항목만 다시 시도", exact: true }).click();
  await expect(panel.getByText("현재 기록을 개별 확인해 주세요.", { exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(3);
  expect(state.writes[2]).toEqual(state.writes[0]);
  await expect(
    panel.getByRole("button", { name: "미완료 항목만 다시 시도", exact: true }),
  ).toHaveCount(0);
});

test("saved value is not reposted when the next read fails and owner filter limits next", async ({
  page,
}) => {
  const state = await mockMonths(page);
  const source = state.record!.values[0]!;
  state.record!.values = [
    source,
    {
      ...source,
      id: uid(501),
      asset_id: uid(601),
      name: "합성 개인",
      ownership_kind: "individual",
      owner_member_id: uid(2),
    },
    { ...source, id: uid(502), asset_id: uid(602), name: "합성 공동 다음" },
  ];
  await page.goto("/assets/months/2025-02");
  await page.getByLabel("소유 관계 필터", { exact: true }).selectOption("joint");
  await expect(page.locator("[data-month-row]")).toHaveCount(2);
  await page.getByRole("button", { name: "미확인 항목 확인하기", exact: true }).click();
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await page.route(
    "**/api/v1/asset-months/2025-02?*",
    (route) => (route.request().method() === "GET" ? route.abort("failed") : route.fallback()),
    { times: 1 },
  );
  await page.getByRole("button", { name: "저장 후 다음 미확인 항목", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "다음 항목만 다시 확인", exact: true }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(1);
  await page.getByRole("button", { name: "다음 항목만 다시 확인", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "합성 공동 다음 금액 확인", exact: true }),
  ).toBeVisible();
  expect(state.writes).toHaveLength(1);
});

for (const width of [320, 390, 1280])
  test(`batch month selection fits ${width}px and focuses the panel`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.emulateMedia({ colorScheme: "dark" });
    await mockMonths(page);
    await page.goto("/assets/months/2025-02");
    await page.getByRole("button", { name: "선택한 항목 변동 없음 확인", exact: true }).click();
    const panel = page.getByRole("region", { name: "선택한 항목 변동 없음", exact: true });
    await expect(panel).toBeFocused();
    await expect(panel.getByRole("checkbox")).toHaveCount(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });

test("a lost batch response retries the original version and does not duplicate the update", async ({
  page,
}) => {
  const state = await mockMonths(page);
  await page.goto("/assets/months/2025-02");
  await page.getByRole("button", { name: "선택한 항목 변동 없음 확인", exact: true }).click();
  const panel = page.getByRole("region", { name: "선택한 항목 변동 없음", exact: true });
  await panel.getByLabel("합성 공동 주택 선택", { exact: true }).check();
  await panel.getByLabel("공통 실제 확인 기준일", { exact: true }).fill("2025-02-28");
  await panel
    .getByLabel("선택한 금액이 기준일에도 같음을 직접 확인했어요.", { exact: true })
    .check();
  state.writeFailure = "after";
  await panel.getByRole("button", { name: "선택한 금액 확인 저장", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("0 / 1개 저장 완료");
  expect(state.record!.values[0]!.version).toBe(2);
  await panel.getByRole("button", { name: "미완료 항목만 다시 시도", exact: true }).click();
  await expect(panel.getByText("현재 기록을 개별 확인해 주세요.", { exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(2);
  expect(state.writes[1]).toEqual(state.writes[0]);
  expect(state.record!.values[0]!.version).toBe(2);
  await panel
    .getByRole("button", { name: "합성 공동 주택 입력 보존하고 개별 비교", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "작성한 값과 현재 기록 비교", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("실제 확인 기준일", { exact: true })).toHaveValue("2025-02-28");
  await page.getByRole("button", { name: "최신 월 기록과 비교", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "월 금액 충돌 비교 표", exact: true }),
  ).toContainText("확인 완료");
  expect(state.writes).toHaveLength(2);
  await expect(page.getByLabel("실제 확인 기준일", { exact: true })).toHaveValue("2025-02-28");
});
