import { MemberLoadError, useHouseholdMembers } from "../finance/FinanceSupport";
import { todaySeoul } from "../finance/dates";
import { AccountSelect } from "../finance/AccountChoices";
import type { IncomeDraft } from "./model";
import { manualKinds } from "./model";
export function IncomeFields({
  draft,
  onChange,
  disabled = false,
  fixedScope = false,
}: {
  draft: IncomeDraft;
  onChange: (draft: IncomeDraft) => void;
  disabled?: boolean;
  fixedScope?: boolean;
}) {
  const members = useHouseholdMembers();
  const change = (field: keyof IncomeDraft, value: string) =>
    onChange({ ...draft, [field]: value });
  return (
    <fieldset disabled={disabled}>
      <legend>{fixedScope ? "대체할 수입 내용" : "수입 내용"}</legend>
      <div className="form-grid">
        <div className="form-field">
          <label>
            수입 구성원
            <select
              value={draft.member}
              disabled={fixedScope || members.loading}
              onChange={(event) => change("member", event.target.value)}
              required
            >
              <option value="">구성원 선택</option>
              {members.members.map((member) => (
                <option key={member.member_id} value={member.member_id}>
                  {member.display_name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="form-field">
          <label>
            수입 종류
            <select
              value={draft.kind}
              disabled={fixedScope}
              onChange={(event) => change("kind", event.target.value)}
            >
              {Object.entries(manualKinds).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="form-field">
          <label>
            수입 귀속월
            <input
              type="month"
              value={draft.month}
              min="0001-01"
              max="9999-12"
              disabled={fixedScope}
              onChange={(event) => change("month", event.target.value)}
              required
            />
          </label>
        </div>
        <div className="form-field">
          <label>
            날짜 정밀도
            <select
              value={draft.precision}
              disabled={fixedScope}
              onChange={(event) => change("precision", event.target.value)}
            >
              <option value="month">월합계 · 입금일 미지정</option>
              <option value="day">실제 입금일</option>
            </select>
          </label>
        </div>
        {draft.precision === "day" && (
          <div className="form-field">
            <label>
              실제 입금일
              <input
                type="date"
                value={draft.date}
                max={todaySeoul()}
                onChange={(event) => change("date", event.target.value)}
                required
              />
            </label>
          </div>
        )}
        <div className="form-field">
          <label>
            수입 금액 (원)
            <input
              inputMode="numeric"
              type="text"
              pattern="[0-9]+"
              maxLength={20}
              value={draft.amount}
              onChange={(event) => change("amount", event.target.value)}
              required
            />
          </label>
        </div>
        <AccountSelect
          value={draft.account}
          onChange={(value) => change("account", value)}
          disabled={disabled}
        />
        <div className="form-field">
          <label>
            수입 메모
            <textarea
              maxLength={2000}
              value={draft.note}
              onChange={(event) => change("note", event.target.value)}
            />
          </label>
        </div>
      </div>
      <MemberLoadError error={members.error} retry={members.retry} />
      <p className="muted">
        월합계에는 입금일을 만들지 않아요. 귀속월과 실제 입금월이 달라도 실제 날짜를 그대로 기록해
        주세요.
      </p>
    </fieldset>
  );
}
