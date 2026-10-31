import { expect, test } from "@playwright/test";
import { mockPrivateVault, vaultPassword } from "./support/vault-private";
import { uid } from "./support/finance";

test.use({ trace: "off", screenshot: "off", video: "off" });

test("batch initial secrets retry the uncertain row without rewriting completed cards", async ({
  page,
}) => {
  const { extra, state } = await mockPrivateVault(page);
  state.cashflow.cards[0]!.has_secret = false;
  state.cashflow.cards.push({ ...state.cashflow.cards[0]!, id: uid(51), alias: "합성 두 번째" });
  await page.reload();
  extra.fail = "REQUEST_FAILED";
  extra.status = 408;
  extra.failOnce = true;
  extra.failAt = 2;
  await page.getByRole("button", { name: "미등록 카드 비밀 일괄 입력", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  for (const index of [1, 2]) {
    await page.getByLabel(`${index}번 카드번호`, { exact: true }).fill("4242424242424242");
    await page.getByLabel(`${index}번 유효기간 연도`, { exact: true }).fill("2032");
    await page.getByLabel(`${index}번 유효기간 월`, { exact: true }).fill("12");
    await page.getByLabel(`${index}번 공유 CVC (선택)`, { exact: true }).fill("007");
  }
  await page.getByLabel("공유 CVC의 접근·백업·삭제 범위와 입력 대상을 확인했어요").check();
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
  await expect(page.getByRole("button", { name: "같은 요청으로 저장 결과 확인" })).toBeVisible();
  await expect(page.getByText("2건 중 1건 저장 완료", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "같은 요청으로 저장 결과 확인" }).click();
  await expect(page.getByRole("region", { name: "보관함 보호 작업" })).toHaveCount(0);
  expect(extra.writes).toHaveLength(3);
  expect(extra.writes[1]).toEqual(extra.writes[2]);
  expect(extra.writes[0]!.path).not.toBe(extra.writes[1]!.path);
  expect(JSON.stringify(extra.writes)).not.toContain("4242424242424242");
});

test("batch partial conflict refresh excludes completed cards and permits the remaining row", async ({
  page,
}) => {
  const { extra, state } = await mockPrivateVault(page);
  state.cashflow.cards[0]!.has_secret = false;
  state.cashflow.cards.push({ ...state.cashflow.cards[0]!, id: uid(51), alias: "합성 두 번째" });
  await page.reload();
  extra.fail = "VERSION_CONFLICT";
  extra.status = 409;
  extra.failOnce = true;
  extra.failAt = 2;
  await page.getByRole("button", { name: "미등록 카드 비밀 일괄 입력", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  for (const index of [1, 2]) {
    await page.getByLabel(`${index}번 카드번호`, { exact: true }).fill("4242424242424242");
    await page.getByLabel(`${index}번 유효기간 연도`, { exact: true }).fill("2032");
    await page.getByLabel(`${index}번 유효기간 월`, { exact: true }).fill("12");
    await page.getByLabel(`${index}번 공유 CVC (선택)`, { exact: true }).fill("007");
  }
  await page.getByLabel("공유 CVC의 접근·백업·삭제 범위와 입력 대상을 확인했어요").check();
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
  await expect(page.getByText("2건 중 1건 저장 완료", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "최신 보관함 상태 다시 확인", exact: true }).click();
  await expect(page.getByLabel("2번 카드번호", { exact: true })).toHaveCount(0);
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  await page.getByLabel("1번 카드번호", { exact: true }).fill("4242424242424242");
  await page.getByLabel("1번 유효기간 연도", { exact: true }).fill("2032");
  await page.getByLabel("1번 유효기간 월", { exact: true }).fill("12");
  await page.getByLabel("공유 CVC의 접근·백업·삭제 범위와 입력 대상을 확인했어요").check();
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
  await expect(page.getByRole("region", { name: "보관함 보호 작업" })).toHaveCount(0);
  expect(extra.writes).toHaveLength(3);
  expect(extra.writes[1]!.path).toEqual(extra.writes[2]!.path);
  expect(extra.writes[0]!.path).not.toBe(extra.writes[1]!.path);
  expect(JSON.stringify(extra.writes)).not.toContain("4242424242424242");
});

test("shared CVC replacement requires consent and sends only a v2 encrypted envelope", async ({
  page,
}) => {
  const { extra } = await mockPrivateVault(page);
  await page.getByRole("button", { name: "카드 비밀 등록·수정", exact: true }).click();
  await page.getByLabel("공유 CVC 처리", { exact: true }).selectOption("replace");
  await page.getByLabel("공유 CVC (3~4자리)", { exact: true }).fill("007");
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  await page.getByLabel("전체 카드 번호 (숫자만)").fill("4242424242424242");
  await page.getByLabel("유효기간 연도 (4자리)").fill("2032");
  await page.getByLabel("유효기간 월", { exact: true }).fill("12");
  await expect(page.getByRole("button", { name: "보호 작업 진행", exact: true })).toBeDisabled();
  await page.getByLabel("공유 CVC의 접근·백업·삭제 범위를 확인했어요.").check();
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
  await expect(page.getByRole("region", { name: "보관함 보호 작업" })).toHaveCount(0);
  expect(extra.writes).toHaveLength(1);
  expect(extra.writes[0]!.body.payload_schema_version).toBe(2);
  expect(extra.writes[0]!.body.ciphertext).toHaveLength(64);
  expect(Object.hasOwn(extra.writes[0]!.body, "cvc")).toBe(false);
  expect(JSON.stringify(extra.writes[0]!.body)).not.toContain("4242424242424242");
});

test("protected view decrypts only transient DOM and blur clears all without persistence", async ({
  page,
}) => {
  await mockPrivateVault(page);
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  await page.getByRole("button", { name: "보관함 암호로 30초 보기", exact: true }).click();
  await expect(page.getByLabel("일시적으로 표시하는 카드 번호·유효기간·공유 CVC")).toHaveText(
    "4242424242424242 · 2032/12",
  );
  expect(
    await page.evaluate(async () => [
      localStorage.length,
      sessionStorage.length,
      (await caches.keys()).length,
    ]),
  ).toEqual([0, 0, 0]);
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(page.getByLabel("일시적으로 표시하는 카드 번호·유효기간·공유 CVC")).toHaveText("");
  await expect(page.getByText(/화면 이동 또는 제한 시간으로 보관함을 잠갔어요/)).toBeVisible();
});

test("wrong password never reveals plaintext and clears uncontrolled fields", async ({ page }) => {
  await mockPrivateVault(page);
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill("Synthetic incorrect password");
  await page.getByRole("button", { name: "보관함 암호로 30초 보기", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("입력 형식을 확인");
  await expect(page.getByLabel("현재 보관함 암호", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("일시적으로 표시하는 카드 번호·유효기간·공유 CVC")).toHaveText("");
});

test("card write sends only encrypted envelope and an ambiguous 408 retries exact ciphertext and key", async ({
  page,
}) => {
  const { extra } = await mockPrivateVault(page);
  extra.fail = "REQUEST_FAILED";
  extra.status = 408;
  extra.failOnce = true;
  await page.getByRole("button", { name: "카드 비밀 등록·수정", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  await page.getByLabel("전체 카드 번호 (숫자만)").fill("4242424242424242");
  await page.getByLabel("유효기간 연도 (4자리)").fill("2032");
  await page.getByLabel("유효기간 월", { exact: true }).fill("12");
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
  await expect(page.getByRole("button", { name: "같은 요청으로 저장 결과 확인" })).toBeVisible();
  await page.getByRole("button", { name: "같은 요청으로 저장 결과 확인" }).click();
  await expect(
    page.getByRole("heading", { name: "카드 번호·유효기간 입력", exact: true }),
  ).toHaveCount(0);
  expect(extra.writes).toHaveLength(2);
  expect(extra.writes[0]).toEqual(extra.writes[1]);
  expect(JSON.stringify(extra.writes)).not.toContain("4242424242424242");
  expect(JSON.stringify(extra.writes)).not.toContain(vaultPassword);
  expect(Object.keys(extra.writes[0]!.body).sort()).toEqual([
    "ciphertext",
    "format_version",
    "key_version",
    "last_four",
    "nonce",
    "payload_schema_version",
  ]);
});

test("same-screen account reauthentication keeps secret fields empty then permits a fresh unlock", async ({
  page,
}) => {
  const { extra } = await mockPrivateVault(page);
  extra.fail = "REAUTHENTICATION_REQUIRED";
  extra.rejectReauth = true;
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  await page.getByRole("button", { name: "보관함 암호로 30초 보기", exact: true }).click();
  await page
    .getByLabel("현재 계정 로그인 비밀번호", { exact: true })
    .fill("Synthetic account password 2026!");
  await page.getByRole("button", { name: "이 화면에서 계정 다시 인증" }).click();
  await expect(page.getByRole("alert")).toContainText("계정 로그인 비밀번호를 확인");
  await expect(page.getByLabel("현재 계정 로그인 비밀번호", { exact: true })).toHaveValue("");
  await page
    .getByLabel("현재 계정 로그인 비밀번호", { exact: true })
    .fill("Synthetic corrected account password 2026!");
  await page.getByRole("button", { name: "이 화면에서 계정 다시 인증" }).click();
  await expect(page.getByLabel("현재 보관함 암호", { exact: true })).toBeEnabled();
  await expect(page.getByLabel("현재 보관함 암호", { exact: true })).toHaveValue("");
  expect(extra.reauths).toBe(2);
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  await page.getByRole("button", { name: "보관함 암호로 30초 보기", exact: true }).click();
  await expect(page.getByLabel("일시적으로 표시하는 카드 번호·유효기간·공유 CVC")).toHaveText(
    "4242424242424242 · 2032/12",
  );
});

test("setup shows recovery before any write and requires explicit offline acknowledgement", async ({
  page,
}) => {
  const { extra, state } = await mockPrivateVault(page);
  Object.assign(state.status, {
    initialized: false,
    id: null,
    version: null,
    current_key_version: null,
    own_membership: "not_enrolled",
  });
  await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
  await page.getByRole("button", { name: "보관함 처음 설정", exact: true }).click();
  await page.getByLabel("합성 구성원 하나의 새 보관함 암호", { exact: true }).fill(vaultPassword);
  await page
    .getByLabel("합성 구성원 하나의 새 보관함 암호 확인", { exact: true })
    .fill(vaultPassword);
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
  await expect(page.getByLabel("새 보관함 복구코드", { exact: true })).toHaveText(
    /^[A-Za-z0-9_-]{43}$/,
  );
  expect(extra.writes).toHaveLength(0);
  await expect(page.getByRole("button", { name: "보관 확인·설정 완료" })).toBeDisabled();
  await page.getByLabel("새 복구코드를 오프라인으로 보관했어요").check();
  await page.getByRole("button", { name: "보관 확인·설정 완료" }).click();
  await expect(page.getByLabel("새 보관함 복구코드", { exact: true })).toHaveCount(0);
  expect(extra.writes).toHaveLength(1);
});

test("a delayed response after leaving the protected screen cannot render or persist secrets", async ({
  page,
}) => {
  const { extra } = await mockPrivateVault(page);
  extra.delay = 200;
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  await page.getByRole("button", { name: "보관함 암호로 30초 보기", exact: true }).click();
  await page.getByRole("button", { name: "보호 작업 닫기·잠금" }).click();
  await page.waitForTimeout(400);
  await expect(page.getByLabel("일시적으로 표시하는 카드 번호·유효기간·공유 CVC")).toHaveCount(0);
  expect(await page.locator("body").textContent()).not.toContain("4242424242424242");
});

test("display expires after 30 seconds even while the page stays focused", async ({ page }) => {
  await mockPrivateVault(page);
  await page.clock.install();
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  await page.getByRole("button", { name: "보관함 암호로 30초 보기", exact: true }).click();
  await expect(page.getByLabel("일시적으로 표시하는 카드 번호·유효기간·공유 CVC")).toHaveText(
    "4242424242424242 · 2032/12",
  );
  await page.clock.fastForward(30_001);
  await expect(page.getByLabel("일시적으로 표시하는 카드 번호·유효기간·공유 CVC")).toHaveText("");
  await expect(page.getByText(/화면 이동 또는 제한 시간으로 보관함을 잠갔어요/)).toBeVisible();
});

test("live membership revocation clears a displayed card at the next permission check", async ({
  page,
}) => {
  const { state } = await mockPrivateVault(page);
  await page.clock.install();
  await page.getByRole("button", { name: "전체 번호·유효기간 열람", exact: true }).click();
  await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
  await page.getByRole("button", { name: "보관함 암호로 30초 보기", exact: true }).click();
  await expect(page.getByLabel("일시적으로 표시하는 카드 번호·유효기간·공유 CVC")).toHaveText(
    "4242424242424242 · 2032/12",
  );
  state.status.own_membership = "revoked";
  state.status.members[0]!.status = "revoked";
  state.status.version!++;
  await page.clock.fastForward(5_001);
  await expect(page.getByLabel("일시적으로 표시하는 카드 번호·유효기간·공유 CVC")).toHaveText("");
});

test("recovery code has an absolute 30-second display bound even after confirmation input", async ({
  page,
}) => {
  const { extra, state } = await mockPrivateVault(page);
  Object.assign(state.status, {
    initialized: false,
    id: null,
    version: null,
    current_key_version: null,
    own_membership: "not_enrolled",
  });
  await page.clock.install();
  await page.getByRole("button", { name: "보관함 상태 다시 확인", exact: true }).click();
  await page.getByRole("button", { name: "보관함 처음 설정", exact: true }).click();
  await page.getByLabel("합성 구성원 하나의 새 보관함 암호", { exact: true }).fill(vaultPassword);
  await page
    .getByLabel("합성 구성원 하나의 새 보관함 암호 확인", { exact: true })
    .fill(vaultPassword);
  await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
  await expect(page.getByLabel("새 보관함 복구코드", { exact: true })).toHaveText(
    /^[A-Za-z0-9_-]{43}$/,
  );
  await page.clock.fastForward(29_000);
  await page.getByLabel("새 복구코드를 오프라인으로 보관했어요").check();
  await page.clock.fastForward(1_001);
  await expect(page.getByLabel("새 보관함 복구코드", { exact: true })).toHaveText("");
  await expect(page.getByRole("button", { name: "보관 확인·설정 완료" })).toHaveCount(0);
  expect(extra.writes).toHaveLength(0);
});

for (const action of ["keep", "remove"] as const)
  test(`shared CVC ${action} preserves explicit intent across edits`, async ({ page }) => {
    const { extra } = await mockPrivateVault(page, "007");
    await page.getByRole("button", { name: "카드 비밀 등록·수정", exact: true }).click();
    await page.getByLabel("현재 보관함 암호", { exact: true }).fill(vaultPassword);
    await page.getByLabel("전체 카드 번호 (숫자만)").fill("4242424242424242");
    await page.getByLabel("유효기간 연도 (4자리)").fill("2032");
    await page.getByLabel("유효기간 월", { exact: true }).fill("12");
    await page.getByLabel("공유 CVC 처리", { exact: true }).selectOption(action);
    if (action === "remove")
      await page.getByLabel("공유 CVC의 접근·백업·삭제 범위를 확인했어요.").check();
    await page.getByRole("button", { name: "보호 작업 진행", exact: true }).click();
    await expect(page.getByRole("region", { name: "보관함 보호 작업" })).toHaveCount(0);
    const correct = await page.evaluate(
      async ({ opaque, body, password, action }) => {
        const c = await import("/src/features/vault/crypto.ts");
        const scope = { householdId: opaque.own.household_id, keyVersion: 1 };
        const pw = c.passwordBytes(password);
        const key = await c.unwrapMember(pw, scope, opaque.own.member_id, opaque.own, opaque.check);
        const plain = await c.decryptCard(key, scope, opaque.card.card_id, body);
        const ok =
          c.cardCvc(plain) === (action === "keep" ? "007" : "") && c.payloadSchema(plain) === 2;
        c.wipe(plain);
        c.wipe(pw);
        key.destroy();
        return ok;
      },
      { opaque: extra.opaque, body: extra.writes[0]!.body, password: vaultPassword, action },
    );
    expect(correct).toBe(true);
  });
