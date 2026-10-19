import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

// UI-only failures and lifecycle simulation. Success/signature verification is tested separately
// with Chromium's virtual authenticator, the real API and PostgreSQL over HTTPS.
test.use({ trace: "off", screenshot: "off", video: "off" });
const id = (last: number) => `00000000-0000-4000-8000-${String(last).padStart(12, "0")}`;
const member = {
  user_id: id(1),
  member_id: id(2),
  household_id: id(3),
  display_name: "합성 패스키 구성원",
  role: "owner",
};

async function mockPasskeys(
  page: Page,
  options: {
    signedIn?: boolean;
    expired?: boolean;
    required?: boolean;
    pending?: boolean;
    duplicate?: boolean;
    unsupported?: boolean;
    conflict?: boolean;
    disabled?: boolean;
    slowOptions?: boolean;
  } = {},
) {
  let releaseOptions = () => {};
  const optionsGate = new Promise<void>((resolve) => {
    releaseOptions = resolve;
  });
  const state = {
    verifies: 0,
    optionRequests: 0,
    deletes: [] as string[],
    version: 1,
    revoked: false,
    conflict: Boolean(options.conflict),
    releaseOptions,
  };
  await page.addInitScript((settings) => {
    const observed = { calls: 0, aborted: false, binary: false };
    Object.assign(window, { __passkeyUI: observed });
    if (settings.unsupported) {
      Object.defineProperty(window, "PublicKeyCredential", { value: undefined });
      return;
    }
    for (const method of ["create", "get"] as const)
      Object.defineProperty(navigator.credentials, method, {
        value: async (input: CredentialCreationOptions & CredentialRequestOptions) => {
          observed.calls++;
          observed.binary = input.publicKey?.challenge instanceof ArrayBuffer;
          if (settings.pending)
            return new Promise((_resolve, reject) =>
              input.signal?.addEventListener(
                "abort",
                () => {
                  observed.aborted = true;
                  reject(new DOMException("Synthetic UI cancellation", "AbortError"));
                },
                { once: true },
              ),
            );
          throw new DOMException(
            "Synthetic UI failure",
            settings.duplicate ? "InvalidStateError" : "NotAllowedError",
          );
        },
      });
  }, options);
  const passkey = () => ({
    id: id(10),
    label: "합성 첫 패스키",
    created_at: "2026-10-17T00:00:00Z",
    last_used_at: null,
    backed_up: false,
    device_type: "single_device",
    version: state.version,
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const failure = (status: number, code: string) =>
      route.fulfill({
        status,
        json: {
          error: { code, message: "UNTRUSTED_PASSKEY_SERVER_MESSAGE", request_id: "synthetic" },
        },
      });
    if (path === "/api/v1/household/setup") return route.fulfill({ json: { available: false } });
    if (path === "/api/v1/me")
      return options.signedIn ? route.fulfill({ json: member }) : failure(401, "UNAUTHENTICATED");
    if (path === "/api/v1/auth/web/csrf")
      return route.fulfill({ json: { csrf_token: "synthetic-ui-csrf" } });
    if (path === "/api/v1/devices")
      return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path === "/api/v1/auth/passkeys")
      return route.fulfill({
        json: {
          items: state.revoked
            ? []
            : new URL(route.request().url()).searchParams.has("cursor")
              ? [passkey(), { ...passkey(), id: id(11), label: "합성 둘째 패스키" }]
              : [passkey()],
          next_cursor:
            new URL(route.request().url()).searchParams.has("cursor") || state.revoked
              ? null
              : id(20),
        },
      });
    if (path === `/api/v1/auth/passkeys/${id(10)}`) {
      state.deletes.push(route.request().headers()["if-match"] ?? "");
      if (state.conflict) {
        state.conflict = false;
        state.version++;
        return failure(409, "VERSION_CONFLICT");
      }
      if (options.required) return failure(403, "REAUTHENTICATION_REQUIRED");
      state.revoked = true;
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/options")) {
      state.optionRequests++;
      if (options.slowOptions) await optionsGate;
      if (options.disabled) return failure(503, "PASSKEY_CONFIGURATION_INVALID");
      if (options.required) return failure(403, "REAUTHENTICATION_REQUIRED");
      const registration = path.includes("/register/");
      return route.fulfill({
        json: {
          challenge_id: id(30),
          expires_at: new Date(Date.now() + (options.expired ? -60_000 : 120_000)).toISOString(),
          public_key: {
            challenge: "c3ludGhldGljLXVpLWNoYWxsZW5nZQ",
            timeout: 120000,
            ...(registration
              ? {
                  rp: { name: "SallimBook", id: "localhost" },
                  user: {
                    id: "c3ludGhldGljLXVpLXVzZXI",
                    name: "synthetic",
                    displayName: "합성 구성원",
                  },
                  pubKeyCredParams: [{ type: "public-key", alg: -7 }],
                  authenticatorSelection: { userVerification: "required" },
                }
              : { rpId: "localhost", userVerification: "required" }),
          },
        },
      });
    }
    if (path.endsWith("/verify")) {
      state.verifies++;
      return failure(401, "PASSKEY_VERIFICATION_FAILED");
    }
    return failure(404, "NOT_FOUND");
  });
  return state;
}

async function fillPasskeyLogin(page: Page) {
  await page.getByLabel("로그인 이름", { exact: true }).fill("synthetic.passkey");
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 패스키 브라우저");
}
async function observations(page: Page) {
  return page.evaluate(
    () =>
      (window as unknown as { __passkeyUI: { calls: number; aborted: boolean; binary: boolean } })
        .__passkeyUI,
  );
}

test("unsupported WebAuthn leaves password login available and never requests options", async ({
  page,
}) => {
  const state = await mockPasskeys(page, { unsupported: true });
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "패스키로 로그인", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "로그인", exact: true })).toBeEnabled();
  expect(state.optionRequests).toBe(0);
});

test("cancelled browser assertion clears password and submits no verification", async ({
  page,
}) => {
  const state = await mockPasskeys(page);
  await page.goto("/login");
  await fillPasskeyLogin(page);
  await page.getByLabel("비밀번호", { exact: true }).fill("synthetic-discarded-before-passkey");
  await page.getByRole("button", { name: "패스키로 로그인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("패스키 인증을 완료하지 않았어요");
  expect((await page.getByLabel("비밀번호", { exact: true }).inputValue()) === "").toBe(true);
  expect(state.verifies).toBe(0);
  expect((await observations(page)).binary).toBe(true);
});

test("expired challenge is rejected before browser authentication", async ({ page }) => {
  const state = await mockPasskeys(page, { expired: true });
  await page.goto("/login");
  await fillPasskeyLogin(page);
  await page.getByRole("button", { name: "패스키로 로그인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("요청 시간이 지났어요");
  expect((await observations(page)).calls).toBe(0);
  expect(state.verifies).toBe(0);
});

test("duplicate registration reports safe error without claiming success", async ({ page }) => {
  const state = await mockPasskeys(page, { signedIn: true, duplicate: true });
  await page.goto("/settings/auth");
  await page.getByLabel("패스키 이름", { exact: true }).fill("합성 새 패스키");
  await page.getByRole("button", { name: "패스키 등록", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("이 패스키를 등록할 수 없어요");
  await expect(page.getByText("패스키를 등록했어요.", { exact: true })).toHaveCount(0);
  expect(state.verifies).toBe(0);
});

for (const reason of ["navigation", "pagehide", "visibility", "cancel"] as const)
  test(`pending ceremony aborts on ${reason} without verification`, async ({ page }) => {
    const state = await mockPasskeys(page, { pending: true });
    await page.goto("/login");
    await fillPasskeyLogin(page);
    await page.getByRole("button", { name: "패스키로 로그인", exact: true }).click();
    await expect.poll(async () => (await observations(page)).calls).toBe(1);
    if (reason === "navigation")
      await page.getByRole("link", { name: "배우자 연결", exact: true }).click();
    else if (reason === "pagehide")
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    else if (reason === "visibility")
      await page.evaluate(() => {
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          get: () => "hidden",
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });
    else await page.getByRole("button", { name: "패스키 인증 취소", exact: true }).click();
    await expect.poll(async () => (await observations(page)).aborted).toBe(true);
    expect(state.verifies).toBe(0);
  });

test("registration recent login failure does not open browser authenticator", async ({ page }) => {
  const state = await mockPasskeys(page, { signedIn: true, required: true });
  await page.goto("/settings/auth");
  await page.getByLabel("패스키 이름", { exact: true }).fill("합성 새 패스키");
  await page.getByRole("button", { name: "패스키 등록", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("5분 이내 로그인");
  await expect(page.getByText("UNTRUSTED_PASSKEY_SERVER_MESSAGE")).toHaveCount(0);
  expect((await observations(page)).calls).toBe(0);
  expect(state.verifies).toBe(0);
});

test("disabled deployment reports configuration without browser prompt", async ({ page }) => {
  const state = await mockPasskeys(page, { disabled: true });
  await page.goto("/login");
  await fillPasskeyLogin(page);
  await page.getByRole("button", { name: "패스키로 로그인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("패스키 연결이 설정되지 않았어요");
  expect((await observations(page)).calls).toBe(0);
  expect(state.verifies).toBe(0);
});

test("metadata pagination deduplicates and revoke conflict needs refreshed version", async ({
  page,
}) => {
  const state = await mockPasskeys(page, { signedIn: true, conflict: true });
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "패스키 더 보기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "합성 첫 패스키", exact: true })).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "합성 둘째 패스키", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "합성 첫 패스키 패스키 해제", exact: true }).click();
  await page.getByRole("button", { name: "패스키 해제 확인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("다시 불러온 뒤");
  await page.getByRole("button", { name: "패스키 목록 다시 불러오기", exact: true }).click();
  await page.getByRole("button", { name: "합성 첫 패스키 패스키 해제", exact: true }).click();
  await page.getByRole("button", { name: "패스키 해제 확인", exact: true }).click();
  await expect(page.getByText("등록된 패스키가 없어요.", { exact: true })).toBeVisible();
  expect(state.deletes).toEqual(['"1"', '"2"']);
});

test("a cancelled options request never opens a late authenticator", async ({ page }) => {
  const state = await mockPasskeys(page, { slowOptions: true });
  await page.goto("/login");
  await fillPasskeyLogin(page);
  await page.getByRole("button", { name: "패스키로 로그인", exact: true }).click();
  await expect.poll(() => state.optionRequests).toBe(1);
  await page.getByRole("button", { name: "패스키 인증 취소", exact: true }).click();
  await expect(page.getByRole("button", { name: "패스키로 로그인", exact: true })).toBeEnabled();
  state.releaseOptions();
  await expect(page.getByRole("alert")).toContainText("중단했어요");
  expect((await observations(page)).calls).toBe(0);
  expect(state.verifies).toBe(0);
});
