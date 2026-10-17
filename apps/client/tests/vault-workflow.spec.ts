import { expect, test } from "@playwright/test";
test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", (route) => route.fulfill({ status: 401, json: { error: { code: "UNAUTHENTICATED" } } }));
  await page.goto("/");
});
for (const mode of ["reauth", "retry", "manifest", "key"] as const) test(`rotation ${mode} preserves only validated progress and never skips mismatched ciphertext`, async ({ page }) => {
  const result = await page.evaluate(async (mode) => (await import("/tests/support/vault-workflow-browser.ts")).rotationScenario(mode), mode);
  if (mode === "reauth") { expect(result.finalized).toBe(1); expect(result.reauthCount).toBe(2); expect(new Set(result.reads).size).toBe(6); expect(result.reads).toHaveLength(6); }
  if (mode === "retry") { expect(result.finalized).toBe(1); expect(result.retryResult).toBe("rotation-pending"); expect(result.retryIdentical).toBe(true); expect(result.writes).toHaveLength(5); }
  if (mode === "manifest" || mode === "key") { expect(result.finalized).toBe(0); expect(result.snapshotError).toBe(true); expect(result.writes).toHaveLength(1); }
  expect(result.valid).toBe(true);
});

test("foreground lifetime wipes inputs/keys and rejects exact deadlines plus late adoption", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { VaultLifetime } = await import("/src/features/vault/lifetime.ts");
    const { VaultKey } = await import("/src/features/vault/crypto.ts");
    const root = document.createElement("section"); root.innerHTML = '<input data-vault-secret value="synthetic"><output data-vault-output>synthetic</output>'; document.body.append(root);
    const original = performance.now.bind(performance); let now = original(); Object.defineProperty(performance, "now", { configurable: true, value: () => now });
    let locked = 0, rejected = 0; const life = new VaultLifetime(root, () => locked++), bytes = life.ownBytes(new Uint8Array([1, 2, 3])), key = life.ownKey(VaultKey.generate());
    now += 60_000; try { life.assert(); } catch { rejected++; }
    const late = VaultKey.generate(), lateBytes = new Uint8Array([4]);
    try { life.ownKey(late); } catch { rejected++; } try { life.ownBytes(lateBytes); } catch { rejected++; }
    for (const value of [key, late]) { try { await value.fingerprint(); } catch { rejected++; } }
    const result = { locked, rejected, wiped: !bytes.some(Boolean) && !lateBytes.some(Boolean), dom: root.querySelector('input')!.value + root.querySelector('output')!.textContent };
    Object.defineProperty(performance, "now", { configurable: true, value: original }); root.remove(); return result;
  });
  expect(result).toEqual({ locked: 1, rejected: 5, wiped: true, dom: "" });
});
