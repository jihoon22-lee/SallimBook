import { Link } from "react-router";
import { AuthenticatedFinance } from "../finance/FinancialFeedback";
import { IncomeSummaryPanel } from "../income/IncomePages";
import { FixedSummaryPanel } from "../fixed/FixedPages";
import { MonthPicker } from "../../shared/MonthContext";
export function LivingPage() {
  return <AuthenticatedFinance title="생활비" description="직접 기록한 수입과 고정 납부를 함께 살펴요."><MonthPicker /><div className="form-actions"><Link className="button-link" to="/income">월간 수입</Link><Link className="button-link secondary-button" to="/fixed-payments">고정 납부</Link><Link className="button-link secondary-button" to="/cards">카드 관리</Link></div><IncomeSummaryPanel /><FixedSummaryPanel /><p className="muted">등록하지 않은 거래와 변동 소비는 포함하지 않아요. 수입과 고정 납부의 차이를 저축액이나 전체 월 지출로 계산하지 않아요.</p></AuthenticatedFinance>;
}
