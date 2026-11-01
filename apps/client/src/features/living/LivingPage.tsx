import { Link } from "react-router";
import { AuthenticatedFinance } from "../finance/FinancialFeedback";
import { HomeSecondary } from "../dashboard/HomeSecondary";
import { MonthPicker } from "../../shared/MonthContext";
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
            월 지출 계획
          </Link>
          <Link className="button-link secondary-button" to="/cards">
            카드 관리
          </Link>
        </div>
      }
    >
      <MonthPicker />
      <HomeSecondary />
      <p className="muted">
        등록하지 않은 거래와 변동 소비는 포함하지 않아요. 수입과 고정 납부의 차이를 저축액이나 전체
        월 지출로 계산하지 않아요.
      </p>
    </AuthenticatedFinance>
  );
}
