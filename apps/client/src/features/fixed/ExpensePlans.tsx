import { useCallback, useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { AmountField } from "../../shared/AmountField";
import { parseKrwInput } from "../../shared/krw";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { formatKrw } from "../assets/months/model";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { CashflowError, SaveControls } from "../finance/FinancialFeedback";
import { useHouseholdMembers } from "../finance/FinanceSupport";
import { dateLabel, todaySeoul } from "../finance/dates";
import { allPages, useResource } from "../finance/queries";
import { useAccountsApi } from "../accounts/api";
import { useCardsApi } from "../cards/api";
import { PaymentMethod, LiabilitySelect } from "./PaymentMethod";
import { useExpensePlanApi } from "./expensePlanApi";
import { useFixedApi } from "./api";
import { economicTypes, paymentMethodChanges, preparationWindow } from "./model";
import { ExpensePlanSummary } from "./ExpensePlanSummary";
import { PlanInsuranceLink } from "./insuranceLink";

type S = components["schemas"];
type Plan = S["PlanResponse"];
type Terms = S["PlanVersionResponse"];
export const treatments = {
  included: "월 계획 합계에 포함",
  external_support: "지원받는 항목·별도 표시",
  payroll: "급여 관련·별도 표시",
  reference_only: "참고용·별도 표시",
};
const groups = ["all", "fixed", "budget", "excluded"] as const;
const sorts = ["category", "name", "amount"] as const;
const suggestedCategories = ["생활비", "구독", "보험료", "통신비", "대출", "연금", "저축"];
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
type EditorState = { planEditor?: boolean } | null;

const filterDefaults = { q: "", group: "all", sort: "category" };
type FilterName = keyof typeof filterDefaults;
const filterNames = Object.keys(filterDefaults) as FilterName[];
/**
 * Filters are mirrored into the URL (replace, not push) so a visit to a linked card or account
 * comes back to the same list. Local state stays the source while typing, so a router
 * transition never rewinds the search box, and every mirror write carries all filters so a
 * quick second change cannot drop the first.
 */
function useListFilters(embedded: boolean) {
  const [params, setParams] = useSearchParams();
  const [values, setValues] = useState(() => {
    const read = (name: FilterName) => (!embedded && params.get(name)) || filterDefaults[name];
    return { q: read("q"), group: read("group"), sort: read("sort") };
  });
  useEffect(() => {
    if (embedded) return;
    if (filterNames.every((name) => (params.get(name) ?? filterDefaults[name]) === values[name]))
      return;
    setParams(
      (old) => {
        for (const name of filterNames)
          if (values[name] !== filterDefaults[name]) old.set(name, values[name]);
          else old.delete(name);
        return old;
      },
      { replace: true, preventScrollReset: true },
    );
  }, [embedded, params, setParams, values]);
  return {
    q: values.q,
    group: (groups as readonly string[]).includes(values.group) ? values.group : "all",
    sort: (sorts as readonly string[]).includes(values.sort) ? values.sort : "category",
    set: (name: FilterName, value: string) => setValues((old) => ({ ...old, [name]: value })),
  };
}

export function ExpensePlans({ method }: { method?: { kind: "card" | "account"; id: string } }) {
  const api = useExpensePlanApi();
  const accountApi = useAccountsApi();
  const cardApi = useCardsApi();
  const navigate = useNavigate();
  const location = useLocation();
  // One paginated metadata read per kind, never a per-row lookup or vault request.
  const methods = useResource(
    useCallback(async () => {
      const [accounts, cards] = await Promise.all([
        allPages((cursor) =>
          accountApi.list({ status: "all", limit: 200, ...(cursor ? { cursor } : {}) }),
        ),
        allPages((cursor) =>
          cardApi.list({ status: "all", limit: 200, ...(cursor ? { cursor } : {}) }),
        ),
      ]);
      return { accounts, cards };
    }, [accountApi, cardApi]),
  );
  const methodName = (v: Terms) => {
    if (v.card_id) {
      const card = methods.data?.cards.find((row) => row.id === v.card_id);
      return card
        ? card.alias || card.product_name
        : methods.loading
          ? "카드 이름 불러오는 중"
          : "연결 카드 확인 필요";
    }
    if (v.account_id) {
      const account = methods.data?.accounts.find((row) => row.id === v.account_id);
      return (
        account?.asset.name ?? (methods.loading ? "계좌 이름 불러오는 중" : "연결 계좌 확인 필요")
      );
    }
    return "미지정";
  };
  // On a card or account page, a change to that same method reads as "this card/account".
  const changeTarget = (v: Terms) =>
    method && (method.kind === "card" ? v.card_id : v.account_id) === method.id
      ? method.kind === "card"
        ? "이 카드"
        : "이 계좌"
      : v.card_id || v.account_id
        ? methodName(v)
        : "납부수단 없음";
  const methodKind = method?.kind;
  const methodId = method?.id;
  const members = useHouseholdMembers();
  const [params, setParams] = useSearchParams();
  const filters = useListFilters(Boolean(method));
  const data = useResource(
    useCallback(async () => {
      // The ledger and its server totals are independent reads; fetch them together.
      const [rows, summary] = await Promise.all([
        allPages((cursor) =>
          api.rules({
            limit: 200,
            ...(cursor ? { cursor } : {}),
            ...(methodKind && methodId ? { [methodKind + "_id"]: methodId } : {}),
          }),
        ),
        api.summary(),
      ]);
      return { rows, summary };
    }, [api, methodKind, methodId]),
  );
  const rows = data.data?.rows ?? [];
  const selected = rows.find((row) => row.id === params.get("plan"));
  const creating = !method && params.get("new") === "1";
  const categories = [
    ...new Set([
      ...suggestedCategories,
      ...rows.flatMap((row) => row.history.map((v) => v.category)).filter(Boolean),
    ]),
  ].sort((a, b) => a.localeCompare(b, "ko"));
  const query = filters.q.toLocaleLowerCase();
  const visible = rows.filter((row) => {
    const v = currentPlan(row);
    const group = filters.group;
    return (
      !!v &&
      (v.title + " " + v.category + " " + methodName(v)).toLocaleLowerCase().includes(query) &&
      (group === "all" ||
        (group === "excluded" && v.budget_treatment !== "included") ||
        (group === "budget" && v.plan_kind === "budget") ||
        (group === "fixed" && v.plan_kind === "recurring" && v.budget_treatment === "included"))
    );
  });
  visible.sort((a, b) => {
    const av = currentPlan(a)!,
      bv = currentPlan(b)!;
    if (filters.sort === "amount") {
      const x = BigInt(av.monthly_equivalent_krw ?? "-1"),
        y = BigInt(bv.monthly_equivalent_krw ?? "-1");
      if (x !== y) return x > y ? -1 : 1;
    }
    if (filters.sort === "category") {
      const category = av.category.localeCompare(bv.category, "ko");
      if (category) return category;
    }
    return av.title.localeCompare(bv.title, "ko");
  });
  // Opening pushes one history entry, so Back (or Android back) closes the editor first.
  function openEditor(id: string | null) {
    setParams(
      (old) => {
        if (id) {
          old.set("plan", id);
          old.delete("new");
        } else {
          old.set("new", "1");
          old.delete("plan");
        }
        return old;
      },
      { state: { planEditor: true }, preventScrollReset: true },
    );
  }
  function closeEditor() {
    if ((location.state as EditorState)?.planEditor) navigate(-1);
    else
      setParams(
        (old) => {
          old.delete("plan");
          old.delete("new");
          return old;
        },
        { replace: true, preventScrollReset: true },
      );
  }
  async function saved() {
    closeEditor();
    await data.reload();
  }
  const ready = !!data.data && !data.error;
  return (
    <section className="expense-plans" aria-label={method ? "연결된 월 계획" : "월 지출 계획 관리"}>
      {method ? <h3>연결된 월 계획</h3> : ready && <ExpensePlanSummary data={data.data!.summary} />}
      <CashflowError error={data.error ?? members.error} />
      {data.loading && <p role="status">월 지출 계획을 불러오고 있어요.</p>}
      <div className="form-actions plan-toolbar">
        {!method && !creating && !selected && (
          <button
            className="primary-button"
            disabled={data.loading || !!data.error}
            onClick={() => openEditor(null)}
          >
            지출 계획 추가
          </button>
        )}
        <button
          className="secondary-button quiet-button"
          disabled={data.loading}
          onClick={() => void data.reload()}
        >
          월 계획 새로고침
        </button>
      </div>
      {/* A failed refresh keeps the loaded rows; keep their editor and its unsaved draft too. */}
      {creating || selected ? (
        <PlanEditor
          key={selected?.id ?? "new"}
          row={selected}
          categories={categories}
          onSaved={() => void saved()}
          onCancel={closeEditor}
        />
      ) : (
        <>
          <div className="form-actions plan-filters">
            <label>
              계획 검색
              <input
                type="search"
                value={filters.q}
                onChange={(e) => filters.set("q", e.target.value)}
              />
            </label>
            <label>
              계획 보기
              <select value={filters.group} onChange={(e) => filters.set("group", e.target.value)}>
                <option value="all">전체</option>
                <option value="fixed">고정 지출</option>
                <option value="budget">변동 예산</option>
                <option value="excluded">별도 표시</option>
              </select>
            </label>
            <label>
              정렬
              <select value={filters.sort} onChange={(e) => filters.set("sort", e.target.value)}>
                <option value="category">분류순</option>
                <option value="name">이름순</option>
                <option value="amount">월 금액순</option>
              </select>
            </label>
          </div>
          {methods.error && (
            // A missing name lookup leaves every plan visible; it is a polite notice, not a blocking error.
            <p role="status">
              납부수단 이름을 불러오지 못했어요.{" "}
              <button onClick={() => void methods.reload()}>납부수단 다시 불러오기</button>
            </p>
          )}
          {ready && (
            // Keep the loaded rows on screen during a refresh instead of collapsing the page.
            <div className="expense-ledger" aria-busy={data.loading}>
              <table role="table" aria-label="월 지출 계획 표">
                <thead>
                  <tr role="row">
                    <th scope="col">항목</th>
                    <th scope="col">분류</th>
                    <th scope="col" className="plan-amount">
                      월 금액
                    </th>
                    <th scope="col">납부 카드·계좌</th>
                    <th scope="col">참고</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((row) => {
                    const v = currentPlan(row)!;
                    return (
                      <tr
                        key={row.id}
                        role="row"
                        className={v.budget_treatment !== "included" ? "plan-excluded" : undefined}
                        data-economic={v.economic_type}
                      >
                        <th scope="row" role="rowheader" className="plan-title">
                          <button
                            className="link-button"
                            title={v.title}
                            onClick={() => openEditor(row.id)}
                          >
                            {v.title}
                          </button>
                        </th>
                        <td className="plan-category">
                          {v.category}
                          {v.plan_kind === "budget" && <small>변동 예산</small>}
                          {v.economic_type !== "expense" && (
                            <small>{economicTypes[v.economic_type]}</small>
                          )}
                          {v.budget_treatment !== "included" && (
                            <small>{treatments[v.budget_treatment]}</small>
                          )}
                        </td>
                        <td className="plan-amount">
                          <strong>{money(v.monthly_equivalent_krw)}</strong>
                          {v.frequency === "annual" ? (
                            <small>
                              {v.interval_count}년마다 {money(v.expected_amount_krw)}
                              {v.annual_month ? ` (${v.annual_month}월)` : ""}
                            </small>
                          ) : v.interval_count > 1 || v.frequency === "days" ? (
                            <small>
                              {v.interval_count}
                              {v.frequency === "days" ? "일" : "개월"}마다{" "}
                              {money(v.expected_amount_krw)}
                            </small>
                          ) : null}
                        </td>
                        <td className="plan-method">
                          {v.card_id || v.account_id ? (
                            <Link
                              to={v.card_id ? `/cards/${v.card_id}` : `/accounts/${v.account_id}`}
                            >
                              {methodName(v)}
                            </Link>
                          ) : (
                            <span className="muted">납부수단 미지정</span>
                          )}
                          {paymentMethodChanges(row).map((change) => (
                            <small key={change.id}>
                              변경 예정: {dateLabel(change.effective_from)}부터{" "}
                              {changeTarget(change)}
                            </small>
                          ))}
                        </td>
                        <td className="plan-note">
                          {v.tracking_mode === "scheduled" && <small>납부 일정 관리</small>}
                          {v.currency_reference && (
                            <small>
                              {v.foreign_amount_reference} {v.currency_reference}
                            </small>
                          )}
                          {v.subject_member_id && (
                            <small>
                              {members.members.find((m) => m.member_id === v.subject_member_id)
                                ?.display_name ?? "구성원"}
                            </small>
                          )}
                          {v.note && (
                            <details>
                              <summary>메모</summary>
                              <p>{v.note}</p>
                            </details>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {ready && !data.loading && !visible.length && (
            <p>
              {rows.length
                ? "조건에 맞는 월 계획이 없어요. 검색어나 보기를 바꿔 보세요."
                : "아직 등록한 월 계획이 없어요. 매달 나가는 돈을 하나씩 추가해 보세요."}
            </p>
          )}
          {rows.some((r) => !currentPlan(r)) && (
            <details>
              <summary>종료·적용 예정 항목</summary>
              {rows
                .filter((r) => !currentPlan(r))
                .map((r) => (
                  <p key={r.id}>
                    <button className="link-button" onClick={() => openEditor(r.id)}>
                      {r.history.at(-1)?.title ?? "계획"} · {r.ended_on ? "종료" : "적용 예정"}
                    </button>
                  </p>
                ))}
            </details>
          )}
        </>
      )}
    </section>
  );
}

const CURRENCY = /^[A-Z]{3}$/;
const FOREIGN_AMOUNT = /^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$/;

function PlanEditor({
  row: serverRow,
  categories,
  onSaved,
  onCancel,
}: {
  row?: Plan;
  categories: string[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const api = useExpensePlanApi();
  const fixedApi = useFixedApi();
  const members = useHouseholdMembers();
  const categoryList = useId();
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
  const [endOn, setEndOn] = useState(todaySeoul());
  const [action, setAction] = useState<"save" | "end" | "delete">("save");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [prepare, setPrepare] = useState<{ input: S["GenerateObligations"]; key: string } | null>(
    null,
  );
  const guard = useUnsavedChangesGuard(dirty);
  const command = useMonthCommand();
  const key = useIdempotencyKey(
    JSON.stringify([row?.id, row?.version, draft, amount, effective, endOn, action]),
    command.uncertain,
  );
  const ended = !!row?.ended_on && row.ended_on <= todaySeoul();
  function update(value: Partial<S["PlanCreate"]>) {
    setDraft((old) => ({ ...old, ...value }));
    setDirty(true);
    setValidation("");
  }
  async function prepareSchedule(task: { input: S["GenerateObligations"]; key: string }) {
    const result = await command.run((signal) => fixedApi.generate(task.input, task.key, signal));
    if (result.ok && command.mounted.current) onSaved();
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setAction("save");
    const parsed = amount.trim() ? parseKrwInput(amount) : null;
    if (parsed && !parsed.ok) {
      setValidation("금액은 원 단위 숫자로 입력해 주세요.");
      return;
    }
    const currency = (draft.currency_reference ?? "").trim();
    const foreign = (draft.foreign_amount_reference ?? "").trim();
    if ((currency || foreign) && !(CURRENCY.test(currency) && FOREIGN_AMOUNT.test(foreign))) {
      setValidation("외화 참고는 통화 코드(예: USD)와 금액을 함께 입력해 주세요.");
      return;
    }
    const input = {
      ...draft,
      currency_reference: currency || null,
      foreign_amount_reference: foreign || null,
      expected_amount_krw: parsed?.ok ? parsed.krw : null,
      amount_mode: parsed?.ok ? draft.amount_mode : "variable",
      effective_from: effective,
    } satisfies S["PlanCreate"];
    const result = await command.run((signal) =>
      row
        ? api.changeRule(row.id, { ...input, reason: "월 계획 수정" }, row.version, key, signal)
        : api.createRule(input, key, signal),
    );
    if (!result.ok || !command.mounted.current) return;
    guard.release();
    setDirty(false);
    // A scheduled item also gets this and the next 11 months of due dates, like a payment rule.
    if (input.tracking_mode === "scheduled" && input.plan_kind !== "budget") {
      const task = {
        input: { rule_id: row?.id ?? result.value.id, ...preparationWindow(effective) },
        key: `prepare:${key}`,
      };
      setPrepare(task);
      await prepareSchedule(task);
      return;
    }
    onSaved();
  }
  async function finish(kind: "end" | "delete") {
    if (!row) return;
    setAction(kind);
    const result = await command.run((signal) =>
      kind === "end"
        ? api.endRule(
            row.id,
            { effective_on: endOn, reason: "월 계획 종료" },
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
  if (prepare)
    return (
      <section className="card" aria-label="지출 계획 편집">
        <h3>납부 일정 준비</h3>
        <p>계획은 저장했어요. 이번 달부터 12개월의 납부 예정일을 준비하고 있어요.</p>
        <CashflowError error={command.error} />
        <div className="form-actions">
          <button disabled={command.busy} onClick={() => void prepareSchedule(prepare)}>
            납부 일정 다시 준비
          </button>
          <button className="secondary-button" disabled={command.busy} onClick={onSaved}>
            나중에 준비하기
          </button>
        </div>
      </section>
    );
  return (
    <section className="card" aria-label="지출 계획 편집">
      <h3>{row ? "지출 계획 수정" : "지출 계획 추가"}</h3>
      {action === "save" && <CashflowError error={command.error} />}
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
              list={categoryList}
              value={draft.category}
              onChange={(e) => update({ category: e.target.value })}
            />
            <datalist id={categoryList}>
              {categories.map((category) => (
                <option key={category} value={category} />
              ))}
            </datalist>
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
              {Object.entries(economicTypes).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
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
                required
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
              외화 결제 통화 (선택, 예: USD)
              <input
                maxLength={3}
                autoCapitalize="characters"
                value={draft.currency_reference ?? ""}
                onChange={(e) =>
                  update({ currency_reference: e.target.value.toUpperCase() || null })
                }
              />
            </label>
            <label>
              외화 참고 금액 (선택)
              <input
                inputMode="decimal"
                maxLength={40}
                value={draft.foreign_amount_reference ?? ""}
                onChange={(e) => update({ foreign_amount_reference: e.target.value || null })}
              />
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
          <details open={draft.tracking_mode === "scheduled" || undefined}>
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
              <>
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
                <p className="muted">
                  저장하면 이번 달부터 12개월의 납부 예정일을 준비해요. 실제 납부는 &lsquo;예정·실제
                  납부&rsquo;에서 따로 기록해요.
                </p>
              </>
            )}
          </details>
        </fieldset>
        {ended ? (
          <div className="form-actions save-actions">
            <button type="button" className="secondary-button" onClick={onCancel}>
              닫기
            </button>
          </div>
        ) : (
          <SaveControls
            busy={command.busy}
            cancel={command.cancel}
            label="계획 저장"
            onDismiss={onCancel}
          />
        )}
      </form>
      {row && <PlanInsuranceLink planId={row.id} />}
      {row && (
        <>
          <details className="history-disclosure">
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
            {/* Only scheduled terms have a payment-schedule detail; plan-only items live here. */}
            {row.versions.some((v) => v.tracking_mode === "scheduled") && (
              <p>
                <Link to={`/fixed-payments/rules/${row.id}`}>적용기간·납부 일정 자세히 관리</Link>
              </p>
            )}
          </details>
          <details className="secondary-actions">
            <summary>계획 종료·삭제</summary>
            {action !== "save" && <CashflowError error={command.error} />}
            {!ended && (
              <section className="review-panel" aria-label="계획 종료">
                <h4>계획 종료</h4>
                <label>
                  종료일
                  <input
                    type="date"
                    required
                    min={todaySeoul()}
                    disabled={command.busy}
                    value={endOn}
                    onChange={(e) => setEndOn(e.target.value)}
                  />
                </label>
                <p className="muted">
                  {endOn || "종료일"}부터 월 계획 합계에서 빠져요. 변경 이력은 그대로 남아요.
                </p>
                <button
                  type="button"
                  disabled={command.busy || !endOn}
                  onClick={() => void finish("end")}
                >
                  계획 종료하기
                </button>
              </section>
            )}
            <form
              className="review-panel danger-review"
              aria-label="잘못 등록한 계획 삭제"
              onSubmit={(e) => {
                e.preventDefault();
                void finish("delete");
              }}
            >
              <h4>잘못 등록한 계획 삭제</h4>
              <p className="muted">
                납부 기록이 있거나 보험료로 연결된 계획은 삭제할 수 없어요. 그때는 위에서 종료해
                주세요.
              </p>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={confirmDelete}
                  disabled={command.busy}
                  onChange={(e) => setConfirmDelete(e.target.checked)}
                />
                잘못 등록한 계획의 삭제를 확인했어요
              </label>
              <button type="submit" disabled={command.busy || !confirmDelete}>
                계획 삭제하기
              </button>
            </form>
          </details>
        </>
      )}
    </section>
  );
}
