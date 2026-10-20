import type { components, operations } from "@sallimbook/api-client";
import { isDateOnly } from "../finance/dates";

export type Asset = components["schemas"]["AssetResponse"];
export type AssetInput = components["schemas"]["AssetCreate"];
export type AssetPatch = components["schemas"]["AssetPatch"];
export type AssetQuery = NonNullable<operations["listAssets"]["parameters"]["query"]>;
export const assetKinds = { asset: "자산", liability: "부채" } as const;
export const categories = {
  real_estate: "부동산",
  deposit: "보증금",
  financial: "금융 자산",
  loan: "대출",
  other: "기타",
} as const;
export const amountBases = {
  whole: "전체 금액 × 가계 지분",
  owned: "이미 가계 보유분인 금액",
} as const;

function scaledDecimal(digits: string, scale: number): string {
  const padded = digits.padStart(scale + 1, "0");
  const whole = padded.slice(0, -scale).replace(/^0+(?=\d)/, "");
  const fraction = padded.slice(-scale).replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole;
}

/** Exact decimal conversion; ownership ratios never pass through floating point. */
export function percentToShare(value: string): string | null {
  const match = /^(0|[1-9][0-9]{0,2})(?:\.([0-9]{1,16}))?$/.exec(value.trim());
  if (!match) return null;
  const fraction = match[2] ?? "";
  const digits = BigInt(`${match[1]}${fraction}`);
  if (digits > 100n * 10n ** BigInt(fraction.length)) return null;
  return scaledDecimal(digits.toString(), fraction.length + 2);
}

export function shareToPercent(value: string): string {
  if (!/^(0(?:\.[0-9]{1,18})?|1(?:\.0{1,18})?)$/.test(value)) return "";
  const [whole = "0", fraction = ""] = value.split(".");
  const digits = BigInt(whole + fraction) * 100n;
  return fraction.length ? scaledDecimal(digits.toString(), fraction.length) : digits.toString();
}

export type AssetDraft = {
  name: string;
  kind: AssetInput["kind"];
  category: AssetInput["category"] | "";
  ownership_kind: AssetInput["ownership_kind"] | "";
  owner_member_id: string;
  sharePercent: string;
  amount_basis: AssetInput["amount_basis"] | "";
  inclusion_status: AssetInput["inclusion_status"];
  started_on: string;
  ended_on: string;
  note: string;
};

export function newAssetDraft(financial = false): AssetDraft {
  return {
    name: "",
    kind: "asset",
    category: financial ? "financial" : "",
    ownership_kind: "",
    owner_member_id: "",
    sharePercent: "100",
    amount_basis: "",
    inclusion_status: "included",
    started_on: "",
    ended_on: "",
    note: "",
  };
}

export function assetDraft(asset: Asset): AssetDraft {
  return {
    name: asset.name,
    kind: asset.kind,
    category: asset.category,
    ownership_kind: asset.ownership_kind,
    owner_member_id: asset.owner_member_id ?? "",
    sharePercent: shareToPercent(asset.household_share ?? "1"),
    amount_basis: asset.amount_basis,
    inclusion_status: asset.inclusion_status ?? "included",
    started_on: asset.started_on,
    ended_on: asset.ended_on ?? "",
    note: asset.note ?? "",
  };
}

export function assetInput(draft: AssetDraft): AssetInput | null {
  const share = percentToShare(draft.sharePercent);
  if (
    !draft.name.trim() ||
    !draft.category ||
    !draft.ownership_kind ||
    !draft.amount_basis ||
    share === null ||
    !isDateOnly(draft.started_on) ||
    (draft.ended_on && (!isDateOnly(draft.ended_on) || draft.ended_on < draft.started_on)) ||
    (draft.ownership_kind === "individual" && !draft.owner_member_id)
  )
    return null;
  return {
    name: draft.name.trim(),
    kind: draft.kind,
    category: draft.category,
    ownership_kind: draft.ownership_kind,
    owner_member_id: draft.ownership_kind === "individual" ? draft.owner_member_id : null,
    household_share: share,
    amount_basis: draft.amount_basis,
    inclusion_status: draft.inclusion_status,
    started_on: draft.started_on,
    ended_on: draft.ended_on || null,
    note: draft.note.trim() || null,
  };
}

export function changedAssetFields(base: Asset, draft: AssetDraft): (keyof AssetDraft)[] {
  const initial = assetDraft(base);
  const changed = (Object.keys(initial) as (keyof AssetDraft)[]).filter(
    (field) => initial[field] !== draft[field],
  );
  if (changed.includes("ownership_kind") || changed.includes("owner_member_id")) {
    return [...new Set<keyof AssetDraft>([...changed, "ownership_kind", "owner_member_id"])];
  }
  return changed;
}

export function mergeAssetDraft(
  latest: Asset,
  draft: AssetDraft,
  fields: (keyof AssetDraft)[],
): AssetDraft {
  const merged = assetDraft(latest);
  for (const field of fields) Object.assign(merged, { [field]: draft[field] });
  // Ownership is one relationship, not two independent scalar edits.
  if (merged.ownership_kind === "joint") merged.owner_member_id = "";
  return merged;
}
