import { useAuth } from "../auth/AuthProvider";
import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { Link } from "react-router";
import { AmountField } from "../../shared/AmountField";
import { parseKrwInput } from "../../shared/krw";
import { formatKrw } from "../assets/months/model";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { AuthenticatedFinance, CashflowError } from "../finance/FinancialFeedback";
import { useHouseholdMembers } from "../finance/FinanceSupport";
import { allPages, useResource } from "../finance/queries";
import { usePlanningApi } from "./planningApi";

type S = components["schemas"];
type Expected = S["ExpectedResponse"];
type Bonus = S["BonusResponse"];
const kinds = { tai_h1: "TAI 상반기", tai_h2: "TAI 하반기", opi: "OPI" };
const money = (value: string | null | undefined) => (value == null ? "미확인" : formatKrw(value));
function parse(value: string) {
  if (!value.trim()) return null;
  const parsed = parseKrwInput(value);
  return parsed.ok ? parsed.krw : undefined;
}
function IncomePlanning() {
  const api = usePlanningApi();
  const members = useHouseholdMembers();
  const data = useResource(
    useCallback(
      async () => ({
        expected: await allPages(api.expected),
        bonuses: await allPages(api.bonuses),
      }),
      [api],
    ),
  );
  const [editor, setEditor] = useState<
    { kind: "expected"; row?: Expected } | { kind: "bonus"; row?: Bonus } | null
  >(null);
  const name = (id: string) =>
    members.members.find((m) => m.member_id === id)?.display_name ?? "구성원";
  const expected = data.data?.expected ?? [];
  const bonuses = data.data?.bonuses ?? [];
  const active = expected.filter((r) => r.active);
  const years = [...new Set(bonuses.map((r) => r.performance_year))].sort((a, b) => b - a);
  async function refresh() {
    setEditor(null);
    await data.reload();
  }
  return (
    <>
      <p>
        <Link to="/income">월별 실제 수입 보기</Link>
      </p>
      <CashflowError error={data.error ?? members.error} />
      {data.loading && <p role="status">수입 기준을 확인하고 있어요.</p>}
      <button type="button" disabled={data.loading} onClick={() => void refresh()}>
        최신 수입 기준 다시 확인
      </button>
      {editor ? (
        <PlanningEditor
          key={editor.row?.id ?? editor.kind}
          kind={editor.kind}
          source={editor.row}
          members={members.members}
          onSaved={() => void refresh()}
          onCancel={() => setEditor(null)}
        />
      ) : (
        <>
          <section className="card">
            <h2>현재 예상 월 수입</h2>
            <p>
              실제 입금 기록과 별도로 관리해요. 이 금액으로 과거 월 수입이나 자산 잔액을 자동
              변경하지 않아요.
            </p>
            {!data.error && data.data && (
              <p>
                확인된 예상 합계{" "}
                {money(active.reduce((sum, r) => sum + BigInt(r.amount_krw ?? "0"), 0n).toString())}{" "}
                · 미확인 {active.filter((r) => r.amount_krw == null).length}건
              </p>
            )}
            <button
              type="button"
              disabled={!!data.error || data.loading}
              onClick={() => setEditor({ kind: "expected" })}
            >
              예상 수입 추가
            </button>
            <ul className="record-list">
              {expected.map((r) => (
                <li key={r.id}>
                  <h3>
                    {name(r.member_id)} · {r.label}
                  </h3>
                  <p>
                    {money(r.amount_krw)} / 월 · {r.active ? "사용 중" : "종료"}
                  </p>
                  {r.note && <p>{r.note}</p>}
                  <button onClick={() => setEditor({ kind: "expected", row: r })}>
                    예상 수입 수정
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <section className="card">
            <h2>성과연도별 상여</h2>
            <p>
              세전 금액, 세후 현금과 수령 당시 주식 평가액을 나누어 보존해요. 주식 금액은 현재
              평가액이 아니에요.
            </p>
            <button
              type="button"
              disabled={!!data.error || data.loading}
              onClick={() => setEditor({ kind: "bonus" })}
            >
              상여 상세 추가
            </button>
            {years.map((year) => {
              const rows = bonuses
                .filter((r) => r.performance_year === year)
                .sort((a, b) => a.award_kind.localeCompare(b.award_kind));
              const current = rows.filter((r) => r.active);
              const sum = (field: "net_cash_krw" | "stock_grant_value_krw") =>
                current.reduce((n, r) => n + BigInt(r[field] ?? "0"), 0n);
              return (
                <section key={year} aria-label={`${year}년 성과 상여`}>
                  <h3>{year}년 성과</h3>
                  <p>
                    확인된 세후 현금 {money(sum("net_cash_krw").toString())} · 주식 수령가액{" "}
                    {money(sum("stock_grant_value_krw").toString())} · 합계{" "}
                    {money((sum("net_cash_krw") + sum("stock_grant_value_krw")).toString())}
                  </p>
                  <p>
                    현금 미확인 {current.filter((r) => r.net_cash_krw == null).length}건 · 주식
                    미확인 {current.filter((r) => r.stock_grant_value_krw == null).length}건
                  </p>
                  <ul className="record-list">
                    {rows.map((r) => (
                      <li key={r.id}>
                        <h4>
                          {name(r.member_id)} · {kinds[r.award_kind]}
                        </h4>
                        <dl className="metadata-grid">
                          <div>
                            <dt>지급월</dt>
                            <dd>
                              {r.payment_month ?? "미확인"} ·{" "}
                              {r.received ? "수령 확인" : "수령 미확인"}
                            </dd>
                          </div>
                          <div>
                            <dt>세전</dt>
                            <dd>{money(r.gross_krw)}</dd>
                          </div>
                          <div>
                            <dt>세후 현금</dt>
                            <dd>{money(r.net_cash_krw)}</dd>
                          </div>
                          <div>
                            <dt>수령 당시 주식 평가액</dt>
                            <dd>{money(r.stock_grant_value_krw)}</dd>
                          </div>
                          <div>
                            <dt>지급률</dt>
                            <dd>
                              {r.payout_rate_percent == null
                                ? "미확인"
                                : `${r.payout_rate_percent}%`}
                            </dd>
                          </div>
                        </dl>
                        {!r.active && <p>무효 처리됨</p>}
                        {r.note && <p>{r.note}</p>}
                        {r.cash_record_id && (
                          <p>
                            <Link to={`/income/${r.cash_record_id}`}>
                              지급월에 연결된 실제 현금 수입
                            </Link>
                          </p>
                        )}
                        <button onClick={() => setEditor({ kind: "bonus", row: r })}>
                          상여 상세 수정
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </section>
        </>
      )}
    </>
  );
}
function PlanningEditor({
  kind,
  source,
  members,
  onSaved,
  onCancel,
}: {
  kind: "expected" | "bonus";
  source?: Expected | Bonus;
  members: ReturnType<typeof useHouseholdMembers>["members"];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const api = usePlanningApi(),
    command = useMonthCommand();
  const expected = source && "label" in source ? source : undefined,
    bonus = source && "award_kind" in source ? source : undefined;
  const { state: auth } = useAuth();
  const [member, setMember] = useState(
    source?.member_id ?? (auth.status === "authenticated" ? auth.member.member_id : ""),
  );
  const [label, setLabel] = useState(expected?.label ?? "");
  const [amount, setAmount] = useState(expected?.amount_krw ?? "");
  const [year, setYear] = useState(bonus?.performance_year.toString() ?? "");
  const [award, setAward] = useState<S["BonusInput"]["award_kind"]>(bonus?.award_kind ?? "tai_h1");
  const [month, setMonth] = useState(bonus?.payment_month ?? "");
  const [gross, setGross] = useState(bonus?.gross_krw ?? ""),
    [cash, setCash] = useState(bonus?.net_cash_krw ?? ""),
    [stock, setStock] = useState(bonus?.stock_grant_value_krw ?? "");
  const [rate, setRate] = useState(bonus?.payout_rate_percent ?? "");
  const [received, setReceived] = useState(bonus?.received ?? false),
    [active, setActive] = useState(source?.active ?? true);
  const [note, setNote] = useState(source?.note ?? ""),
    [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const fingerprint = JSON.stringify([
    source?.id,
    source?.version,
    member,
    label,
    amount,
    year,
    award,
    month,
    gross,
    cash,
    stock,
    rate,
    received,
    active,
    note,
    reason,
  ]);
  const key = useIdempotencyKey(fingerprint);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const common = { member_id: member, active, note: note.trim() || null };
    if (
      !member ||
      (source && (kind === "bonus" || !active) && !reason.trim()) ||
      (kind === "expected"
        ? !label.trim() || parse(amount) === undefined
        : !/^[0-9]{4}$/.test(year) ||
          Number(year) < 1900 ||
          Number(year) > 9998 ||
          [gross, cash, stock].some((v) => parse(v) === undefined) ||
          (rate && !/^(0|[1-9][0-9]{0,4})(\.[0-9]{1,2})?$/.test(rate)) ||
          (received && (!month || !cash.trim())))
    ) {
      setError("구성원·금액·연도와 정정 사유를 확인해 주세요. 미입력과 0원은 달라요.");
      return;
    }
    setError("");
    const result = await command.run<Expected | Bonus>((signal) =>
      kind === "expected"
        ? api.saveExpected(
            { ...common, label: label.trim(), amount_krw: parse(amount) ?? null },
            expected,
            reason.trim() || "예상 월 수입 수정",
            key,
            signal,
          )
        : api.saveBonus(
            {
              ...common,
              performance_year: Number(year),
              award_kind: award,
              payment_month: month || null,
              gross_krw: parse(gross) ?? null,
              net_cash_krw: parse(cash) ?? null,
              stock_grant_value_krw: parse(stock) ?? null,
              payout_rate_percent: rate || null,
              received,
            },
            bonus,
            reason.trim(),
            key,
            signal,
          ),
    );
    if (result.ok && command.mounted.current) onSaved();
  }
  return (
    <section className="card">
      <h2>{kind === "expected" ? "예상 월 수입 입력" : "성과연도 상여 입력"}</h2>
      <form onSubmit={(e) => void submit(e)}>
        <fieldset disabled={command.busy}>
          <legend>입력 내용</legend>
          <label>
            구성원
            <select
              aria-label="구성원"
              value={member}
              onChange={(e) => setMember(e.target.value)}
              required
            >
              <option value="">선택해 주세요</option>
              {members.map((m) => (
                <option key={m.member_id} value={m.member_id}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </label>
          {kind === "expected" ? (
            <>
              <label>
                수입 항목
                <input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  maxLength={120}
                  required
                />
              </label>
              <AmountField
                label="예상 월 금액"
                value={amount}
                onChange={setAmount}
                hint="비워두면 미확인, 0은 0원이에요."
              />
            </>
          ) : (
            <>
              <label>
                성과연도
                <input
                  inputMode="numeric"
                  value={year}
                  onChange={(e) => setYear(e.target.value)}
                  maxLength={4}
                  required
                />
              </label>
              <label>
                상여 구분
                <select
                  aria-label="상여 구분"
                  value={award}
                  onChange={(e) => setAward(e.target.value as typeof award)}
                >
                  {Object.entries(kinds).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                실제 지급월
                <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
              </label>
              <p>
                TAI 상반기는 성과연도 7월, 하반기는 12월, OPI는 다음 해 1월을 기준으로 원본의
                지급월을 확인해 입력해 주세요.
              </p>
              <AmountField label="세전 금액" value={gross} onChange={setGross} />
              <AmountField label="세후 현금" value={cash} onChange={setCash} />
              <AmountField
                label="수령 당시 주식 평가액"
                value={stock}
                onChange={setStock}
                hint="현재 주가 평가액을 넣지 않아요. 비워두면 미확인, 0은 주식 수령액 0원이에요."
              />
              <label>
                지급률 (%)
                <input
                  inputMode="decimal"
                  value={rate}
                  onChange={(e) => setRate(e.target.value)}
                  maxLength={8}
                />
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={received}
                  onChange={(e) => setReceived(e.target.checked)}
                />
                실제 수령을 확인했으며, 양수 세후 현금을 지급월 수입에 연결할게요
              </label>
            </>
          )}
          <label className="checkbox-field">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            현재 유효한 기록
          </label>
          <p>
            해제하면 예상 합계에서 제외하고, 상여에 연결된 현금 수입은 사유를 남겨 무효 처리해요.
          </p>
          <label>
            메모
            <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
          </label>
          {source && (
            <label>
              {kind === "expected" && active ? "변경 메모 (선택)" : "정정 사유"}
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                required={kind !== "expected" || !active}
                maxLength={500}
              />
            </label>
          )}
          {error && <p role="alert">{error}</p>}
          <CashflowError error={command.error} />
          {command.error?.status === 409 && (
            <p>
              내용이 변경되었거나 연결된 기록을 확인해야 해요. 닫은 뒤 최신 수입 기준을 다시 확인해
              주세요.
            </p>
          )}
          <button type="submit" disabled={command.busy || command.error?.status === 409}>
            저장
          </button>
          <button type="button" onClick={onCancel}>
            닫기
          </button>
        </fieldset>
      </form>
    </section>
  );
}
export function IncomePlanningPage() {
  return (
    <AuthenticatedFinance
      title="예상 수입·성과연도 상여"
      description="예상 기준과 실제 지급 내역을 구분해 관리해요."
    >
      <IncomePlanning />
    </AuthenticatedFinance>
  );
}
