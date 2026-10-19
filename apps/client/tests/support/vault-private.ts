import type { Page } from "@playwright/test";
import { mockVaultOverview } from "./vault-overview";
import { members, uid } from "./finance";
export const vaultPassword = "Synthetic vault password 2026!";
export async function mockPrivateVault(page: Page) {
  const state = await mockVaultOverview(page);
  state.cashflow.cards[0]!.has_secret = true;
  state.cashflow.cards[0]!.last_four = "4242";
  state.cashflow.cards[0]!.masked_number = "•••• 4242";
  const extra = {
    fail: "",
    failOnce: false,
    status: 403,
    delay: 0,
    opaque: null as any,
    writes: [] as { path: string; key: string; body: any }[],
    reauths: 0,
    rejectReauth: false,
  };
  await page.route("**/api/v1/vault/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!/wrappings\/me$|initialize$|recover$|recovery-wrap$/.test(path)) return route.fallback();
    if (extra.delay) await new Promise((resolve) => setTimeout(resolve, extra.delay));
    if (extra.fail && extra.status !== 408 && (!extra.failOnce || !extra.writes.length))
      return route.fulfill({
        status: extra.status,
        json: { error: { code: extra.fail, message: "UNTRUSTED_PRIVATE_DETAIL" } },
      });
    if (route.request().method() === "GET")
      return route.fulfill({
        json: path.endsWith("recovery-wrap")
          ? { wrapping: extra.opaque.recovery, key_check: extra.opaque.check }
          : { wrapping: extra.opaque.own, key_check: extra.opaque.check },
      });
    const body = route.request().postDataJSON();
    extra.writes.push({ path, key: route.request().headers()["idempotency-key"]!, body });
    if (body.member_wrapping)
      extra.opaque.own = { ...body.member_wrapping, household_id: uid(3), version: 1 };
    if (body.key_check) extra.opaque.check = { ...body.key_check, household_id: uid(3) };
    if (body.recovery_wrapping)
      extra.opaque.recovery = { ...body.recovery_wrapping, household_id: uid(3) };
    state.status.initialized = true;
    state.status.id = uid(800);
    state.status.version = 1;
    state.status.current_key_version = 1;
    state.status.own_membership = "active";
    return route.fulfill({ json: { id: uid(800), version: 1 } });
  });
  await page.route("**/api/v1/cards/*/secret-envelope", async (route) => {
    if (extra.delay) await new Promise((resolve) => setTimeout(resolve, extra.delay));
    if (route.request().method() === "GET") return route.fulfill({ json: extra.opaque.card });
    const body = route.request().method() === "DELETE" ? {} : route.request().postDataJSON();
    extra.writes.push({
      path: new URL(route.request().url()).pathname,
      key: route.request().headers()["idempotency-key"]!,
      body,
    });
    if (extra.fail) {
      const code = extra.fail;
      if (extra.failOnce) extra.fail = "";
      return route.fulfill({ status: extra.status, json: { error: { code } } });
    }
    if (route.request().method() === "DELETE") state.cashflow.cards[0]!.has_secret = false;
    return route.fulfill({ json: { id: uid(50), version: 2 } });
  });
  await page.route("**/api/v1/auth/web/reauthenticate", (route) => {
    extra.reauths++;
    if (extra.rejectReauth) {
      extra.rejectReauth = false;
      return route.fulfill({ status: 403, json: { error: { code: "REAUTHENTICATION_FAILED" } } });
    }
    extra.fail = "";
    return route.fulfill({ json: members[0] });
  });
  await page.goto("/vault");
  extra.opaque = await page.evaluate(
    async ({ password, householdId, memberId, cardId }) => {
      const c = await import("/src/features/vault/crypto.ts");
      const key = c.VaultKey.generate(),
        pw = c.passwordBytes(password),
        code = c.randomBytes(32),
        scope = { householdId, keyVersion: 1 };
      const plain = c.cardPayload("4242424242424242", 2032, 12);
      const result = {
        own: {
          ...(await c.wrapMember(key, pw, scope, memberId, 1)),
          household_id: householdId,
          version: 1,
        },
        recovery: {
          ...(await c.wrapRecovery(key, code, scope, 1)),
          household_id: householdId,
          version: 1,
        },
        check: { ...(await c.makeKeyCheck(key, scope)), household_id: householdId },
        card: {
          ...(await c.encryptCard(key, scope, cardId, plain)),
          household_id: householdId,
          card_id: cardId,
          id: cardId,
          revision: 1,
          card_version: 1,
        },
      };
      key.destroy();
      [pw, code, plain].forEach(c.wipe);
      return result;
    },
    { password: vaultPassword, householdId: uid(3), memberId: uid(2), cardId: uid(50) },
  );
  return { ...extra, extra, state };
}
