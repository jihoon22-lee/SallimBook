import { NamedReference } from "../finance/RelatedRecords";
import { dateLabel } from "../finance/dates";
import { formatKrw } from "../assets/months/model";
import { economicTypes, frequencies } from "./model";
import type { RuleTerms } from "./model";
export function RuleSummary({ terms }: { terms: RuleTerms }) {
  return (
    <dl className="metadata-grid">
      <div>
        <dt>분류</dt>
        <dd>{terms.category}</dd>
      </div>
      <div>
        <dt>예정액</dt>
        <dd>
          {terms.expected_amount_krw == null ? "미정" : formatKrw(terms.expected_amount_krw)} ·{" "}
          {terms.amount_mode === "fixed" ? "고정 금액" : "변동 금액"}
        </dd>
      </div>
      <div>
        <dt>납부 성격</dt>
        <dd>{economicTypes[terms.economic_type]}</dd>
      </div>
      <div>
        <dt>주기와 기준일</dt>
        <dd>
          {frequencies[terms.frequency]} · {terms.interval_count}
          {terms.frequency === "days" ? "일" : terms.frequency === "annual" ? "년" : "개월"}마다 ·
          기준 {dateLabel(terms.anchor_date)}
        </dd>
      </div>
      <div>
        <dt>적용기간</dt>
        <dd>
          {dateLabel(terms.effective_from)}부터{" "}
          {terms.effective_until ? `${dateLabel(terms.effective_until)} 전까지` : "계속"}
        </dd>
      </div>
      <div>
        <dt>예정 납부수단</dt>
        <dd>
          {terms.card_id ? (
            <NamedReference kind="cards" id={terms.card_id} suffix=" · 연결 카드 · 승인 계획" />
          ) : terms.account_id ? (
            <NamedReference
              kind="accounts"
              id={terms.account_id}
              suffix=" · 연결 계좌 · 직접 납부 계획"
            />
          ) : (
            "수단 연결 안 함"
          )}
        </dd>
      </div>
      {terms.loan_asset_id && (
        <div>
          <dt>연결 부채</dt>
          <dd>
            <NamedReference kind="assets" id={terms.loan_asset_id} suffix=" · 부채 항목 확인" />
          </dd>
        </div>
      )}
      {terms.currency_reference && (
        <div>
          <dt>외화 참고</dt>
          <dd>
            {terms.foreign_amount_reference} {terms.currency_reference} · 자동 환산 없음
          </dd>
        </div>
      )}
      {terms.note && (
        <div>
          <dt>메모</dt>
          <dd>{terms.note}</dd>
        </div>
      )}
    </dl>
  );
}
