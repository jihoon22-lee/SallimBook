import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { safeReturnPath } from "../src/features/auth/returnPath";

// UI-only synthetic mocks. These do not establish cookie, server authorization or native security.
// Avoid recording credential form bodies in browser artifacts, including failed tests.
test.use({ trace: "off", screenshot: "off", video: "off" });

const member: components["schemas"]["MemberResponse"] = {
  user_id: "00000000-0000-4000-8000-000000000001",
  member_id: "00000000-0000-4000-8000-000000000002",
  household_id: "00000000-0000-4000-8000-000000000003",
  display_name: "합성 구성원",
  role: "owner",
};

async function mockIdentity(page: Page, loggedIn = false) {
  const state = {
    loggedIn,
    meOffline: false,
    rejectLogin: false,
    loginFailure: null as { status: number; code: string } | null,
    devicesUnauthorized: false,
    inviteError: null as string | null,
    revokeConflictOnce: false,
    revokeFailure: false,
    csrfFailuresRemaining: 0,
    csrfRenewals: 0,
    loginAttempts: 0,
    reauthAttempts: 0,
    rejectReauth: false,
    validReauthShape: false,
    logoutAttempts: 0,
    invitationAttempts: 0,
    acceptAttempts: 0,
    revokeVersions: [] as string[],
    paths: [] as string[],
    validLoginShape: false,
    validAcceptShape: false,
    csrf: `synthetic-csrf-${crypto.randomUUID()}`,
    invitationCode: `synthetic-invitation-${crypto.randomUUID()}`,
    devices: [
      {
        id: "00000000-0000-4000-8000-000000000004",
        label: "합성 다른 기기",
        platform: "web",
        status: "active",
        last_seen_at: "2026-10-17T00:00:00Z",
        current: false,
        version: 1,
      },
      {
        id: "00000000-0000-4000-8000-000000000005",
        label: "합성 현재 기기",
        platform: "web",
        status: "active",
        last_seen_at: "2026-10-17T00:00:00Z",
        current: true,
        version: 1,
      },
    ] as components["schemas"]["DeviceResponse"][],
  };
  const failure = (route: Route, status: number, code: string, version?: number) =>
    route.fulfill({
      status,
      json: {
        error: {
          code,
          message: "UNTRUSTED_SERVER_MESSAGE_MUST_NOT_RENDER",
          request_id: "synthetic-request",
          current_version: version ?? null,
        },
      } satisfies components["schemas"]["ErrorResponse"],
    });
  async function csrfRejected(route: Route) {
    if (state.csrfFailuresRemaining > 0) {
      state.csrfFailuresRemaining -= 1;
      state.csrf = `synthetic-csrf-${crypto.randomUUID()}`;
      await failure(route, 403, "CSRF_FAILED");
      return true;
    }
    if (route.request().headers()["x-csrf-token"] !== state.csrf) {
      await failure(route, 403, "CSRF_FAILED");
      return true;
    }
    return false;
  }

  await page.addInitScript(() => {
    const observed: boolean[] = [];
    Object.defineProperty(window, "__authCredentialsIncluded", { value: observed });
    const original = window.fetch;
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      const credentials =
        init?.credentials ?? (input instanceof Request ? input.credentials : "same-origin");
      if (new URL(url, location.href).pathname.startsWith("/api/"))
        observed.push(credentials === "include");
      return original.call(window, input, init);
    };
  });

  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    state.paths.push(path);
    if (path === "/api/v1/household/setup") return route.fulfill({ json: { available: false } });
    if (path === "/api/v1/me") {
      if (state.meOffline) return route.abort("failed");
      return state.loggedIn
        ? route.fulfill({ json: member })
        : failure(route, 401, "UNAUTHENTICATED");
    }
    if (path === "/api/v1/auth/passkeys")
      return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path === "/api/v1/auth/web/csrf") {
      if (!state.loggedIn) return failure(route, 401, "UNAUTHENTICATED");
      state.csrfRenewals += 1;
      state.csrf = `synthetic-csrf-${crypto.randomUUID()}`;
      return route.fulfill({ json: { csrf_token: state.csrf } });
    }
    if (path === "/api/v1/auth/web/login") {
      if (state.loginFailure)
        return failure(route, state.loginFailure.status, state.loginFailure.code);
      state.loginAttempts += 1;
      const body = route.request().postDataJSON();
      state.validLoginShape =
        Object.keys(body).sort().join(",") === "device_label,login_name,password" &&
        body.login_name === "synthetic.user" &&
        Boolean(body.password) &&
        body.device_label === "합성 브라우저";
      if (state.rejectLogin) return failure(route, 401, "UNAUTHENTICATED");
      state.loggedIn = true;
      state.csrf = `synthetic-csrf-${crypto.randomUUID()}`;
      return route.fulfill({
        json: {
          member,
          csrf_token: state.csrf,
          expires_at: new Date(Date.now() + 3_600_000).toISOString(),
        },
      });
    }
    if (path === "/api/v1/auth/web/logout") {
      state.logoutAttempts += 1;
      if (await csrfRejected(route)) return;
      state.loggedIn = false;
      return route.fulfill({ status: 204 });
    }
    if (path === "/api/v1/auth/web/reauthenticate") {
      state.reauthAttempts++;
      if (await csrfRejected(route)) return;
      state.validReauthShape = Object.keys(route.request().postDataJSON()).join(",") === "password";
      if (state.rejectReauth) return failure(route, 403, "REAUTHENTICATION_FAILED");
      return route.fulfill({ json: member });
    }
    if (path === "/api/v1/devices" && method === "GET") {
      if (state.devicesUnauthorized) return failure(route, 401, "UNAUTHENTICATED");
      return route.fulfill({ json: { items: state.devices, next_cursor: null } });
    }
    if (path.startsWith("/api/v1/devices/") && method === "DELETE") {
      state.revokeVersions.push(route.request().headers()["if-match"] ?? "");
      if (await csrfRejected(route)) return;
      const device = state.devices.find((item) => path.endsWith(item.id))!;
      if (state.revokeFailure) return failure(route, 503, "UNAVAILABLE");
      if (state.revokeConflictOnce) {
        state.revokeConflictOnce = false;
        device.version += 1;
      }
      if (route.request().headers()["if-match"] !== `"${device.version}"`)
        return failure(route, 409, "VERSION_CONFLICT", device.version);
      device.status = "revoked";
      device.version += 1;
      if (device.current) state.loggedIn = false;
      return route.fulfill({ status: 204 });
    }
    if (path === "/api/v1/household/invitations") {
      state.invitationAttempts += 1;
      if (await csrfRejected(route)) return;
      if (state.inviteError) return failure(route, 403, state.inviteError);
      return route.fulfill({
        status: 201,
        json: {
          id: "00000000-0000-4000-8000-000000000006",
          token: state.invitationCode,
          expires_at: new Date(Date.now() + 900_000).toISOString(),
        },
      });
    }
    if (path === "/api/v1/auth/invitations/accept") {
      state.acceptAttempts += 1;
      const body = route.request().postDataJSON();
      state.validAcceptShape =
        Object.keys(body).sort().join(",") === "display_name,password,token" &&
        Boolean(body.token) &&
        Boolean(body.password) &&
        body.display_name === "합성 새 구성원";
      return route.fulfill({
        status: 201,
        json: { ...member, display_name: "합성 새 구성원", role: "member" },
      });
    }
    return failure(route, 404, "NOT_FOUND");
  });
  return state;
}

async function expectNoPersistence(page: Page) {
  expect(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0)).toBe(
    true,
  );
  expect(
    await page.evaluate(() => {
      const observed = (window as unknown as { __authCredentialsIncluded: boolean[] })
        .__authCredentialsIncluded;
      return observed.every(Boolean);
    }),
  ).toBe(true);
}

async function fillLogin(page: Page) {
  await page.getByLabel("로그인 이름", { exact: true }).fill("synthetic.user");
  await page.getByLabel("비밀번호", { exact: true }).fill(`synthetic-only-${crypto.randomUUID()}`);
  await page.getByText("기기 이름 변경", { exact: true }).click();
  await page.getByLabel("이 기기 이름", { exact: true }).fill("합성 브라우저");
}

test("current web account reauthenticates without another login or changing devices", async ({
  page,
}) => {
  const api = await mockIdentity(page, true);
  api.rejectReauth = true;
  await page.goto("/settings/auth");
  await page.getByRole("link", { name: "패스키 관리 전 다시 로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "패스키로 로그인", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("로그인 이름", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("이 기기 이름", { exact: true })).toHaveCount(0);
  await page.getByLabel("비밀번호", { exact: true }).fill(`synthetic-only-${crypto.randomUUID()}`);
  await page.getByRole("button", { name: "다시 인증", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("기존 로그인은 유지");
  expect(api.loggedIn).toBe(true);
  api.rejectReauth = false;
  await page.getByLabel("비밀번호", { exact: true }).fill(`synthetic-only-${crypto.randomUUID()}`);
  await page.getByRole("button", { name: "다시 인증", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/auth$/);
  await expect(page.getByRole("heading", { name: "현재 계정" })).toBeVisible();
  expect(api.validReauthShape).toBe(true);
  expect(api.reauthAttempts).toBe(2);
  expect(api.loginAttempts).toBe(0);
  await expectNoPersistence(page);
});

test("return path accepts only same-app paths", () => {
  expect(safeReturnPath("/insurance/policies/1?tab=number#top")).toBe(
    "/insurance/policies/1?tab=number#top",
  );
  for (const value of [
    "//evil.example",
    "/\\evil.example",
    "https://evil.example/x",
    "javascript:alert(1)",
    "/login",
    "/login?next=/",
    "/login/",
    "/a/../login",
    "/a\nb",
    "",
    "settings",
    `/${"a".repeat(2048)}`,
    null,
    42,
  ])
    expect(safeReturnPath(value)).toBeNull();
});

test("revealed invitation disappears within thirty seconds", async ({ page }) => {
  await page.clock.install();
  await mockIdentity(page, true);
  await page.goto("/settings/auth");
  await page.getByText("기존 로그인 이름으로 초대", { exact: true }).click();
  await page.getByLabel("초대할 로그인 이름").fill("synthetic.partner");
  await page.getByRole("button", { name: "초대 만들기", exact: true }).click();
  await page.clock.fastForward(60_000);
  await page.getByRole("button", { name: "초대 코드 보기", exact: true }).click();
  await expect(page.getByLabel("생성된 초대 코드")).toBeVisible();
  await page.clock.fastForward(29_000);
  await expect(page.getByLabel("생성된 초대 코드")).toBeVisible();
  await page.clock.fastForward(1_000);
  await expect(page.getByLabel("생성된 초대 코드")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "초대 코드 보기", exact: true })).toHaveCount(0);
});

test("web login uses generated request fields and logout clears the displayed member without persistence", async ({
  page,
}) => {
  const api = await mockIdentity(page);
  await page.goto("/login");
  await expect(page.getByLabel("비밀번호", { exact: true })).toHaveAttribute(
    "autocomplete",
    "current-password",
  );
  await fillLogin(page);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/^https?:\/\/[^/]+\/$/);
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정" })).toBeVisible();
  await expect(page.getByRole("main").getByText("합성 구성원", { exact: true })).toBeVisible();
  expect(api.validLoginShape).toBe(true);
  await expectNoPersistence(page);
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page.getByRole("heading", { name: "로그인이 필요해요" })).toBeVisible();
  await expect(page.getByText("합성 구성원", { exact: true })).toHaveCount(0);
  expect(api.logoutAttempts).toBe(1);
  expect(api.paths.some((path) => path.includes("/native/"))).toBe(false);
  await expectNoPersistence(page);
});

test("reload refetches the cookie session and renews only an in-memory CSRF token", async ({
  page,
}) => {
  const api = await mockIdentity(page, true);
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정" })).toBeVisible();
  expect(api.csrfRenewals).toBe(1);
  await page.reload();
  await expect(page.getByRole("heading", { name: "현재 계정" })).toBeVisible();
  expect(api.csrfRenewals).toBe(2);
  expect(api.paths.filter((path) => path === "/api/v1/me")).toHaveLength(2);
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page.getByRole("heading", { name: "로그인이 필요해요" })).toBeVisible();
  expect(api.logoutAttempts).toBe(1);
  await expectNoPersistence(page);
});

test("session network failure offers retry and is distinct from confirmed signed-out state", async ({
  page,
}) => {
  const api = await mockIdentity(page);
  api.meOffline = true;
  await page.goto("/login");
  await expect(page.getByRole("alert")).toContainText("서버 연결을 확인하지 못했어요");
  await expect(page.getByLabel("로그인 이름", { exact: true })).toHaveCount(0);
  api.meOffline = false;
  await page.getByRole("button", { name: "로그인 상태 다시 확인" }).click();
  await expect(page.getByLabel("로그인 이름", { exact: true })).toBeVisible();
  expect(api.csrfRenewals).toBe(0);
});

test("failed login clears the password and never renders raw server messages", async ({ page }) => {
  const api = await mockIdentity(page);
  api.rejectLogin = true;
  await page.goto("/login");
  await fillLogin(page);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("로그인 이름이나 비밀번호를 확인");
  await expect(page.getByLabel("비밀번호", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("로그인 이름", { exact: true })).toHaveValue("synthetic.user");
  await expect(page.getByText("UNTRUSTED_SERVER_MESSAGE_MUST_NOT_RENDER")).toHaveCount(0);
  expect(api.loginAttempts).toBe(1);
  await expectNoPersistence(page);
});

test("device version conflict preserves the row and requires an explicit refetch before retry", async ({
  page,
}) => {
  const api = await mockIdentity(page, true);
  api.revokeConflictOnce = true;
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "합성 다른 기기 연결 해제", exact: true }).click();
  await page.getByRole("button", { name: "연결 해제 확인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("정보가 다른 곳에서 변경");
  expect(api.revokeVersions).toEqual(['"1"']);
  await expect(
    page.getByRole("button", { name: "합성 다른 기기 연결 해제", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "기기 목록 다시 불러오기" }).click();
  await page.getByRole("button", { name: "합성 다른 기기 연결 해제", exact: true }).click();
  await page.getByRole("button", { name: "연결 해제 확인", exact: true }).click();
  await expect(page.getByText("웹 브라우저 · 연결 해제됨", { exact: true })).toBeVisible();
  expect(api.revokeVersions).toEqual(['"1"', '"2"']);
});

test("non-CSRF mutation failures are not retried or shown as a successful revoke", async ({
  page,
}) => {
  const api = await mockIdentity(page, true);
  api.revokeFailure = true;
  await page.goto("/settings/auth");
  await page.getByRole("button", { name: "합성 다른 기기 연결 해제", exact: true }).click();
  await page.getByRole("button", { name: "연결 해제 확인", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("요청을 완료하지 못했어요");
  expect(api.revokeVersions).toEqual(['"1"']);
  await expect(page.getByText("연결 해제됨", { exact: false })).toHaveCount(0);
});

test("one CSRF failure renews and retries the mutation once", async ({ page }) => {
  const api = await mockIdentity(page, true);
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정" })).toBeVisible();
  api.csrfFailuresRemaining = 1;
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page.getByRole("heading", { name: "로그인이 필요해요" })).toBeVisible();
  expect(api.csrfRenewals).toBe(2);
  expect(api.logoutAttempts).toBe(2);
  await expectNoPersistence(page);
});

test("a repeated CSRF failure stops after one retry and retains a truthful error state", async ({
  page,
}) => {
  const api = await mockIdentity(page, true);
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "현재 계정" })).toBeVisible();
  api.csrfFailuresRemaining = 2;
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("인증 상태가 다시 변경");
  await expect(page.getByRole("heading", { name: "현재 계정" })).toBeVisible();
  expect(api.logoutAttempts).toBe(2);
  expect(api.csrfRenewals).toBe(2);
});

test("partner invitation asks for recent login when the server requires it", async ({ page }) => {
  const api = await mockIdentity(page, true);
  api.inviteError = "REAUTHENTICATION_REQUIRED";
  await page.goto("/settings/auth");
  await page.getByText("기존 로그인 이름으로 초대", { exact: true }).click();
  await page.getByLabel("초대할 로그인 이름", { exact: true }).fill("synthetic.partner");
  await page.getByRole("button", { name: "초대 만들기", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("5분 이내 로그인");
  await expect(page.getByRole("link", { name: "다시 로그인", exact: true })).toHaveAttribute(
    "href",
    "/login",
  );
  await expect(page.getByLabel("생성된 초대 코드", { exact: true })).toHaveCount(0);
  expect(api.invitationAttempts).toBe(1);
});

test("invitation code is revealed explicitly, never put into the URL or persistent storage, and cleared on navigation", async ({
  page,
}) => {
  const api = await mockIdentity(page, true);
  await page.goto("/settings/auth");
  await page.getByText("기존 로그인 이름으로 초대", { exact: true }).click();
  await page.getByLabel("초대할 로그인 이름", { exact: true }).fill("synthetic.partner");
  await page.getByRole("button", { name: "초대 만들기", exact: true }).click();
  await page.getByRole("button", { name: "초대 코드 보기" }).click();
  expect(
    (await page.getByLabel("생성된 초대 코드", { exact: true }).textContent()) ===
      api.invitationCode,
  ).toBe(true);
  expect(page.url().includes(api.invitationCode)).toBe(false);
  await expectNoPersistence(page);
  await page.getByRole("link", { name: "최근 로그인 다시 확인" }).click();
  await expect(page.getByLabel("생성된 초대 코드", { exact: true })).toHaveCount(0);
  await page.goBack();
  await expect(page.getByRole("heading", { name: "현재 계정" })).toBeVisible();
  await expect(page.getByRole("button", { name: "초대 코드 보기" })).toHaveCount(0);
});

test("accepting an invitation uses manual code entry and does not pretend to create a login session", async ({
  page,
}) => {
  const api = await mockIdentity(page);
  await page.goto("/onboarding/invitation");
  const password = `synthetic-only-${crypto.randomUUID()}`;
  await page.getByLabel("초대 코드", { exact: true }).fill(api.invitationCode);
  await page.getByLabel("표시 이름", { exact: true }).fill("합성 새 구성원");
  await page.getByLabel("새 비밀번호", { exact: true }).fill(password);
  await page.getByLabel("새 비밀번호 확인", { exact: true }).fill(password);
  await page.getByRole("button", { name: "초대 수락하고 계정 등록" }).click();
  await expect(page.getByRole("heading", { name: "계정 등록을 마쳤어요" })).toBeVisible();
  expect(api.validAcceptShape).toBe(true);
  expect(api.loggedIn).toBe(false);
  expect(api.loginAttempts).toBe(0);
  expect(page.url().includes(api.invitationCode)).toBe(false);
  await expectNoPersistence(page);
});

test("expired session during protected loading removes the member view", async ({ page }) => {
  const api = await mockIdentity(page, true);
  api.devicesUnauthorized = true;
  await page.goto("/settings/auth");
  await expect(page.getByRole("heading", { name: "로그인이 필요해요" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "현재 계정" })).toHaveCount(0);
});

test("native Android shows an unavailable state without JS credential requests or forms", async ({
  page,
}) => {
  const api = await mockIdentity(page);
  await page.addInitScript(() => {
    Object.defineProperty(window, "CapacitorCustomPlatform", { value: { name: "android" } });
  });
  for (const path of ["/login", "/onboarding", "/settings/auth"]) {
    await page.goto(path);
    await expect(
      page.getByRole("heading", { name: "네이티브 인증을 준비하고 있어요" }),
    ).toBeVisible();
    await expect(page.locator("input")).toHaveCount(0);
  }
  expect(api.paths).toEqual([]);
  await expectNoPersistence(page);
});
test("login rate limit shows a wait message instead of a credential error", async ({ page }) => {
  const api = await mockIdentity(page);
  for (const code of ["RATE_LIMITED", "AUTH_BUSY"]) {
    api.loginFailure = { status: 429, code };
    await page.goto("/login");
    await fillLogin(page);
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("잠시 후 다시 시도해 주세요");
    await expect(page.getByRole("alert")).not.toContainText("로그인 이름이나 비밀번호");
  }
});
