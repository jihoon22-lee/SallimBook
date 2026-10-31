import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { Link, useSearchParams } from "react-router";
import { AmountField } from "../../shared/AmountField";
import { parseKrwInput } from "../../shared/krw";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { formatKrw } from "../assets/months/model";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { CashflowError } from "../finance/FinancialFeedback";
import { useHouseholdMembers } from "../finance/FinanceSupport";
import { todaySeoul } from "../finance/dates";
import { allPages, useResource } from "../finance/queries";
import { PaymentMethod, LiabilitySelect } from "./PaymentMethod";
import { useExpensePlanApi } from "./expensePlanApi";
import { ExpensePlanSummary } from "./ExpensePlanSummary";

type S = components["schemas"];
type Plan = S["PlanResponse"];
type Terms = S["PlanVersionResponse"];
export const treatments = {
  included: "월 계획 합계에 포함",
  external_support: "지원받는 항목·별도 표시",
  payroll: "급여 관련·별도 표시",
  reference_only: "참고용·별도 표시",
};
const economics = { expense: "소비 비용", loan: "대출 납입", asset_transfer: "저축·자산 이동" };
const money = (v: string | null | undefined) => (v == null ? "금액 미정" : formatKrw(v));
export function currentPlan(row: Plan, day = todaySeoul()): Terms | undefined {
  return row.versions.find(
    (v) => v.effective_from <= day && (!v.effective_until || v.effective_until > day),
  );
}
function termsOf(v?: Terms): S["PlanCreate"] {
  if (!v)
    return {
      title: "",
      category: "생활비",
      amount_mode: "variable",
      expected_amount_krw: null,
      economic_type: "expense",
      frequency: "monthly",
      interval_count: 1,
      tracking_mode: "plan_only",
      plan_kind: "recurring",
      budget_treatment: "included",
    };
  const {
    id: _id,
    effective_from: _from,
    effective_until: _until,
    reason: _reason,
    created_at: _created,
    revoked_at: _revoked,
    monthly_equivalent_krw: _monthly,
    ...terms
  } = v;
  return terms;
}
export function ExpensePlans({ method }: { method?: { kind: "card" | "account"; id: string } }) {
  const api = useExpensePlanApi();
  const methodKind = method?.kind;
  const methodId = method?.id;
  const members = useHouseholdMembers();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("all");
  const [sort, setSort] = useState("category");
  const [newPlan, setNewPlan] = useState(false);
  const data = useResource(
    useCallback(
      async () => ({
        rows: await allPages((cursor) =>
          api.rules({
            limit: 200,
            ...(cursor ? { cursor } : {}),
            ...(methodKind && methodId ? { [methodKind + "_id"]: methodId } : {}),
          }),
        ),
        summary: await api.summary(),
      }),
      [api, methodKind, methodId],
    ),
  );
  const rows = data.data?.rows ?? [];
  const selected = rows.find((row) => row.id === params.get("plan"));
  const visible = rows.filter((row) => {
    const v = currentPlan(row);
    return (
      !!v &&
      (v.title + " " + v.category).toLocaleLowerCase().includes(query.toLocaleLowerCase()) &&
      (group === "all" ||
        (group === "excluded" && v.budget_treatment !== "included") ||
        (group === "budget" && v.plan_kind === "budget") ||
        (group === "fixed" && v.plan_kind === "recurring" && v.budget_treatment === "included"))
    );
  });
  visible.sort((a, b) => {
    const av = currentPlan(a)!,
      bv = currentPlan(b)!;
    if (sort === "amount") {
      const x = BigInt(av.monthly_equivalent_krw ?? "-1"),
        y = BigInt(bv.monthly_equivalent_krw ?? "-1");
      if (x !== y) return x > y ? -1 : 1;
    }
    if (sort === "category") {
      const category = av.category.localeCompare(bv.category, "ko");
      if (category) return category;
    }
    return av.title.localeCompare(bv.title, "ko");
  });
  async function refresh() {
    setNewPlan(false);
    setParams(
      (old) => {
        old.delete("plan");
        return old;
      },
      { replace: true },
    );
    await data.reload();
  }
  return (
    <section className="expense-plans" aria-label={method ? "연결된 월 계획" : "월 지출 계획 관리"}>
      {method ? (
        <h3>연결된 월 계획</h3>
      ) : (
        data.data && !data.error && <ExpensePlanSummary data={data.data.summary} />
      )}
      <CashflowError error={data.error ?? members.error} />
      {data.loading && <p role="status">월 지출 계획을 불러오고 있어요.</p>}
      <button disabled={data.loading} onClick={() => void data.reload()}>
        월 계획 새로고침
      </button>
      {!method && (
        <button disabled={data.loading || !!data.error} onClick={() => setNewPlan(true)}>
          지출 계획 추가
        </button>
      )}
      {(newPlan || selected) && !data.error ? (
        <PlanEditor
          key={selected?.id ?? "new"}
          row={selected}
          onSaved={() => void refresh()}
          onCancel={() => {
            setNewPlan(false);
            setParams(
              (old) => {
                old.delete("plan");
                return old;
              },
              { replace: true },
            );
          }}
        />
      ) : (
        <>
          <div className="form-actions">
            <label>
              계획 검색
              <input value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <label>
              계획 보기
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                <option value="all">전체</option>
                <option value="fixed">고정 지출</option>
                <option value="budget">변동 예산</option>
                <option value="excluded">별도 표시</option>
              </select>
            </label>
            <label>
              정렬
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="category">분류순</option>
                <option value="name">이름순</option>
                <option value="amount">월 금액순</option>
              </select>
            </label>
          </div>
          {!data.loading && !data.error && (
            <ul className="record-list">
              {visible.map((row) => {
                const v = currentPlan(row)!;
                return (
                  <li key={row.id}>
                    <h3>
                      <button
                        className="link-button"
                        onClick={() =>
                          setParams((old) => {
                            old.set("plan", row.id);
                            return old;
                          })
                        }
                      >
                        {v.title}
                      </button>
                    </h3>
                    <p>
                      {v.category} · {v.plan_kind === "budget" ? "변동 예산" : "고정 지출"} ·{" "}
                      {economics[v.economic_type]}
                    </p>
                    <p>
                      월 {money(v.monthly_equivalent_krw)}
                      {v.frequency === "annual"
                        ? ` · ${v.interval_count}년마다 ${money(v.expected_amount_krw)}${v.annual_month ? ` (${v.annual_month}월)` : ""}`
                        : v.interval_count > 1 || v.frequency === "days"
                          ? ` · ${v.interval_count}${v.frequency === "days" ? "일" : "개월"}마다 ${money(v.expected_amount_krw)}`
                          : ""}
                    </p>
                    {v.currency_reference && (
                      <p>
                        외화 참고 {v.foreign_amount_reference} {v.currency_reference}
                      </p>
                    )}
                    {v.budget_treatment !== "included" && <p>{treatments[v.budget_treatment]}</p>}
                    {v.subject_member_id && (
                      <p>
                        관련 구성원:{" "}
                        {members.members.find((m) => m.member_id === v.subject_member_id)
                          ?.display_name ?? "구성원"}
                      </p>
                    )}
                    {v.card_id && <Link to={`/cards/${v.card_id}`}>납부 카드 보기</Link>}
                    {v.account_id && <Link to={`/accounts/${v.account_id}`}>납부 계좌 보기</Link>}
                    {v.note && (
                      <details>
                        <summary>메모</summary>
                        <p style={{ whiteSpace: "pre-wrap" }}>{v.note}</p>
                      </details>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {!data.loading && !data.error && !visible.length && <p>표시할 월 계획이 없어요.</p>}
          <details>
            <summary>종료·적용 예정 항목</summary>
            {rows
              .filter((r) => !currentPlan(r))
              .map((r) => (
                <p key={r.id}>
                  <button
                    onClick={() =>
                      setParams((old) => {
                        old.set("plan", r.id);
                        return old;
                      })
                    }
                  >
                    {r.history.at(-1)?.title ?? "계획"} · {r.ended_on ? "종료" : "적용 예정"}
                  </button>
                </p>
              ))}
          </details>
        </>
      )}
    </section>
  );
}
function PlanEditor({
  row: serverRow,
  onSaved,
  onCancel,
}: {
  row?: Plan;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const api = useExpensePlanApi();
  const members = useHouseholdMembers();
  // Keep the source revision with the draft; a background refresh must not rebase unsaved input.
  const [row] = useState(serverRow);
  const version = row && (currentPlan(row) ?? row.versions[0] ?? row.history.at(-1));
  const [draft, setDraft] = useState<S["PlanCreate"]>(() => termsOf(version));
  const [paymentKind, setPaymentKind] = useState<"none" | "card" | "account">(
    version?.card_id ? "card" : version?.account_id ? "account" : "none",
  );
  const [amount, setAmount] = useState(version?.expected_amount_krw ?? "");
  const [dirty, setDirty] = useState(false);
  const [validation, setValidation] = useState("");
  const [effective, setEffective] = useState(todaySeoul());
  const [action, setAction] = useState<"save" | "end" | "delete">("save");
  const guard = useUnsavedChangesGuard(dirty);
  const command = useMonthCommand();
  const key = useIdempotencyKey(
    JSON.stringify([row?.id, row?.version, draft, amount, effective, action]),
  );
  const ended = !!row?.ended_on && row.ended_on <= todaySeoul();
  function update(value: Partial<S["PlanCreate"]>) {
    setDraft((old) => ({ ...old, ...value }));
    setDirty(true);
    setValidation("");
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    const parsed = amount.trim() ? parseKrwInput(amount) : null;
    if (parsed && !parsed.ok) {
      setValidation("금액은 원 단위 숫자로 입력해 주세요.");
      return;
    }
    const input = {
      ...draft,
      expected_amount_krw: parsed?.ok ? parsed.krw : null,
      amount_mode: parsed?.ok ? draft.amount_mode : "variable",
      effective_from: effective,
    } satisfies S["PlanCreate"];
    const result = await command.run((signal) =>
      row
        ? api.changeRule(row.id, { ...input, reason: "월 계획 수정" }, row.version, key, signal)
        : api.createRule(input, key, signal),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      onSaved();
    }
  }
  async function finish() {
    if (!row) return;
    const result = await command.run((signal) =>
      action === "end"
        ? api.endRule(
            row.id,
            { effective_on: effective, reason: "월 계획 종료" },
            row.version,
            key,
            signal,
          )
        : api.deleteRule(row.id, row.version, key, signal),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      onSaved();
    }
  }
  return (
    <section className="card" aria-label="지출 계획 편집">
      <h3>{row ? "지출 계획 수정" : "지출 계획 추가"}</h3>
      <CashflowError error={command.error} />
      {validation && <p role="alert">{validation}</p>}
      <form onSubmit={(e) => void submit(e)}>
        <fieldset disabled={command.busy || ended}>
          <label>
            이름
            <input
              required
              maxLength={120}
              value={draft.title}
              onChange={(e) => update({ title: e.target.value })}
            />
          </label>
          <label>
            분류
            <input
              required
              maxLength={40}
              value={draft.category}
              onChange={(e) => update({ category: e.target.value })}
            />
          </label>
          <AmountField
            label={
              draft.frequency === "annual"
                ? "연 결제 금액 (미정이면 비워두기)"
                : "계획 금액 (미정이면 비워두기)"
            }
            value={amount}
            onChange={(v) => {
              setAmount(v);
              setDirty(true);
            }}
          />
          <label>
            계획 구분
            <select
              value={draft.plan_kind}
              onChange={(e) =>
                update(
                  e.target.value === "budget"
                    ? {
                        plan_kind: "budget",
                        frequency: "monthly",
                        interval_count: 1,
                        tracking_mode: "plan_only",
                        anchor_date: null,
                        annual_month: null,
                      }
                    : { plan_kind: "recurring" },
                )
              }
            >
              <option value="recurring">고정 지출</option>
              <option value="budget">변동 예산</option>
            </select>
          </label>
          <label>
            합계 처리
            <select
              value={draft.budget_treatment}
              onChange={(e) =>
                update({ budget_treatment: e.target.value as S["PlanCreate"]["budget_treatment"] })
              }
            >
              {Object.entries(treatments).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <details>
            <summary>결제수단·주기·관련 구성원·메모</summary>
            <PaymentMethod
              method={paymentKind}
              id={draft.card_id ?? draft.account_id ?? ""}
              onChange={(method, id) => {
                setPaymentKind(method);
                update({
                  card_id: method === "card" ? id || null : null,
                  account_id: method === "account" ? id || null : null,
                });
              }}
            />
            <label>
              관련 구성원
              <select
                value={draft.subject_member_id ?? ""}
                onChange={(e) => update({ subject_member_id: e.target.value || null })}
              >
                <option value="">공동·미지정</option>
                {members.members.map((m) => (
                  <option key={m.member_id} value={m.member_id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              경제적 성격
              <select
                value={draft.economic_type}
                onChange={(e) =>
                  update({
                    economic_type: e.target.value as S["PlanCreate"]["economic_type"],
                    loan_asset_id: null,
                  })
                }
              >
                {Object.entries(economics).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            {draft.economic_type === "loan" && (
              <LiabilitySelect
                value={draft.loan_asset_id ?? ""}
                onChange={(id) => update({ loan_asset_id: id || null })}
              />
            )}
            <label>
              주기
              <select
                disabled={draft.plan_kind === "budget"}
                value={draft.frequency}
                onChange={(e) =>
                  update({
                    frequency: e.target.value as S["PlanCreate"]["frequency"],
                    annual_month: null,
                  })
                }
              >
                <option value="monthly">월</option>
                <option value="annual">년</option>
                <option value="days">일</option>
              </select>
            </label>
            <label>
              주기 간격
              <input
                type="number"
                min={1}
                max={3650}
                disabled={draft.plan_kind === "budget"}
                value={draft.interval_count ?? 1}
                onChange={(e) => update({ interval_count: Number(e.target.value) })}
              />
            </label>
            {draft.frequency === "annual" && (
              <label>
                결제월 (선택)
                <select
                  value={draft.annual_month ?? ""}
                  onChange={(e) =>
                    update({ annual_month: e.target.value ? Number(e.target.value) : null })
                  }
                >
                  <option value="">미정</option>
                  {Array.from({ length: 12 }, (_, i) => (
                    <option key={i} value={i + 1}>
                      {i + 1}월
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              금액 성격
              <select
                value={draft.amount_mode}
                onChange={(e) => update({ amount_mode: e.target.value as "fixed" | "variable" })}
              >
                <option value="fixed">정해진 금액</option>
                <option value="variable">예상·변동 금액</option>
              </select>
            </label>
            <label>
              메모
              <textarea
                maxLength={2000}
                value={draft.note ?? ""}
                onChange={(e) => update({ note: e.target.value || null })}
              />
            </label>
          </details>
          <details>
            <summary>적용일·납부 일정 관리</summary>
            <label>
              이 계획 적용일
              <input
                type="date"
                required
                min={row ? todaySeoul() : undefined}
                value={effective}
                onChange={(e) => {
                  setEffective(e.target.value);
                  setDirty(true);
                }}
              />
            </label>
            <label>
              관리방식
              <select
                disabled={draft.plan_kind === "budget"}
                value={draft.tracking_mode}
                onChange={(e) =>
                  update({ tracking_mode: e.target.value as "scheduled" | "plan_only" })
                }
              >
                <option value="plan_only">월 계획만 보기</option>
                <option value="scheduled">납부 일정도 관리</option>
              </select>
            </label>
            {draft.tracking_mode === "scheduled" && (
              <label>
                납부 기준일
                <input
                  type="date"
                  required
                  value={draft.anchor_date ?? ""}
                  onChange={(e) =>
                    update({
                      anchor_date: e.target.value || null,
                      annual_month:
                        draft.frequency === "annual" && e.target.value
                          ? Number(e.target.value.slice(5, 7))
                          : null,
                    })
                  }
                />
              </label>
            )}
          </details>
          <button type="submit" onClick={() => setAction("save")}>
            계획 저장
          </button>
        </fieldset>
      </form>
      {row && (
        <>
          <details>
            <summary>변경 이력 {row.history.length}개</summary>
            {row.history.map((v) => (
              <p key={v.id}>
                {v.effective_from} · {money(v.expected_amount_krw)} ·{" "}
                {v.revoked_at
                  ? "정정됨"
                  : v.effective_until
                    ? `${v.effective_until} 전까지`
                    : "적용 중"}{" "}
                · {v.reason}
              </p>
            ))}
          </details>
          {!ended && (
            <button disabled={command.busy} onClick={() => setAction("end")}>
              계획 종료
            </button>
          )}
          <button disabled={command.busy} onClick={() => setAction("delete")}>
            계획 삭제
          </button>
          {action !== "save" && (
            <div>
              <p>
                {action === "end"
                  ? `${effective}부터 월 계획 합계에서 제외해요.`
                  : "이 계획을 삭제해요. 납부 이력이 있으면 종료만 할 수 있어요."}
              </p>
              <button disabled={command.busy} onClick={() => void finish()}>
                {action === "end" ? "종료하기" : "삭제하기"}
              </button>
              <button disabled={command.busy} onClick={() => setAction("save")}>
                취소
              </button>
            </div>
          )}
        </>
      )}
      <button disabled={command.busy} onClick={onCancel}>
        닫기
      </button>
    </section>
  );
}
