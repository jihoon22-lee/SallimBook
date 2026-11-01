import { Link } from "react-router";
import { AuthenticatedFinance } from "../finance/FinancialFeedback";
import { HomeSecondary } from "../dashboard/HomeSecondary";
import { useHouseholdOverview } from "../dashboard/overviewApi";
import { MonthPicker, useMonth } from "../../shared/MonthContext";
import { RetryScope, useRetryReport } from "../../shared/RetryFailed";

function LivingSummary() {
  const { month } = useMonth();
  const overview = useHouseholdOverview(month);
  const quiet = useRetryReport("household-overview", overview.error, overview.reload);
  return <HomeSecondary overview={overview} overviewQuiet={quiet} />;
}

export function LivingPage() {
  return (
    <AuthenticatedFinance
      title="생활비"
      description="예상 월 수입과 지출 계획을 한눈에 살펴요."
      navigation={
        <div className="form-actions">
          <Link className="button-link" to="/income">
            월간 수입
          </Link>
          <Link className="button-link secondary-button" to="/fixed-payments">
            고정 지출
          </Link>
          <Link className="button-link secondary-button" to="/cards">
            카드 관리
          </Link>
        </div>
      }
    >
      <MonthPicker />
      <RetryScope label="생활비 다시 불러오기">
        <LivingSummary />
      </RetryScope>
      <p className="muted">
        월 계획 기준 여유는 등록한 예상 수입과 월 계획으로 계산한 추정이에요. 등록하지 않은 거래와
        변동 소비는 포함하지 않고, 실제 잔액이나 저축액으로 보지 않아요.
      </p>
    </AuthenticatedFinance>
  );
}
