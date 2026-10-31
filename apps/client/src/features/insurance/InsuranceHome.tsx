import { InsuranceOverview } from "../dashboard/HouseholdOverview";
import { Link } from "react-router";
import { InsurancePage } from "./InsuranceSupport";
export function InsuranceHome() {
  const navigation = (
    <div className="form-actions">
      <Link className="button-link secondary-button" to="/settings/people">
        가족 관리
      </Link>
      <Link className="button-link" to="/insurance/policies">
        보험 계약
      </Link>
      <Link className="button-link" to="/insurance/cases">
        보험 사건
      </Link>
      <Link className="button-link" to="/insurance/claims">
        전체 청구 작업 목록
      </Link>
      <Link className="button-link" to="/insurance/payouts">
        수령 원본 목록
      </Link>
      <Link className="button-link" to="/insurance/payouts/new">
        보험금 수령 입력
      </Link>
    </div>
  );
  return (
    <InsurancePage
      title="보험"
      description="계약과 독립 사건, 실제 의료비·청구·수령을 함께 기록해요."
      navigation={navigation}
    >
      <InsuranceOverview />
      <details className="card">
        <summary>보험 기록 도움말</summary>
        <ol>
          <li>계약·보장과 보험료 납부 규칙을 연결해요.</li>
          <li>사건과 진료·처방·약국을 기록해요.</li>
          <li>실제 비용을 한 번 기록하고 여러 청구의 근거로 연결해요.</li>
          <li>실제 보험금 입금을 사건별로 배분하고 환불·반환을 별도 기록해요.</li>
        </ol>
        <p>청구가 없어도 실제 수령부터 기록할 수 있어요. 치료 종료와 정산 종료는 각각 확인해요.</p>
      </details>
    </InsurancePage>
  );
}
