export function Dashboard() {
  return (
    <main className="page">
      <header className="brand">
        <span className="brand-mark" aria-hidden="true">
          살림
        </span>
        <span>SallimBook</span>
      </header>
      <div className="intro">
        <p className="eyebrow">우리 집의 기록</p>
        <h1>함께 살피는 오늘의 살림</h1>
        <p>월별 자산부터 생활 속 작은 물건까지, 한곳에서 차근차근.</p>
      </div>
      <div className="dashboard-grid">
        <section className="card" aria-labelledby="assets-title">
          <p className="eyebrow">월간 기록</p>
          <h2 id="assets-title">자산의 변화</h2>
          <p className="empty-value" aria-label="입력한 자산 기록 없음">
            —
          </p>
          <p>아직 확인한 자산 기록이 없어요.</p>
          <p className="muted">
            월별 잔액과 평가액을 기록하면 변화를 함께 살펴볼 수 있어요.
          </p>
        </section>
        <section className="card" aria-labelledby="consumables-title">
          <p className="eyebrow">오늘 기준</p>
          <h2 id="consumables-title">살펴볼 소모품</h2>
          <p className="empty-value" aria-label="등록한 소모품 없음">
            —
          </p>
          <p>아직 등록한 소모품이 없어요.</p>
          <p className="muted">
            필터와 생활용품의 재고, 교체 기록을 함께 관리할 수 있어요.
          </p>
        </section>
      </div>
      <footer>살림북 · 함께 쌓아가는 우리 집의 기록</footer>
    </main>
  );
}
