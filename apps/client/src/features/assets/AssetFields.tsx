import { useId } from "react";
import type { HouseholdMember } from "../finance/FinanceSupport";
import { amountBases, assetKinds, categories } from "./model";
import type { AssetDraft } from "./model";

export const assetFieldLabels: Record<keyof AssetDraft, string> = {
  name: "자산 이름", kind: "자산·부채 구분", category: "분류", ownership_kind: "소유 방식", owner_member_id: "소유자",
  sharePercent: "가계 지분 (%)", amount_basis: "금액 입력 기준", inclusion_status: "순자산 합계 포함", started_on: "보유 시작일", ended_on: "보유 종료일", note: "메모",
};

export function AssetFields({ value, onChange, members, disabled, financial = false }: {
  value: AssetDraft; onChange: (next: AssetDraft) => void; members: HouseholdMember[]; disabled?: boolean; financial?: boolean;
}) {
  const id = useId();
  function set<K extends keyof AssetDraft>(field: K, next: AssetDraft[K]) {
    onChange({ ...value, [field]: next, ...(field === "ownership_kind" && next === "joint" ? { owner_member_id: "" } : {}) });
  }
  return <fieldset className="finance-fields" disabled={disabled}>
    <legend>{financial ? "연결할 금융 자산" : "자산 기본정보"}</legend>
    <div className="form-section"><div className="form-section-heading"><span className="step-index">01</span><h3>어떤 자산인가요</h3><p>이름과 종류를 구분해요.</p></div><div className="form-section-fields">
    <div className="form-field"><label htmlFor={`${id}-name`}>자산 이름</label><input id={`${id}-name`} value={value.name} onChange={(event) => set("name", event.target.value)} required maxLength={120} autoComplete="off" /></div>
    {!financial && <div className="form-pair">
      <div className="form-field"><label htmlFor={`${id}-kind`}>자산·부채 구분</label><select id={`${id}-kind`} value={value.kind} onChange={(event) => set("kind", event.target.value as AssetDraft["kind"])}>{Object.entries(assetKinds).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></div>
      <div className="form-field"><label htmlFor={`${id}-category`}>분류</label><select id={`${id}-category`} value={value.category} onChange={(event) => set("category", event.target.value as AssetDraft["category"])} required><option value="">분류 선택</option>{Object.entries(categories).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></div>
    </div>}
    </div></div>
    <div className="form-section"><div className="form-section-heading"><span className="step-index">02</span><h3>누구의 자산인가요</h3><p>소유와 금액 반영 기준을 정해요.</p></div><div className="form-section-fields">
    <div className="form-pair">
      <div className="form-field"><label htmlFor={`${id}-ownership`}>소유 방식</label><select id={`${id}-ownership`} value={value.ownership_kind} onChange={(event) => set("ownership_kind", event.target.value as AssetDraft["ownership_kind"])} required><option value="">소유 방식 선택</option><option value="joint">공동 소유</option><option value="individual">한 사람 소유</option></select><p className="muted">공동 소유 자산은 한 건만 등록해요.</p></div>
      {value.ownership_kind === "individual" && <div className="form-field"><label htmlFor={`${id}-owner`}>소유자</label><select id={`${id}-owner`} value={value.owner_member_id} onChange={(event) => set("owner_member_id", event.target.value)} required><option value="">구성원 선택</option>{members.map((member) => <option key={member.member_id} value={member.member_id}>{member.display_name}</option>)}</select></div>}
    </div>
    <div className="form-pair"><div className="form-field"><label htmlFor={`${id}-share`}>가계 지분 (%)</label><input id={`${id}-share`} value={value.sharePercent} onChange={(event) => set("sharePercent", event.target.value)} inputMode="decimal" required maxLength={20} aria-describedby={`${id}-share-help`} /><p className="muted" id={`${id}-share-help`}>0~100 사이의 비율이에요. 소수점 아래 최대 16자리까지 입력할 수 있어요.</p></div>
    <div className="form-field"><label htmlFor={`${id}-basis`}>금액 입력 기준</label><select id={`${id}-basis`} value={value.amount_basis} onChange={(event) => set("amount_basis", event.target.value as AssetDraft["amount_basis"])} required><option value="">금액 기준 선택</option>{Object.entries(amountBases).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><p className="muted">이미 가계 보유분인 금액에는 지분을 다시 곱하지 않아요. 이 화면에서는 금액 기준만 정해요.</p></div>
    </div><div className="form-field"><label htmlFor={`${id}-include`}>순자산 합계 포함</label><select id={`${id}-include`} value={value.inclusion_status} onChange={(event) => set("inclusion_status", event.target.value as AssetDraft["inclusion_status"])}><option value="included">합계에 포함</option><option value="excluded">합계에서 제외</option></select><p className="muted">가전 구매가격과 미래 연금 수령 예상액은 현재 자산으로 자동 합산하지 않아요.</p></div>
    </div></div>
    <div className="form-section"><div className="form-section-heading"><span className="step-index">03</span><h3>언제부터 보유했나요</h3><p>기간과 필요한 메모를 남겨요.</p></div><div className="form-section-fields">
    <div className="form-pair">
      <div className="form-field"><label htmlFor={`${id}-start`}>보유 시작일</label><input id={`${id}-start`} type="date" value={value.started_on} onChange={(event) => set("started_on", event.target.value)} min="0001-01-01" max="9999-12-31" required /><p className="muted">등록한 날짜가 아닌, 실제 보유를 시작한 날짜를 선택해 주세요.</p></div>
      <div className="form-field"><label htmlFor={`${id}-end`}>보유 종료일 (선택)</label><input id={`${id}-end`} type="date" value={value.ended_on} onChange={(event) => set("ended_on", event.target.value)} min={value.started_on || "0001-01-01"} max="9999-12-31" /><p className="muted">종료일을 입력하면 사용 종료 상태가 돼요. 비우면 사용 중으로 관리해요.</p></div>
    </div>
    <div className="form-field"><label htmlFor={`${id}-note`}>메모 (선택)</label><textarea id={`${id}-note`} value={value.note} onChange={(event) => set("note", event.target.value)} maxLength={2000} rows={4} /><p className="muted">계좌번호나 카드번호는 메모에 입력하지 말고 전용 화면을 이용해 주세요.</p></div>
    </div></div>
  </fieldset>;
}
