import { expect, test } from "@playwright/test";
import { documentLink, mockDocuments } from "./support/documents";
import { mockNativeDocuments } from "./support/documents-native";
import { uid } from "./support/finance";

for (const transport of ["web", "native"] as const) {
  for (const currentTarget of [true, false]) {
    for (const failPage of [false, true]) {
      test(`${transport} document history page two ${currentTarget ? "blocks duplicate" : "allows new target"}${failPage ? " after failure and retry" : ""}`, async ({
        page,
      }) => {
        const state = await mockDocuments(page);
        state.links = Array.from({ length: 50 }, (_, index) =>
          documentLink(8100 + index, {
            active: false,
            ended_at: "2026-10-18T00:00:00Z",
            end_reason: "합성 과거 연결 종료",
          }),
        );
        state.links.push(
          documentLink(8150, { target: { kind: "appliance", id: uid(currentTarget ? 100 : 101) } }),
        );
        let release: () => void = () => {};
        let pageStarted = false;
        let fail = failPage;
        const gate = new Promise<void>((resolve) => {
          release = resolve;
        });
        const handle = state.handle;
        state.handle = async (...args) => {
          const result = await handle(...args);
          if (args[0] === "GET" && args[1].endsWith("/links") && args[2]?.has("cursor")) {
            pageStarted = true;
            await gate;
            if (fail)
              return {
                status: 503,
                body: {
                  error: {
                    code: "REQUEST_FAILED",
                    message: "UNTRUSTED_PAGE_ERROR",
                    request_id: "synthetic",
                  },
                },
              };
          }
          return result;
        };
        const native = transport === "native" ? await mockNativeDocuments(page, state) : undefined;
        try {
          await page.goto(`/appliances/${uid(100)}`);
          await page.getByRole("button", { name: "첨부 문서 열기" }).click();
          await page.getByRole("button", { name: "기존 문서에서 연결·대기 기록 찾기" }).click();
          await page.getByRole("button", { name: "합성 영수증.png", exact: true }).click();
          const detail = page.getByRole("region", { name: "문서 상세", exact: true });
          const link = detail.getByRole("button", { name: "현재 대상에 문서 연결" });
          const more = detail.getByRole("button", { name: "연결 이력 더 보기" });
          await expect(detail.locator("ul.record-list > li")).toHaveCount(50);
          await expect(more).toBeEnabled();
          await expect(link).toBeDisabled();
          await expect(
            detail.getByText("연결 여부를 확인하려면 남은 연결 이력을 모두 확인해 주세요.", {
              exact: true,
            }),
          ).toBeVisible();
          await more.click();
          await expect.poll(() => pageStarted).toBe(true);
          await expect(more).toBeDisabled();
          await expect(link).toBeDisabled();
          release();
          if (failPage) {
            await expect(detail.getByRole("alert")).toBeVisible();
            await expect(link).toBeDisabled();
            await expect(page.getByText("UNTRUSTED_PAGE_ERROR")).toHaveCount(0);
            expect(state.writes).toHaveLength(0);
            fail = false;
            await detail.getByRole("button", { name: "연결 이력 다시 확인" }).click();
            await expect(detail.getByRole("alert")).toHaveCount(0);
            await expect(detail.locator("ul.record-list > li")).toHaveCount(50);
            await expect(more).toBeEnabled();
            await expect(link).toBeDisabled();
            await more.click();
          }
          await expect(detail.locator("ul.record-list > li")).toHaveCount(51);
          await expect(more).toHaveCount(0);
          expect(state.writes).toHaveLength(0);
          if (currentTarget) await expect(link).toBeDisabled();
          else {
            await expect(link).toBeEnabled();
            await link.click();
            await expect(detail.getByText("현재 대상에 연결 완료", { exact: true })).toBeVisible();
            expect(state.writes).toHaveLength(1);
            expect(state.writes[0]).toMatchObject({
              path: "/api/v1/document-links",
              method: "POST",
              version: '"1"',
              body: { document_id: uid(8000), target: { kind: "appliance", id: uid(100) } },
            });
            await expect(link).toBeDisabled();
          }
          if (native) expect(native.http).toEqual([]);
        } finally {
          release();
        }
      });
    }
  }
}
