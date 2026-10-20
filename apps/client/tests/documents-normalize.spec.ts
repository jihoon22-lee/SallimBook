import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mockDocuments } from "./support/documents";
import { uid } from "./support/finance";
import {
  canvasJpeg,
  exifOrientation,
  mpf,
  segments,
  seftTrailer,
  withSegments,
  xmp,
} from "./support/jpeg";
import { targetSize } from "../src/features/documents/normalize";

const appliance = `/appliances/${uid(100)}`;
const ALLOWED = new Set([
  "e0:JFIF",
  "e2:ICC_PROFILE",
  "ee:Adobe",
  "db:",
  "c0:",
  "c2:",
  "c4:",
  "dd:",
  "da:",
]);
const panel = (page: Page) => page.getByRole("region", { name: "가전 첨부 문서", exact: true });
const detail = (page: Page) => page.getByRole("region", { name: "문서 상세", exact: true });
const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");
async function open(page: Page) {
  await page.goto(appliance);
  await panel(page).getByRole("button", { name: "첨부 문서 열기" }).click();
}
async function choose(region: ReturnType<Page["getByRole"]>, name: string, buffer: Buffer) {
  await region
    .getByLabel("문서 파일", { exact: true })
    .setInputFiles({ name, mimeType: "image/jpeg", buffer });
  await region.getByRole("checkbox").check();
  await region.getByRole("button", { name: "문서 업로드", exact: true }).click();
}
const upload = (page: Page, name: string, buffer: Buffer) =>
  choose(page.getByRole("region", { name: "새 문서 첨부", exact: true }), name, buffer);
async function resumePending(page: Page, name: string, buffer: Buffer) {
  await panel(page).getByRole("button", { name, exact: true }).click();
  await choose(
    detail(page).getByRole("region", { name: "대기 파일 업로드", exact: true }),
    name,
    buffer,
  );
}
async function decodeInPage(page: Page, bytes: Buffer) {
  return page.evaluate(async (base64) => {
    const data = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
    const bitmap = await createImageBitmap(new Blob([data], { type: "image/jpeg" }));
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext("2d", { willReadFrequently: true })!;
    context.drawImage(bitmap, 0, 0);
    const band = (from: number, to: number) => {
      const pixels = context.getImageData(0, from, canvas.width, to - from).data;
      let total = 0;
      for (let index = 0; index < pixels.length; index += 4) total += pixels[index]!;
      return total / (pixels.length / 4);
    };
    const quarter = Math.floor(canvas.height / 4);
    const result = {
      width: bitmap.width,
      height: bitmap.height,
      top: band(0, quarter),
      bottom: band(canvas.height - quarter, canvas.height),
    };
    bitmap.close();
    return result;
  }, bytes.toString("base64"));
}

test("camera jpeg is normalized before hashing and upload", async ({ page }) => {
  const state = await mockDocuments(page);
  await open(page);
  const source = withSegments(
    await canvasJpeg(page, 1200, 900, "plain"),
    [exifOrientation(1), xmp(), mpf()],
    seftTrailer(),
  );
  await upload(page, "합성 카메라 영수증.jpg", source);
  await expect(detail(page).getByText("보관 완료", { exact: true })).toBeVisible();
  const [create, put] = state.writes;
  const body = put!.bytes!;
  expect(create!.body).toMatchObject({
    original_name: "합성 카메라 영수증.jpg",
    mime_type: "image/jpeg",
    size_bytes: body.length,
    checksum_sha256: sha256(body),
  });
  const parsed = segments(body);
  expect(parsed.trailing).toBe(0);
  expect(
    parsed.markers.every(({ marker, prefix }) => ALLOWED.has(`${marker.toString(16)}:${prefix}`)),
  ).toBe(true);
});

test("exif orientation is applied and the long edge is bounded", async ({ page }) => {
  const state = await mockDocuments(page);
  await open(page);
  await upload(
    page,
    "합성 회전 사진.jpg",
    withSegments(await canvasJpeg(page, 4000, 1000, "left-dark"), [exifOrientation(6)]),
  );
  await expect(detail(page).getByText("보관 완료", { exact: true })).toBeVisible();
  const view = await decodeInPage(page, state.writes[1]!.bytes!);
  expect({ width: view.width, height: view.height }).toEqual(targetSize(1000, 4000));
  // 왼쪽 검정 → 시계 방향 90° 회전 뒤 위쪽
  expect(view.top).toBeLessThan(64);
  expect(view.bottom).toBeGreaterThan(192);
});

test("jpeg normalization is deterministic for pending resume", async ({ page }) => {
  const state = await mockDocuments(page);
  state.failure = "upload-before";
  await open(page);
  const source = withSegments(
    await canvasJpeg(page, 1600, 1200, "plain"),
    [exifOrientation(1)],
    seftTrailer(),
  );
  await upload(page, "합성 대기 사진.jpg", source);
  await expect(
    page.getByRole("region", { name: "새 문서 첨부", exact: true }).getByRole("alert"),
  ).toBeVisible();
  const created = state.writes.find(
    (w) => w.method === "POST" && w.path === "/api/v1/documents",
  )!.body;
  // 메모리의 시도는 사라지고 새 canvas로 다시 정규화한다
  await page.reload();
  await open(page);
  await resumePending(page, "합성 대기 사진.jpg", source);
  await expect(detail(page).getByText("보관 완료", { exact: true })).toBeVisible();
  expect(
    state.writes.filter((w) => w.method === "POST" && w.path === "/api/v1/documents"),
  ).toHaveLength(1);
  expect(sha256(state.writes.filter((w) => w.method === "PUT").at(-1)!.bytes!)).toBe(
    created.checksum_sha256,
  );
});

test("undecodable jpeg uploads the original bytes unchanged", async ({ page }) => {
  const state = await mockDocuments(page);
  await open(page);
  const source = Buffer.from("SYNTHETIC DOCUMENT FIXTURE ONLY");
  await upload(page, "합성 손상 사진.jpg", source);
  await expect(detail(page).getByText("보관 완료", { exact: true })).toBeVisible();
  expect(state.writes[1]!.bytes!.equals(source)).toBe(true);
});
