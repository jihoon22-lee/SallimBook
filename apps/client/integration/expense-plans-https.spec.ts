import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
const fixture = JSON.parse(readFileSync(process.env.SALLIMBOOK_HTTPS_FIXTURE!, "utf8")) as {
  login: string;
  password: string;
};
test.setTimeout(180000);
test.use({ actionTimeout: 10000, navigationTimeout: 15000 });
test("real monthly planning saves without dates, edits same day, links cards and ends without cash effects", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("로그인 이름", { exact: true }).fill(fixture.login);
  await page.getByLabel("비밀번호", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.getByRole("heading", { name: "오늘의 살림", exact: true })).toBeVisible();
  await page.goto("/cards/new");
  await page
    .getByRole("combobox", { name: "카드 소유자", exact: true })
    .selectOption({ label: "합성 HTTPS 구성원" });
  await page.getByLabel("카드사", { exact: true }).fill("합성 계획 카드사");
  await page.getByLabel("카드명", { exact: true }).fill("합성 계획 카드");
  await page.getByRole("button", { name: "카드 등록 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 계획 카드", exact: true })).toBeVisible();
  const cardId = new URL(page.url()).pathname.split("/").at(-1)!;
  await page.goto("/fixed-payments");
  await page.getByRole("button", { name: "지출 계획 추가", exact: true }).click();
  await page.getByLabel("이름", { exact: true }).fill("합성 HTTPS 월 계획");
  await page.getByLabel("계획 금액 (미정이면 비워두기)", { exact: true }).fill("12345");
  await page.getByText("결제수단·주기·관련 구성원·메모", { exact: true }).click();
  await page.getByRole("combobox", { name: "납부수단 구분", exact: true }).selectOption("card");
  await page.getByRole("combobox", { name: "납부 카드", exact: true }).selectOption(cardId);
  await page.getByRole("button", { name: "계획 저장", exact: true }).click();
  await expect(page.getByRole("button", { name: "합성 HTTPS 월 계획", exact: true })).toBeVisible();
  const summary = page.getByRole("region", { name: "현재 월 지출 계획", exact: true });
  await expect(summary).toContainText("12,345원");
  await page.getByRole("button", { name: "합성 HTTPS 월 계획", exact: true }).click();
  await page.getByLabel("계획 금액 (미정이면 비워두기)", { exact: true }).fill("23456");
  await page.getByRole("button", { name: "계획 저장", exact: true }).click();
  await expect(summary).toContainText("23,456원");
  await page.reload();
  await expect(summary).toContainText("23,456원");
  const invariant = await page.evaluate(async () => {
    const read = async (path: string) => fetch(path).then((r) => r.json());
    const plans = await read("/api/v1/expense-plans");
    const plan = plans.items.find((p: { history: { title: string }[] }) =>
      p.history.some((v) => v.title === "합성 HTTPS 월 계획"),
    );
    const day = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
    const facts = await read("/api/v1/obligations/summary?month=" + day.slice(0, 7));
    const missing = await fetch("/api/v1/expense-plans/00000000-0000-4000-8000-000000000099");
    return { plan, facts, missing: missing.status };
  });
  expect(invariant.plan.versions[0].anchor_date).toBeNull();
  expect(invariant.plan.history).toHaveLength(2);
  expect(invariant.plan.history[0].revoked_at).not.toBeNull();
  expect(invariant.facts.obligation_count).toBe(0);
  expect(invariant.facts.actual_amount_krw).toBe("0");
  expect(invariant.missing).toBe(404);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "현재 월 지출 계획", exact: true })).toContainText(
    "23,456원",
  );
  await page.goto("/cards/" + cardId);
  await expect(page.getByRole("region", { name: "연결된 월 계획", exact: true })).toContainText(
    "합성 HTTPS 월 계획",
  );
  await page.goto("/fixed-payments?plan=" + invariant.plan.id);
  await expect(page.getByLabel("이름", { exact: true })).toHaveValue("합성 HTTPS 월 계획");
  await page.getByRole("button", { name: "계획 종료", exact: true }).click();
  await page.getByRole("button", { name: "종료하기", exact: true }).click();
  await expect(page.getByRole("region", { name: "현재 월 지출 계획", exact: true })).toContainText(
    "등록 0개",
  );
});
