import { amountBases, assetKinds, categories, shareToPercent } from "../model";
import type { Asset } from "../model";
import { dateLabel } from "../../finance/dates";
import type { HouseholdMember } from "../../finance/FinanceSupport";
import type { MonthValue } from "./model";
export type SnapshotScope = Pick<
  MonthValue,
  | "name"
  | "kind"
  | "category"
  | "ownership_kind"
  | "owner_member_id"
  | "household_share"
  | "amount_basis"
  | "inclusion_status"
  | "started_on"
  | "ended_on"
>;
export function assetScope(asset: Asset): SnapshotScope {
  return {
    name: asset.name,
    kind: asset.kind,
    category: asset.category,
    ownership_kind: asset.ownership_kind,
    owner_member_id: asset.owner_member_id ?? null,
    household_share: asset.household_share ?? "1",
    amount_basis: asset.amount_basis,
    inclusion_status: asset.inclusion_status ?? "included",
    started_on: asset.started_on,
    ended_on: asset.ended_on ?? null,
  };
}
export function snapshotOwner(
  row: Pick<SnapshotScope, "ownership_kind" | "owner_member_id">,
  members: HouseholdMember[],
): string {
  return row.ownership_kind === "joint"
    ? "공동 소유"
    : (members.find((member) => member.member_id === row.owner_member_id)?.display_name ??
        "당시 구성원");
}
export function ScopeChanges({
  before,
  after,
  members,
}: {
  before: SnapshotScope;
  after: SnapshotScope;
  members: HouseholdMember[];
}) {
  const fields: { label: string; old: string; next: string; changed: boolean }[] = [
    { label: "이름", old: before.name, next: after.name, changed: before.name !== after.name },
    {
      label: "자산·부채 구분",
      old: assetKinds[before.kind],
      next: assetKinds[after.kind],
      changed: before.kind !== after.kind,
    },
    {
      label: "분류",
      old: categories[before.category],
      next: categories[after.category],
      changed: before.category !== after.category,
    },
    {
      label: "소유 관계",
      old: snapshotOwner(before, members),
      next: snapshotOwner(after, members),
      changed:
        before.ownership_kind !== after.ownership_kind ||
        before.owner_member_id !== after.owner_member_id,
    },
    {
      label: "가계 지분",
      old: `${shareToPercent(before.household_share)}%`,
      next: `${shareToPercent(after.household_share)}%`,
      changed: shareToPercent(before.household_share) !== shareToPercent(after.household_share),
    },
    {
      label: "금액 입력 기준",
      old: amountBases[before.amount_basis],
      next: amountBases[after.amount_basis],
      changed: before.amount_basis !== after.amount_basis,
    },
    {
      label: "합계 반영",
      old: before.inclusion_status === "included" ? "포함" : "제외",
      next: after.inclusion_status === "included" ? "포함" : "제외",
      changed: before.inclusion_status !== after.inclusion_status,
    },
    {
      label: "보유 시작일",
      old: dateLabel(before.started_on),
      next: dateLabel(after.started_on),
      changed: before.started_on !== after.started_on,
    },
    {
      label: "보유 종료일",
      old: dateLabel(before.ended_on),
      next: dateLabel(after.ended_on),
      changed: before.ended_on !== after.ended_on,
    },
  ];
  const changed = fields.filter((field) => field.changed);
  return changed.length > 0 ? (
    <dl className="metadata-grid scope-change-list">
      {changed.map((field) => (
        <div key={field.label}>
          <dt>{field.label} 변경</dt>
          <dd>
            {field.old} → {field.next}
            {field.label === "소유 관계" && field.old === field.next
              ? " (소유자 연결이 달라짐)"
              : ""}
          </dd>
        </div>
      ))}
    </dl>
  ) : null;
}
