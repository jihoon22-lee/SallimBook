import type { Page } from "@playwright/test";
import type { components } from "@sallimbook/api-client";
import { members } from "./finance";

export async function mockOnboarding(page: Page) {
  const state = {
    available: true,
    authenticated: false,
    role: "owner" as "owner" | "member",
    name: "합성 시작 계정",
    error: "",
    status: 409,
    setupOffline: false,
    setupReads: 0,
    setupWrites: 0,
    connectWrites: 0,
    codeWrites: 0,
    codeResponses: 0,
    loginWrites: 0,
    validSetup: false,
    validConnect: false,
    validCode: false,
    delay: 0,
    code: "00123456",
    csrf: `synthetic-csrf-${crypto.randomUUID()}`,
  };
  const member = (): components["schemas"]["MemberResponse"] => ({
    ...members[0]!,
    display_name: state.name,
    role: state.role,
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    const failure = (code = state.error, status = state.status) =>
      route.fulfill({
        status,
        json: { error: { code, message: "UNTRUSTED_ONBOARDING_ERROR", request_id: "synthetic" } },
      });
    const reply = (json: unknown, status = 200) =>
      route.fulfill({ status, json, headers: { "Cache-Control": "no-store" } });
    if (path === "/api/v1/me")
      return state.authenticated ? reply(member()) : failure("UNAUTHENTICATED", 401);
    if (path === "/api/v1/household/setup") {
      state.setupReads++;
      return state.setupOffline ? route.abort("failed") : reply({ available: state.available });
    }
    if (path === "/api/v1/auth/web/csrf") return reply({ csrf_token: state.csrf });
    if (path === "/api/v1/devices" || path === "/api/v1/auth/passkeys")
      return reply({ items: [], next_cursor: null });
    if (path === "/api/v1/household/members") return reply([member()]);
    if (path === "/api/v1/auth/web/setup" || path === "/api/v1/auth/web/connect") {
      const setup = path.endsWith("/setup"),
        input = request.postDataJSON();
      if (setup) {
        state.setupWrites++;
        state.validSetup =
          Object.keys(input).sort().join(",") === "device_label,display_name,password" &&
          input.display_name === "합성 새 이름" &&
          input.device_label === "웹 브라우저" &&
          input.password.length >= 15;
      } else {
        state.connectWrites++;
        state.validConnect =
          Object.keys(input).sort().join(",") === "code,device_label,display_name,password" &&
          input.code === state.code &&
          input.display_name === "합성 새 이름" &&
          input.device_label === "웹 브라우저" &&
          input.password.length >= 15;
      }
      if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay));
      if (state.error) return failure();
      state.authenticated = true;
      state.available = false;
      state.name = "합성 새 이름";
      state.role = setup ? "owner" : "member";
      return reply(
        {
          member: member(),
          csrf_token: state.csrf,
          expires_at: new Date(Date.now() + 3_600_000).toISOString(),
        } satisfies components["schemas"]["WebLoginResponse"],
        201,
      );
    }
    if (path === "/api/v1/household/connection-code") {
      state.codeWrites++;
      state.validCode =
        request.method() === "POST" &&
        !request.postData() &&
        request.headers()["x-csrf-token"] === state.csrf;
      if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay));
      if (state.error) return failure();
      state.codeResponses++;
      return reply(
        {
          code: state.code,
          expires_at: new Date(Date.now() + 900_000).toISOString(),
        } satisfies components["schemas"]["ConnectionCodeResponse"],
        201,
      );
    }
    if (path === "/api/v1/auth/web/login") {
      state.loginWrites++;
      return failure("UNAUTHENTICATED", 401);
    }
    if (path === "/api/v1/auth/web/logout") {
      state.authenticated = false;
      return route.fulfill({ status: 204 });
    }
    return failure("NOT_FOUND", 404);
  });
  return state;
}

export async function mockNativeOnboarding(page: Page) {
  const state = {
    available: true,
    authenticated: false,
    role: "owner",
    cancelled: false,
    locked: false,
    unlockBeforeResult: false,
    lockBeforeResult: false,
    failure: "",
    method: "",
    calls: [] as { method: string; args: Record<string, unknown> }[],
    http: [] as string[],
  };
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) state.http.push(request.url());
  });
  async function emitLock(locked: boolean) {
    state.locked = locked;
    await page.evaluate((locked) => (window as any).syntheticOnboardingLock(locked), locked);
  }
  await page.exposeFunction(
    "syntheticNativeOnboarding",
    async (method: string, args: Record<string, unknown>) => {
      state.calls.push({ method, args });
      const success = (value: unknown) => ({ ok: true, value });
      const metadata = (body: unknown) => success({ status: 200, body });
      if (state.failure && state.method === method) return { ok: false, code: state.failure };
      if (state.locked && (method === "getSession" || method === "request"))
        return { ok: false, code: "APP_LOCKED" };
      if (method === "getSession")
        return success({ available: true, authenticated: state.authenticated });
      if (method === "getSetupStatus") return success({ available: state.available });
      if (method === "createHousehold" || method === "connectHousehold") {
        if (!state.cancelled) {
          state.authenticated = true;
          state.available = false;
          state.role = method === "createHousehold" ? "owner" : "member";
        }
        if (state.unlockBeforeResult) await emitLock(false);
        if (state.lockBeforeResult) await emitLock(true);
        return success({ status: state.cancelled ? "cancelled" : "authenticated" });
      }
      if (method === "createConnectionCode")
        return success({ status: state.cancelled ? "cancelled" : "created" });
      if (method === "request") {
        if (args.path === "/api/v1/me")
          return metadata({ ...members[0], role: state.role, display_name: "합성 앱 새 계정" });
        if (
          String(args.path).startsWith("/api/v1/devices") ||
          String(args.path).startsWith("/api/v1/auth/passkeys")
        )
          return metadata({ items: [], next_cursor: null });
      }
      return { ok: false, code: "INVALID_REQUEST" };
    },
  );
  await page.addInitScript(() => {
    const listeners = new Map<string, (event: { locked: boolean }) => void>();
    let next = 0;
    Object.assign(window, {
      syntheticOnboardingLock: (locked: boolean) =>
        listeners.forEach((listener) => listener({ locked })),
      CapacitorCustomPlatform: { name: "android" },
      Capacitor: {
        PluginHeaders: [
          {
            name: "SallimBookAuth",
            methods: [
              "getSession",
              "getSetupStatus",
              "createHousehold",
              "connectHousehold",
              "createConnectionCode",
              "request",
            ]
              .map((name) => ({ name, rtype: "promise" }))
              .concat([
                { name: "addListener", rtype: "callback" },
                { name: "removeListener", rtype: "promise" },
              ]),
          },
        ],
        nativeCallback: (
          _plugin: string,
          _method: string,
          _args: unknown,
          listener: (event: { locked: boolean }) => void,
        ) => {
          const id = String(++next);
          listeners.set(id, listener);
          return id;
        },
        nativePromise: (_plugin: string, method: string, args: Record<string, unknown> = {}) => {
          if (method === "removeListener") {
            listeners.delete(String(args.callbackId));
            return Promise.resolve();
          }
          return (window as any).syntheticNativeOnboarding(method, args);
        },
      },
    });
  });
  return Object.assign(state, { emitLock });
}
