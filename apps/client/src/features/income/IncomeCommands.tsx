import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";
import { toApiError } from "../../platform/api";
import { isValidMonth, useMonth } from "../../shared/MonthContext";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { formatKrw, parseKrw } from "../assets/months/model";
import { AccountSelect } from "../finance/AccountChoices";
import { CashflowError, SaveControls } from "../finance/FinancialFeedback";
import { isDateOnly, todaySeoul } from "../finance/dates";
import type { Income, IncomeReturn } from "./model";
import { useIncomeApi } from "./api";
export function IncomeCommand({ initial, action, onSaved }: { initial: Income; action: "void" | "return"; onSaved: () => void }) {
  const api = useIncomeApi(); const navigate = useNavigate(); const { month } = useMonth(); const command = useMonthCommand();
  const [source, setSource] = useState(initial); const [latest, setLatest] = useState<Income | null>(null); const [reason, setReason] = useState(""); const [amount, setAmount] = useState(""); const [period, setPeriod] = useState(month); const [precision, setPrecision] = useState<"day" | "month">("day"); const [date, setDate] = useState(""); const [account, setAccount] = useState(""); const [note, setNote] = useState("");
  const parsed = parseKrw(amount); const valid = !!reason.trim() && reason.trim().length <= 500 && (action === "void" || !!parsed && parsed !== "0" && BigInt(parsed) <= BigInt(source.amount_krw) && isValidMonth(period) && (precision === "month" || isDateOnly(date) && date <= todaySeoul()));
  const body: IncomeReturn = { amount_krw: parsed ?? "", period_month: period, date_precision: precision, occurred_on: precision === "day" ? date : null, account_id: account || null, note: note.trim() || null, reason: reason.trim() };
  const payload = action === "void" ? { reason: reason.trim() } : body; const key = useIdempotencyKey(JSON.stringify([source.id, source.version, action, payload]));
  async function submit(event: FormEvent) { event.preventDefault(); if (!valid) return;
    const result = await command.run((signal) => action === "void" ? api.void(source.id, { reason: reason.trim() }, source.version, key, signal) : api.return(source.id, body, source.version, key, signal));
    if (result.ok && command.mounted.current) { if (action === "return") navigate(`/income/${result.value.id}`); else onSaved(); }
  }
  async function compare() { try { const current = await api.get(source.id); if (command.mounted.current) setLatest(current); } catch (error) { command.setError(toApiError(error)); } }
  return <section className="card"><h2>{action === "void" ? "사유를 남기고 무효 처리" : "원본에 연결된 반환 기록"}</h2><p>원본 {formatKrw(source.amount_krw)} · 버전 {source.version}. 원본과 이력을 보존해요.</p><form onSubmit={(event) => void submit(event)}><fieldset disabled={command.busy}><legend>{action === "void" ? "무효 사유 확인" : "실제로 반환한 내용"}</legend>
    {action === "return" && <><p>구성원은 원본에서 이어받아요. 기존 반환을 포함한 합계는 원본 금액을 넘을 수 없어요.</p><div className="form-grid">
      <div className="form-field"><label>반환 금액 (원)<input type="text" inputMode="numeric" pattern="[0-9]+" maxLength={20} value={amount} onChange={(event) => setAmount(event.target.value)} required /></label></div>
      <div className="form-field"><label>반환 귀속월<input type="month" value={period} onChange={(event) => setPeriod(event.target.value)} required /></label></div>
      <div className="form-field"><label>반환 날짜 정밀도<select value={precision} onChange={(event) => setPrecision(event.target.value as "day" | "month")}><option value="day">실제 반환일</option><option value="month">월합계 · 날짜 미지정</option></select></label></div>
      {precision === "day" && <div className="form-field"><label>실제 반환일<input type="date" value={date} max={todaySeoul()} onChange={(event) => setDate(event.target.value)} required /></label></div>}
      <AccountSelect label="반환 계좌" value={account} onChange={setAccount} /><div className="form-field"><label>반환 메모<textarea maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} /></label></div>
    </div></>}
    <div className="form-field"><label>{action === "void" ? "무효 사유" : "반환 사유"}<textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} required /></label></div></fieldset>
    <CashflowError error={command.error} />{command.error?.status === 409 && <button type="button" disabled={command.busy} onClick={() => void compare()}>현재 원본과 비교</button>}
    {latest && <section className="review-panel"><h3>현재 원본 확인</h3><p>{formatKrw(latest.amount_krw)} · {latest.state === "active" ? "활성" : "무효"} · 버전 {latest.version}</p><button type="button" disabled={action === "void" ? !latest.voidable : latest.state !== "active"} onClick={() => { setSource(latest); setLatest(null); command.setError(null); }}>현재 원본을 확인하고 계속</button></section>}
    <SaveControls busy={command.busy} cancel={command.cancel} disabled={!valid || source.state !== "active" || action === "void" && !source.voidable} label={action === "void" ? "사유와 함께 무효 처리" : "반환 기록 저장"} />
  </form></section>;
}
