import { Link } from "react-router";
import { formatMonth, MonthPicker, useMonth } from "../../shared/MonthContext";
import { RelatedLinks } from "../../shared/PlannedPage";

export function Dashboard() {
  const { month } = useMonth();
  return (
    <>
      <div className="intro">
        <p className="eyebrow">우리 집의 기록</p>
        <h1>함께 살피는 오늘의 살림</h1>
        <p>월별 자산부터 생활 속 작은 물건까지, 한곳에서 차근차근.</p>
      </div>
      <MonthPicker />
      <div className="dashboard-grid">
        <section className="card" aria-labelledby="assets-title">
          <p className="eyebrow">월간 기록 · {formatMonth(month)}</p>
          <h2 id="assets-title">자산의 변화</h2>
          <p className="empty-value" aria-label="입력한 자산 기록 없음">—</p>
          <p>아직 자산 기록이 연결되지 않았어요.</p>
          <p className="muted">월별 잔액과 평가액을 기록하면 변화를 함께 살펴볼 수 있어요. 기록 기능을 준비하고 있어요.</p>
          <Link className="button-link" to="/assets">자산 관리 둘러보기</Link>
        </section>
        <section className="card" aria-labelledby="consumables-title">
          <p className="eyebrow">오늘 기준</p>
          <h2 id="consumables-title">살펴볼 소모품</h2>
          <p className="empty-value" aria-label="등록한 소모품 없음">—</p>
          <p>아직 소모품 기록이 연결되지 않았어요.</p>
          <p className="muted">필터와 생활용품의 재고, 교체 기록을 함께 관리할 수 있어요. 과거 월을 골라도 소모품은 오늘 기준이에요.</p>
          <Link className="button-link" to="/consumables">소모품 관리 둘러보기</Link>
        </section>
      </div>
      <div className="secondary-summary" aria-label="다른 기록 살펴보기">
        <RelatedLinks links={[
          { to: "/income", label: "이번 달 수입", description: "등록 기준 · 준비 중" },
          { to: "/fixed-payments", label: "등록된 고정 납부", description: "등록 기준 · 준비 중" },
          { to: "/insurance/cases", label: "진행 보험 사건", description: "치료·청구·지급 · 준비 중" },
        ]} />
      </div>
    </>
  );
}
