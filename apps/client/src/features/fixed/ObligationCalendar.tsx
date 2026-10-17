import { useCallback } from "react";
import { Link } from "react-router";
import { formatMonth } from "../../shared/MonthContext";
import { formatKrw, monthEnd } from "../assets/months/model";
import { CashflowError } from "../finance/FinancialFeedback";
import { allPages, useResource } from "../finance/queries";
import { useFixedApi } from "./api";
import { obligationStates } from "./model";

const weekdays = ["일", "월", "화", "수", "목", "금", "토"];
export function ObligationCalendar({ month, refresh }: { month: string; refresh: number }) {
  const api = useFixedApi();
  const resource = useResource(useCallback(() => allPages((cursor) => api.obligations({ month, limit: 200, ...(cursor ? { cursor } : {}) })), [api, month, refresh]));
  const firstWeekday = new Date(`${month}-01T00:00:00Z`).getUTCDay();
  const days = Number(monthEnd(month).slice(-2));
  return <section className="card" aria-label="월 납부 달력"><h2>{formatMonth(month)} 예정일 달력</h2>
    <p>생성된 회차의 예정일 기준이에요. 각 회차의 실제 납부 합계는 납부일과 관계없이 표시하며, 선택 월의 실제 지출은 위 월 요약에서 확인해요.</p>
    <CashflowError error={resource.error} />{resource.error && <button onClick={() => void resource.reload()}>납부 달력 다시 확인</button>}
    {resource.loading && <p role="status">이 달의 전체 회차를 확인하고 있어요.</p>}
    {resource.data && !resource.loading && !resource.error && <>
      <p>이 달의 생성된 회차 {resource.data.length}개</p>
      <div className="payment-calendar-weekdays" aria-hidden="true">{weekdays.map((day) => <span key={day}>{day}</span>)}</div>
      <ol className="payment-calendar">
        {Array.from({ length: firstWeekday }, (_, index) => <li className="payment-calendar-padding" aria-hidden="true" key={`padding-${index}`} />)}
        {Array.from({ length: days }, (_, index) => {
          const date = `${month}-${String(index + 1).padStart(2, "0")}`;
          const rows = resource.data!.filter((row) => row.scheduled_date === date);
          return <li key={date} aria-label={`${date} 예정`}><time dateTime={date}>{index + 1}일 <span className="payment-calendar-weekday">{weekdays[(firstWeekday + index) % 7]}요일</span></time>
            {rows.length ? <ul>{rows.map((row) => <li key={row.id}><Link to={`/fixed-payments/${row.id}`}>{row.title}</Link><span>{obligationStates[row.status]}{row.manual_override ? " · 수동 예외" : ""}</span><span>예정 {row.expected_amount_krw === null ? "미정" : formatKrw(row.expected_amount_krw)}</span><span>실제 {formatKrw(row.actual_amount_krw)}</span></li>)}</ul> : <span className="muted">등록 회차 없음</span>}
          </li>;
        })}
      </ol>
    </>}
  </section>;
}
