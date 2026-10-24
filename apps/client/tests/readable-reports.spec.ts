import { expect, test } from "@playwright/test";
import { mockExports } from "./support/exports";

test.use({ trace: "off", screenshot: "off", video: "off" });
const ack = "민감한 업무 기록이 포함될 수 있고 저장한 파일을 앱에서 회수할 수 없음을 확인했어요";
for (const native of [false, true]) {
  test(`readable only ${native ? "Android" : "web"} retains domain period and independent annual scope`, async ({
    page,
  }) => {
    const state = await mockExports(page, native);
    await page.goto("/exports");
    await page.getByLabel("JSON — 원래 값과 구조를 보존하는 교환용", { exact: true }).uncheck();
    await page.getByLabel("CSV — 표로 살펴보기", { exact: true }).uncheck();
    await page.getByLabel("읽기용 HTML 포함", { exact: true }).check();
    const domains = page.getByRole("group", { name: "읽기용 영역", exact: true });
    for (const name of ["자산", "계좌", "카드", "수입", "가전·소모품"])
      await domains.getByLabel(name, { exact: true }).uncheck();
    await page.getByLabel("연간 가족별 참고 요약 포함", { exact: true }).check();
    await page.getByLabel("요약 연도", { exact: true }).fill("2024");
    await page.getByRole("button", { name: "상세 자료도 같은 연도로 맞추기", exact: true }).click();
    await expect(page.getByLabel("읽기용 시작일 (선택)", { exact: true })).toHaveValue(
      "2024-01-01",
    );
    await expect(page.getByLabel("읽기용 종료일 (선택)", { exact: true })).toHaveValue(
      "2024-12-31",
    );
    await page.getByLabel("읽기용 시작일 (선택)", { exact: true }).fill("2024-02-29");
    await page.getByLabel(ack).check();
    if (!native) {
      const waiting = page.waitForEvent("download");
      await page.getByRole("button", { name: "ZIP 내보내기·저장", exact: true }).click();
      await waiting;
    } else {
      await page.getByRole("button", { name: "Android에서 ZIP 내보내기", exact: true }).click();
      await expect(page.getByText(/Android 보호 화면에서 내보내기를 마쳤어요/)).toBeVisible();
    }
    const expected = {
      formats: [],
      document_ids: [],
      readable: {
        domains: ["fixed", "insurance"],
        from_date: "2024-02-29",
        through_date: "2024-12-31",
        annual_year: 2024,
      },
    };
    if (native) {
      expect(
        state.calls.filter((call) => call.method === "exportArchiveUI").map((call) => call.args),
      ).toEqual([{ input: expected }]);
      expect(state.http).toEqual([]);
    } else expect(state.writes[0]!.body).toEqual(expected);
    await expect(page.getByLabel(ack)).not.toBeChecked();
  });
}

test("invalid periods and years block export and scope edits revoke consent", async ({ page }) => {
  const state = await mockExports(page);
  await page.goto("/exports");
  await page.getByLabel("읽기용 HTML 포함", { exact: true }).check();
  await page.getByLabel(ack).check();
  await page.getByLabel("읽기용 시작일 (선택)", { exact: true }).fill("2026-03-01");
  await expect(page.getByLabel(ack)).not.toBeChecked();
  await page.getByLabel("읽기용 종료일 (선택)", { exact: true }).fill("2026-02-28");
  await expect(page.getByRole("alert")).toContainText("종료일");
  const download = page.getByRole("button", { name: "ZIP 내보내기·저장", exact: true });
  await expect(download).toBeDisabled();
  await page.getByLabel("읽기용 종료일 (선택)", { exact: true }).fill("");
  await page.getByLabel("연간 가족별 참고 요약 포함", { exact: true }).check();
  await page.getByLabel("요약 연도", { exact: true }).fill("10000");
  await expect(page.getByRole("alert")).toContainText("요약 연도");
  await expect(download).toBeDisabled();
  await page
    .getByRole("group", { name: "읽기용 영역", exact: true })
    .getByLabel("보험·의료", { exact: true })
    .uncheck();
  await expect(page.getByLabel("요약 연도", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(state.writes).toEqual([]);
});

test("domain selection requires at least one and fits enlarged narrow dark screen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 750 });
  await mockExports(page);
  await page.goto("/exports");
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "dark";
    document.documentElement.style.fontSize = "20px";
  });
  await page.getByLabel("읽기용 HTML 포함", { exact: true }).check();
  const domains = page.getByRole("group", { name: "읽기용 영역", exact: true });
  for (const box of await domains.getByRole("checkbox").all()) await box.uncheck();
  await expect(page.getByRole("alert")).toContainText("영역을 하나 이상");
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1);
  expect(fits).toBe(true);
});

test("generated scope bridge rejects forged fields and invalid dates without native calls", async ({
  page,
}) => {
  const state = await mockExports(page, true);
  await page.goto("/exports");
  const result = await page.evaluate(async () => {
    const path = "/src/platform/nativeExports.ts";
    const { nativeExports } = await import(path);
    const cases = [
      { domains: [] },
      { domains: ["vault"] },
      { domains: ["income", "income"] },
      { domains: ["income"], annual_year: 2024 },
      { domains: ["insurance"], annual_year: "2024" },
      { domains: ["insurance"], annual_year: true },
      { domains: ["insurance"], annual_year: 1.5 },
      { domains: ["insurance"], from_date: "2025-02-29" },
      { domains: ["insurance"], from_date: "0000-01-01" },
      { domains: ["insurance"], from_date: "2025-03-01", through_date: "2025-02-28" },
      { domains: ["insurance"], household_id: "forged" },
      { domains: ["insurance"], url: "https://synthetic.invalid" },
    ];
    const failures = [];
    for (const readable of cases) {
      try {
        await nativeExports.export({ input: { formats: [], readable } });
        failures.push("accepted");
      } catch (error) {
        failures.push((error as { code: string }).code);
      }
    }
    return failures;
  });
  expect(result).toEqual(Array(12).fill("VALIDATION_ERROR"));
  expect(state.calls.filter((call) => call.method === "exportArchiveUI")).toEqual([]);
  expect(state.http).toEqual([]);
});
