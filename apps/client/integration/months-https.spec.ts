import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as { login: string; password: string };
test.setTimeout(150_000); test.use({ actionTimeout: 10_000, navigationTimeout: 15_000 });
// Actual PostgreSQL, generated API client, HTTPS and synthetic records. No route mocks.
async function asset(page: Page, name: string, liability: boolean) {
  await page.goto("/assets/new"); await page.getByLabel("자산 이름", { exact: true }).fill(name); await page.getByLabel("자산·부채 구분", { exact: true }).selectOption(liability ? "liability" : "asset");
  await page.getByLabel("분류", { exact: true }).selectOption(liability ? "loan" : "real_estate"); await page.getByLabel("소유 방식", { exact: true }).selectOption("joint"); await page.getByLabel("가계 지분 (%)", { exact: true }).fill(liability ? "100" : "50"); await page.getByLabel("금액 입력 기준", { exact: true }).selectOption(liability ? "owned" : "whole"); await page.getByLabel("보유 시작일", { exact: true }).fill("2025-01-01");
  await page.getByRole("button", { name: "자산 등록", exact: true }).click(); await expect(page.getByRole("heading", { name, exact: true })).toBeVisible(); return new URL(page.url()).pathname.split("/").at(-1)!;
}
async function observe(page: Page, name: string, amount: string | "unchanged", date: string) {
  await page.getByRole("button", { name: `${name} 금액 확인`, exact: true }).click();
  if (amount === "unchanged") await page.getByLabel("입력 방식", { exact: true }).selectOption("unchanged"); else await page.getByLabel("확인 금액 (원)", { exact: true }).fill(amount);
  await page.getByLabel("실제 확인 기준일", { exact: true }).fill(date); await page.getByRole("button", { name: "금액 확인 저장", exact: true }).click(); await expect(page.getByRole("button", { name: `${name} 금액 확인`, exact: true })).toBeEnabled();
}
async function changeLiveShare(page: Page, assetId: string, share: string) {
  return page.evaluate(async ({ id, share }) => {
    const csrf = await fetch("/api/v1/auth/web/csrf").then((response) => response.json()); const asset = await fetch(`/api/v1/assets/${id}`).then((response) => response.json());
    return (await fetch(`/api/v1/assets/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf.csrf_token, "If-Match": `"${asset.version}"` }, body: JSON.stringify({ household_share: share }) })).status;
  }, { id: assetId, share });
}
async function confirmReviewed(page: Page, ack: boolean) {
  await page.getByRole("button", { name: "월 확정 검토", exact: true }).click();
  if (ack) { await page.getByLabel("월말과 다른 기준일을 확인했어요.", { exact: true }).check(); await page.getByLabel("전월과 달라진 포함 항목·가계 지분을 확인했어요.", { exact: true }).check(); }
  await page.getByRole("button", { name: "확인하고 월 확정", exact: true }).click(); await expect(page.getByRole("button", { name: "정정 사유 남기고 다시 열기", exact: true })).toBeVisible();
}

test("real monthly workflow preserves null zero copied values scope and immutable corrections across desktop and Android width", async ({ page }) => {
  await page.goto("/login"); await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login); await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password); await page.getByText("기기 이름 변경", { exact: true }).click(); await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 월 기록 HTTPS"); await page.getByRole("button", { name: "로그인", exact: true }).click(); await expect(page.getByRole("heading", { name: "현재 계정", exact: true })).toBeVisible();
  const house = await asset(page, "합성 월 확인 주택", false); await asset(page, "합성 월 확인 대출", true); console.log("SAFE_PHASE=MONTH_ASSETS_CREATED");
  await page.goto("/assets/months/2025-01"); await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click(); await expect(page.locator(".month-value-card")).toHaveCount(2); await expect(page.getByRole("button", { name: "월 확정 검토", exact: true })).toBeDisabled();
  await observe(page, "합성 월 확인 주택", "100000001", "2025-01-31"); await observe(page, "합성 월 확인 대출", "30000000", "2025-01-31");
  await expect(page.getByRole("region", { name: "이번 기록의 합계", exact: true })).toContainText("20,000,001원"); await confirmReviewed(page, false); console.log("SAFE_PHASE=MONTH_FIRST_CONFIRMED");

  await page.setViewportSize({ width: 412, height: 915 }); await page.goto("/assets/months/2025-02"); await page.getByRole("button", { name: "월 작성본 만들기", exact: true }).click();
  await expect(page.getByText("불러온 값 · 미확인", { exact: true })).toHaveCount(2); await expect(page.getByRole("button", { name: "월 확정 검토", exact: true })).toBeDisabled();
  await observe(page, "합성 월 확인 주택", "unchanged", "2025-02-20"); await observe(page, "합성 월 확인 대출", "0", "2025-02-28");
  expect(await changeLiveShare(page, house, "0.75")).toBe(200);
  await page.getByRole("button", { name: "월 확정 검토", exact: true }).click(); await page.getByLabel("월말과 다른 기준일을 확인했어요.", { exact: true }).check(); await page.getByRole("button", { name: "확인하고 월 확정", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("현재 자산 목록이나 지분이 바뀌었어요"); await page.getByRole("button", { name: "확정 검토 닫기", exact: true }).click(); await page.getByRole("button", { name: "현재 월 기록 다시 불러오기", exact: true }).click();
  await expect(page.getByRole("button", { name: "월 확정 검토", exact: true })).toBeDisabled(); await page.getByRole("button", { name: "현재 자산 범위 반영 검토", exact: true }).click(); await page.getByLabel("변경될 범위와 미확인으로 돌아갈 항목을 확인했어요.", { exact: true }).check(); await page.getByRole("button", { name: "확인한 현재 자산 범위 반영", exact: true }).click();
  await expect(page.getByText("불러온 값 · 미확인", { exact: true })).toHaveCount(1); await observe(page, "합성 월 확인 주택", "unchanged", "2025-02-20"); await confirmReviewed(page, true); console.log("SAFE_PHASE=MONTH_SCOPE_CONFIRMED");

  expect(await changeLiveShare(page, house, "1")).toBe(200); await page.getByRole("button", { name: "정정 사유 남기고 다시 열기", exact: true }).click(); await page.getByLabel("정정 사유", { exact: true }).fill("합성 확인 당시 평가액 정정"); await page.getByRole("button", { name: "사유를 남기고 정정 시작", exact: true }).click();
  await expect(page.getByRole("heading", { name: "과거 범위를 유지하는 정정본", exact: true })).toBeVisible(); await expect(page.getByText("정정본은 과거 범위를 유지한 채 확정할 수 있어요.", { exact: false })).toBeVisible();
  await observe(page, "합성 월 확인 주택", "100000003", "2025-02-20"); await confirmReviewed(page, true);
  await page.getByRole("link", { name: "1차 기록 · 확정", exact: true }).click(); await expect(page.getByRole("heading", { name: "1차 기록 조회", exact: true })).toBeVisible(); await expect(page.getByRole("button", { name: "합성 월 확인 주택 금액 확인", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "이번 기록의 합계", exact: true })).toContainText("75,000,001원");
  const invariant = await page.evaluate(async (houseId) => {
    const read = async (path: string) => { const response = await fetch(path); return { value: await response.json(), noStore: response.headers.get("cache-control")?.includes("no-store") ?? false }; };
    const [first, corrected, january] = await Promise.all([read("/api/v1/asset-months/2025-02/revisions/1"), read("/api/v1/asset-months/2025-02/revisions/2"), read("/api/v1/asset-months/2025-01")]);
    const old = first.value.values.find((row: { asset_id: string }) => row.asset_id === houseId); const next = corrected.value.values.find((row: { asset_id: string }) => row.asset_id === houseId);
    return first.noStore && corrected.noStore && january.noStore && first.value.state === "confirmed" && corrected.value.state === "confirmed" && corrected.value.previous_revision_id === first.value.revision_id && corrected.value.reopened_reason === "합성 확인 당시 평가액 정정" && old.id !== next.id && old.input_amount_krw === "100000001" && next.input_amount_krw === "100000003" && /^0\.750*$/.test(old.household_share) && old.household_share === next.household_share && first.value.totals.net_assets_krw === "75000001" && corrected.value.totals.net_assets_krw === "75000002" && january.value.totals.net_assets_krw === "20000001";
  }, house);
  expect(invariant).toBe(true); expect(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0 && document.documentElement.scrollWidth <= innerWidth)).toBe(true); console.log("SAFE_PHASE=MONTH_IMMUTABLE_HISTORY");
  if (process.env.SALLIMBOOK_HTTPS_COMPARISON === "1") {
    await page.goto("/assets/compare?to=2025-02&from=2025-01"); const summary = page.getByRole("region", { name: "월간 자산 변화", exact: true });
    await expect(summary).toContainText("75,000,002원"); await expect(summary).toContainText("+55,000,001원"); await expect(summary).toContainText("+30,000,000원"); await expect(summary).toContainText("지분 변경 1개"); await expect(summary).toContainText("서로 다른 기준일이 섞여 있어요");
    await expect(page.getByRole("region", { name: "월별 추이 금액 표" })).toContainText("월 기록 없음"); await expect(page.locator("circle.chart-point")).toHaveCount(2); await expect(page.locator("polyline.chart-line")).toHaveCount(1);
    const projection = await page.evaluate(async () => {
      const comparison = await fetch("/api/v1/asset-comparison?to=2025-02&from=2025-01"); const trends = await fetch("/api/v1/asset-trends?from=2024-12&to=2025-02"); const a = await comparison.json(); const b = await trends.json();
      return comparison.headers.get("cache-control")?.includes("no-store") && trends.headers.get("cache-control")?.includes("no-store") && a.current.revision.revision_no === 2 && a.total_delta_krw === "55000001" && a.common_scope_delta_krw === "30000000" && b.points[0].confirmed_amount_krw === null && b.points[2].confirmed_amount_krw === "75000002";
    }); expect(projection).toBe(true);
    await page.getByRole("link", { name: "합성 월 확인 주택", exact: true }).click(); await expect(page.getByRole("region", { name: "이 자산의 월 기록", exact: true })).toContainText("75,000,002원");
    await page.goto("/assets/compare?to=2025-01"); await expect(page.getByRole("region", { name: "월간 자산 변화", exact: true })).toContainText("첫 기록을 0원 대비 증가로 표시하지 않아요");
    await page.goto("/assets/compare?to=2025-03"); await expect(page.getByRole("region", { name: "월간 자산 변화", exact: true })).toContainText("자산이 0원으로 줄어든 것으로 계산하지 않아요");
    await page.goto("/assets/months/2025-02"); await page.getByRole("button", { name: "정정 사유 남기고 다시 열기", exact: true }).click(); await page.getByLabel("정정 사유", { exact: true }).fill("합성 비교 미확정 검증"); await page.getByRole("button", { name: "사유를 남기고 정정 시작", exact: true }).click(); await expect(page.getByRole("heading", { name: "과거 범위를 유지하는 정정본", exact: true })).toBeVisible();
    await page.goto("/assets/compare?to=2025-02"); await expect(page.getByRole("region", { name: "월간 자산 변화", exact: true })).toContainText("두 월을 확정하기 전에는 증감을 계산하지 않아요"); await expect(page.locator("circle.chart-point")).toHaveCount(1); await expect(page.getByRole("region", { name: "월별 추이 금액 표" })).toContainText("미확정 참고값");
    await page.getByRole("link", { name: "홈", exact: true }).click(); await expect(page.getByRole("region", { name: "자산의 변화", exact: true })).toContainText("두 월을 확정하기 전에는 증감을 계산하지 않아요");
    expect(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0 && document.documentElement.scrollWidth <= innerWidth)).toBe(true); console.log("SAFE_PHASE=COMPARISON_TREND_HOME_VERIFIED");
  }

});
