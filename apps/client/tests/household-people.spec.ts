import { openDisclosure } from "./support/task-ui";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { householdPeople, uid } from "./support/finance";
import { mockInsuranceEvents } from "./support/insurance-events";
import { mockNativeInsurance } from "./support/insurance-native";

type Person = components["schemas"]["PersonResponse"];
async function setup(page: Page, native: boolean) {
  const insurance = await mockInsuranceEvents(page);
  const people = {
    items: structuredClone(householdPeople),
    creates: [] as { key: string; input: Record<string, unknown> }[],
    loseNextCreate: false,
    conflictNext: false,
    saved: new Map<string, { id: string; version: number }>(),
    handle(method: string, args: Record<string, any>) {
      const reply = (body: unknown, status = 200) => ({ ok: true, value: { body, status } });
      if (method === "listHouseholdPeople") return reply({ items: this.items, next_cursor: null });
      if (method === "createHouseholdPerson") {
        this.creates.push({ key: args.idempotencyKey, input: args.input });
        let reference = this.saved.get(args.idempotencyKey);
        if (!reference) {
          const row: Person = {
            ...householdPeople[0]!,
            id: uid(700 + this.items.length),
            member_id: null,
            ...args.input,
          };
          this.items.push(row);
          reference = { id: row.id, version: 1 };
          this.saved.set(args.idempotencyKey, reference);
        }
        if (this.loseNextCreate) {
          this.loseNextCreate = false;
          return { ok: false, code: "NETWORK_UNAVAILABLE" };
        }
        return reply(reference, 201);
      }
      const row = this.items.find((p) => p.id === args.personId)!;
      if (this.conflictNext) {
        this.conflictNext = false;
        row.version++;
        row.display_name = "배우자가 고친 이름";
      }
      if (args.ifMatch !== `"${row.version}"`)
        return reply(
          { error: { code: "VERSION_CONFLICT", message: "synthetic", request_id: "synthetic" } },
          409,
        );
      Object.assign(row, args.input);
      row.version++;
      if (args.input.active !== undefined)
        row.archived_at = row.active ? null : "2026-10-24T00:00:00Z";
      return reply(row);
    },
  };
  const bridge = native ? await mockNativeInsurance(page, insurance, people) : null;
  if (!native)
    await page.route("**/api/v1/household/people**", async (route) => {
      const request = route.request(),
        method = request.method(),
        path = new URL(request.url()).pathname;
      const args =
        method === "GET"
          ? {}
          : {
              input: request.postDataJSON(),
              idempotencyKey: request.headers()["idempotency-key"],
              personId: path.split("/").at(-1),
              ifMatch: request.headers()["if-match"],
            };
      const result = people.handle(
        method === "GET"
          ? "listHouseholdPeople"
          : method === "POST"
            ? "createHouseholdPerson"
            : "updateHouseholdPerson",
        args,
      );
      if (!result.ok || !result.value) return route.abort("failed");
      await route.fulfill({ status: result.value.status, json: result.value.body });
    });
  return { people, insurance, bridge };
}
for (const native of [false, true]) {
  const mode = native ? "native" : "web";
  test(`${mode} family creation retries the same identity and preserves two login members`, async ({
    page,
  }) => {
    const { people, bridge } = await setup(page, native);
    people.loseNextCreate = true;
    await page.goto("/settings/people");
    await page.getByLabel("가족 이름", { exact: true }).fill("합성 자녀");
    await page.getByRole("button", { name: "가족 등록", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "가족 등록", exact: true }).click();
    await expect(page.getByRole("heading", { name: /합성 자녀/ })).toBeVisible();
    expect(people.creates).toHaveLength(2);
    expect(people.creates[0]!.key).toBe(people.creates[1]!.key);
    expect(people.items).toHaveLength(3);
    expect(people.items.filter((p) => p.member_id)).toHaveLength(2);
    await page.getByLabel("가족 이름", { exact: true }).fill("합성 자녀");
    await expect(
      page.getByText("같은 이름의 가족이 있어요. 다른 가족인지 확인해 주세요."),
    ).toBeVisible();
    if (bridge) expect(bridge.http).toEqual([]);
  });
  test(`${mode} family archive keeps history identity and conflict review keeps the typed name`, async ({
    page,
  }) => {
    const { people } = await setup(page, native);
    people.items.push({
      ...householdPeople[0]!,
      id: uid(702),
      member_id: null,
      relation: "parent",
      display_name: "합성 부모",
    });
    await page.goto("/settings/people");
    await page.getByRole("button", { name: "이름·관계 수정" }).click();
    await page.getByLabel("가족 이름", { exact: true }).last().fill("내가 적은 이름");
    people.conflictNext = true;
    await page.getByRole("button", { name: "가족 정보 저장" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "최신 가족 정보 확인" }).click();
    await expect(page.getByText("현재 저장된 이름: 배우자가 고친 이름 · 부모")).toBeVisible();
    await expect(page.getByLabel("가족 이름", { exact: true }).last()).toHaveValue(
      "내가 적은 이름",
    );
    await page.getByRole("button", { name: "입력 유지하고 최신 버전으로 저장 준비" }).click();
    await page.getByRole("button", { name: "가족 정보 저장" }).click();
    await page.getByRole("button", { name: "가족 보관", exact: true }).click();
    await expect(page.getByRole("heading", { name: /내가 적은 이름.*보관됨/ })).toBeVisible();
    await page.getByRole("button", { name: "가족 다시 사용" }).click();
    await expect(page.getByRole("button", { name: "가족 보관", exact: true })).toBeVisible();
    expect(people.items.at(-1)!.id).toBe(uid(702));
  });
  test(`${mode} insurance patient and insured include family while policyholder remains a login member`, async ({
    page,
  }) => {
    const { people, insurance, bridge } = await setup(page, native);
    people.items.push({
      ...householdPeople[0]!,
      id: uid(702),
      member_id: null,
      relation: "child",
      display_name: "합성 자녀",
    });
    await page.goto("/insurance/cases/new");
    await page.getByLabel("사건 이름", { exact: true }).fill("합성 가족 진료");
    await page.getByRole("combobox", { name: "사건 환자", exact: true }).selectOption(uid(702));
    await page.getByRole("button", { name: "보험 사건 등록", exact: true }).click();
    await expect(page.getByRole("heading", { name: "합성 가족 진료", exact: true })).toBeVisible();
    expect(insurance.core.cases.at(-1)!.patient_member_id).toBe(uid(702));
    await expect(
      page
        .locator(".case-heading")
        .getByText(/합성 자녀/)
        .first(),
    ).toBeVisible();
    await page.goto("/insurance/policies/new");
    await expect(
      page
        .getByRole("combobox", { name: "보험 피보험자", exact: true })
        .locator("option", { hasText: "합성 자녀" }),
    ).toHaveCount(1);
    await expect(
      page
        .getByRole("combobox", { name: "보험 계약자", exact: true })
        .locator("option", { hasText: "합성 자녀" }),
    ).toHaveCount(0);
    people.items.at(-1)!.active = false;
    people.items.at(-1)!.archived_at = "2026-10-24T00:00:00Z";
    await page.reload();
    await expect(page.getByRole("combobox", { name: "보험 피보험자", exact: true })).toBeEnabled();
    await expect(
      page
        .getByRole("combobox", { name: "보험 피보험자", exact: true })
        .locator("option", { hasText: "합성 자녀" }),
    ).toHaveCount(0);
    await page.goto(`/insurance/policies?insured=${uid(702)}`);
    await openDisclosure(page, "계약 찾기");
    await expect(page.getByRole("combobox", { name: "피보험자 필터", exact: true })).toHaveValue(
      uid(702),
    );
    await expect(
      page
        .getByRole("combobox", { name: "피보험자 필터", exact: true })
        .locator("option", { hasText: "합성 자녀 · 보관됨" }),
    ).toHaveCount(1);
    if (bridge) expect(bridge.http).toEqual([]);
  });
}
