import { Link, useParams } from "react-router";
import { formatMonth, isValidMonth, MonthPicker, useMonth } from "./MonthContext";
import type { PlannedScreen, ScreenLink } from "./screens";

export function RelatedLinks({ links }: { links: ScreenLink[] }) {
  return (
    <ul className="related-links">
      {links.map((link) => <li key={link.to}>
        <Link to={link.to}><span><strong>{link.label}</strong>{link.description && <small>{link.description}</small>}</span><span aria-hidden="true">↗</span></Link>
      </li>)}
    </ul>
  );
}

export function PlannedPage({ screen }: { screen: PlannedScreen }) {
  const params = useParams();
  const { month } = useMonth();
  if (screen.id === "UI-06" && (!params.month || !isValidMonth(params.month))) {
    return <><div className="intro"><h1>월을 확인해 주세요</h1><p>올바른 연도와 월로 이동해 주세요.</p></div><Link className="button-link" to="/assets">자산 목록으로</Link></>;
  }
  return (
    <>
      <div className="intro"><p className="eyebrow">우리 집의 기록</p><h1>{screen.title}</h1><p>{screen.description}</p></div>
      {screen.monthly && <MonthPicker />}
      {screen.id === "UI-06" && <p className="month-caption">{formatMonth(params.month!)} · 서울 기준</p>}
      {screen.links && <RelatedLinks links={screen.links} />}
      {screen.id === "UI-04" && <Link className="button-link month-action" to={`/assets/months/${month}`}>{formatMonth(month)} 확인 안내</Link>}
      <section className="card planned-state" aria-labelledby="planned-title">
        <span className="status-chip">준비 중</span>
        <h2 id="planned-title">기록 기능을 준비하고 있어요</h2>
        <p>{screen.upcoming}</p>
        <p className="muted">현재는 화면을 둘러볼 수 있으며, 데이터를 조회하거나 저장하지 않아요.</p>
      </section>
    </>
  );
}
