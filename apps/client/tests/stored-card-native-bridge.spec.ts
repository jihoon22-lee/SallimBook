import { expect, test } from "@playwright/test";

test.use({ trace: "off", screenshot: "off", video: "off" });
const cardId = "00000000-0000-4000-8000-000000000001";
for (const scenario of ["completed", "cancelled", "extra", "locked"]) {
  test(`stored card native bridge returns only status: ${scenario}`, async ({ page }) => {
    await page.route("**/__stored-card", (route) =>
      route.fulfill({
        contentType: "text/html",
        body: "<!doctype html><title>Synthetic native test</title>",
      }),
    );
    await page.addInitScript((scenario) => {
      Object.assign(window, {
        __calls: [],
        CapacitorCustomPlatform: { name: "android" },
        Capacitor: {
          PluginHeaders: [
            { name: "SallimBookAuth", methods: [{ name: "openCardDetailsUI", rtype: "promise" }] },
          ],
          nativePromise: async (_: string, method: string, args: unknown) => {
            (window as unknown as { __calls: unknown[] }).__calls.push({ method, args });
            return scenario === "locked"
              ? { ok: false, code: "APP_LOCKED" }
              : {
                  ok: true,
                  value:
                    scenario === "extra"
                      ? { status: "completed", pan: "synthetic" }
                      : { status: scenario },
                };
          },
        },
      });
    }, scenario);
    await page.goto("/__stored-card");
    const result = await page.evaluate(async (cardId) => {
      const { nativeStoredCards } = await import("/src/platform/nativeStoredCards.ts");
      try {
        return await nativeStoredCards.open({ action: "edit", cardId });
      } catch (error) {
        return { code: (error as { code: string }).code };
      }
    }, cardId);
    expect(result).toEqual(
      scenario === "extra"
        ? { code: "FORBIDDEN" }
        : scenario === "locked"
          ? { code: "APP_LOCKED" }
          : { status: scenario },
    );
    expect(
      await page.evaluate(() => (window as unknown as { __calls: unknown[] }).__calls),
    ).toEqual([{ method: "openCardDetailsUI", args: { action: "edit", cardId } }]);
    const invalid = await page.evaluate(async (cardId) => {
      const { nativeStoredCards } = await import("/src/platform/nativeStoredCards.ts");
      try {
        await nativeStoredCards.open({ action: "edit", cardId, pan: "synthetic" } as never);
        return "accepted";
      } catch (error) {
        return (error as { code: string }).code;
      }
    }, cardId);
    expect(invalid).toBe("VALIDATION_ERROR");
    expect(
      await page.evaluate(() => (window as unknown as { __calls: unknown[] }).__calls.length),
    ).toBe(1);
  });
}
