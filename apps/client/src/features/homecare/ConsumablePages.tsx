import { LastModified } from "../../shared/RecordActor";
import { NameSearch } from "../../shared/NameSearch";
import { TaskNavigation } from "../../shared/TaskLayout";
import { Icon } from "../../shared/Icon";
import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { dateLabel, isUuid, todaySeoul } from "../finance/dates";
import { usePagedList, useResource } from "../finance/queries";
import { useHomecareApi } from "./api";
import {
  changedFields,
  consumableDraft,
  consumableInput,
  etag,
  preserveDraft,
  statuses,
} from "./model";
import type { Consumable, ConsumableDraft } from "./model";
import {
  ConflictReview,
  HomecarePage,
  ListFeedback,
  MetadataFeedback,
  ResourceFeedback,
  useMetadataCommand,
} from "./HomecareSupport";
import { DeleteHomecare } from "./DeleteHomecare";
import { DeviceLinks } from "./DeviceLinks";
import { StockEditor, StockMovements } from "./StockPages";
import { TodayConsumables } from "./TodayConsumables";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { stateFlag, useRouteNotice } from "../../shared/routeNotice";
import { useHomecareOrigin } from "./HomecareOutcome";
import { FormError, useSubmitAttempt } from "../../shared/formValidation";
export function ConsumableSummary({ row }: { row: Consumable }) {
  return (
    <>
      <dl className="metadata-grid">
        <div>
          <dt>소모품 이름 · 규격</dt>
          <dd>
            {row.name} · {row.sku_or_model || "규격 미입력"}
          </dd>
        </div>
        <div>
          <dt>공용 재고</dt>
          <dd>
            {row.stock_quantity.toLocaleString("ko-KR")} {row.unit}
          </dd>
        </div>
        <div>
          <dt>재고 부족 임계</dt>
          <dd>
            {row.low_stock_threshold.toLocaleString("ko-KR")} {row.unit} ·{" "}
            {row.low_stock ? "재고 부족" : "부족 표시 없음"}
          </dd>
        </div>
        <div>
          <dt>소모품 사용 상태</dt>
          <dd>
            {statuses[row.status]}
            {row.ended_on && ` · ${dateLabel(row.ended_on)}`}
          </dd>
        </div>
        <div>
          <dt>소모품 메모</dt>
          <dd>{row.note || "미입력"}</dd>
        </div>
        <LastModified record={row} />
      </dl>
      <p className="muted">
        여러 기기가 같은 재고를 사용해요. 재고 부족 표시가 없어도 한 번 교체할 수량보다 적으면
        구매가 필요해요.
      </p>
    </>
  );
}
export function ConsumableEditor({
  initial,
  onSaved,
  onCancel,
}: {
  initial?: Consumable;
  onSaved?: (row: Consumable) => void;
  onCancel?: () => void;
}) {
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const api = useHomecareApi();
  const navigate = useNavigate();
  const command = useMetadataCommand();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => consumableDraft(initial));
  const [latest, setLatest] = useState<Consumable | null>(null);
  const [ack, setAck] = useState(false);
  const [message, setMessage] = useState("");
  const attempt = useSubmitAttempt();
  const input = consumableInput(draft);
  const changed =
    base && input ? changedFields(consumableInput(consumableDraft(base))!, input) : null;
  const ending = !!draft.ended && draft.ended !== base?.ended_on;
  const change = <K extends keyof ConsumableDraft>(key: K, value: ConsumableDraft[K]) => {
    setDraft((old) => ({ ...old, [key]: value }));
    if (key === "ended") setAck(false);
    if (!base && !command.uncertain) command.setError(null);
  };
  async function submit(e: FormEvent<HTMLFormElement>) {
    const form = e.currentTarget;
    e.preventDefault();
    if (command.error?.status === 409) return;
    const problem = !input
      ? "소모품 이름·단위·재고 부족 임계 수량·종료일을 확인해 주세요."
      : ending && !ack
        ? "사용 종료 확인란을 선택해 주세요."
        : base && !Object.keys(changed ?? {}).length
          ? "바꾼 소모품 정보가 없어요."
          : "";
    if (problem || !input) {
      setMessage(problem);
      attempt.reject(form);
      return;
    }
    const row = await command.run(
      () =>
        base
          ? api.updateConsumable({
              consumableId: base.id,
              input: changed!,
              ifMatch: etag(base.version),
            })
          : api.createConsumable({ input }),
      !base,
    );
    if (row && command.mounted.current) {
      guard.release();
      if (onSaved) onSaved(row);
      else
        navigate(`/consumables/${row.id}`, {
          replace: true,
          state: !base ? { consumableCreated: true } : null,
        });
    }
  }
  async function compare() {
    if (!base) return;
    try {
      const row = await api.getConsumable({ consumableId: base.id });
      if (command.mounted.current) setLatest(row);
    } catch (e) {
      if (command.mounted.current) command.setError(toApiError(e));
    }
  }
  function adopt(keep: boolean) {
    if (!latest) return;
    setDraft(
      keep
        ? preserveDraft(consumableDraft(base), draft, consumableDraft(latest))
        : consumableDraft(latest),
    );
    setBase(latest);
    setLatest(null);
    command.setError(null);
    setAck(false);
  }
  return (
    <section className="card">
      <h2>소모품 규격과 공용 재고 기준</h2>
      <p>
        처음에는 재고 0으로 등록돼요. 구매·기초 수량은 날짜와 함께 입고 또는 사유 있는 조정으로
        기록해 주세요.
      </p>
      <form
        onInput={() => {
          setDirty(true);
          setMessage("");
        }}
        onSubmit={(e) => void submit(e)}
      >
        <fieldset disabled={command.busy}>
          <legend>소모품 정보</legend>
          <div className="form-grid">
            {(
              [
                ["name", "소모품 이름", 120],
                ["sku", "SKU·규격·모델", 120],
                ["unit", "재고 단위", 40],
              ] as const
            ).map(([key, label, length]) => (
              <div className="form-field" key={key}>
                <label>
                  {label}
                  <input
                    required={key !== "sku"}
                    maxLength={length}
                    value={draft[key]}
                    onChange={(e) => change(key, e.target.value)}
                  />
                </label>
              </div>
            ))}
            <div className="form-field">
              <label>
                재고 부족 임계 수량
                <input
                  inputMode="numeric"
                  required
                  value={draft.threshold}
                  onChange={(e) => change("threshold", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                소모품 사용 종료일
                <input
                  type="date"
                  max={todaySeoul()}
                  value={draft.ended}
                  onChange={(e) => change("ended", e.target.value)}
                />
              </label>
              <p className="muted">비우면 사용 중이에요. 종료 후에도 원장과 교체 기록은 남아요.</p>
            </div>
            <div className="form-field">
              <label>
                소모품 메모
                <textarea
                  maxLength={2000}
                  value={draft.note}
                  onChange={(e) => change("note", e.target.value)}
                />
              </label>
            </div>
          </div>
          {ending && (
            <label className="checkbox-field">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              종료 후 새 입고·교체가 제한되고 현재 재고와 이력은 보존됨을 확인했어요
            </label>
          )}
        </fieldset>
        <FormError message={message} />
        <MetadataFeedback command={command} listPath="/consumables?status=all" />
        <ConflictReview
          error={base ? command.error : null}
          compare={() => void compare()}
          latest={!!latest}
          adopt={() => adopt(true)}
          replace={() => adopt(false)}
        >
          {latest && <ConsumableSummary row={latest} />}
        </ConflictReview>
        <button
          type="submit"
          disabled={command.busy || command.uncertain || command.error?.status === 409}
        >
          {base ? "소모품 수정 저장" : "소모품 등록"}
        </button>
        {onCancel && (
          <button
            type="button"
            disabled={command.busy}
            onClick={() => {
              guard.release();
              onCancel();
            }}
          >
            소모품 등록 취소
          </button>
        )}
      </form>
    </section>
  );
}
function ConsumableList() {
  const origin = useHomecareOrigin();
  const api = useHomecareApi();
  const [params, setParams] = useSearchParams();
  const status =
    params.get("status") === "all" ? "all" : params.get("status") === "ended" ? "ended" : "active";
  const q = params.get("q") ?? "";
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.listConsumables({ query: { status, cursor, limit: 50, ...(q ? { q } : {}) } }),
      [api, status, q],
    ),
    undefined,
    "consumables",
  );
  return (
    <>
      <TaskNavigation
        label="소모품 작업 바로가기"
        sections={[
          { id: "shared-stock", label: "공용 재고", detail: "수량 확인과 입고" },
          { id: "today-care", label: "교체 확인", detail: "오늘 기준 관리" },
        ]}
      />
      <section
        id="shared-stock"
        className="task-section"
        tabIndex={-1}
        aria-label="소모품 규격 목록"
      >
        <h2>공용 재고·규격 목록</h2>
        <NameSearch label="소모품 이름·규격 검색" />
        <div className="form-field">
          <label>
            소모품 사용 상태
            <select
              value={status}
              onChange={(e) =>
                setParams((previous) => {
                  const next = new URLSearchParams(previous);
                  next.set("status", e.target.value);
                  return next;
                })
              }
            >
              {Object.entries(statuses).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="record-list inventory-grid">
          {list.items.map((row) => (
            <article className="card stock-card" key={row.id}>
              <div className="record-heading">
                <span className="record-icon warm">
                  <Icon name="package" />
                </span>
                <h3>
                  <Link to={`/consumables/${row.id}`}>{row.name}</Link>
                </h3>
              </div>
              <p className="muted">
                {row.sku_or_model || "규격 미입력"} · {statuses[row.status]}
              </p>
              <p className="stock-count">
                공용 재고 <strong>{row.stock_quantity.toLocaleString("ko-KR")}</strong> {row.unit} ·{" "}
                <span className={row.low_stock ? "stock-low" : "stock-ready"}>
                  {row.low_stock ? "재고 부족" : "부족 표시 없음"}
                </span>
              </p>
              <div className="form-actions">
                {row.status === "active" && (
                  <Link
                    className="button-link secondary-button"
                    to={`/consumables/${row.id}/stock/new`}
                    state={origin}
                  >
                    입고·재고 조정 기록
                  </Link>
                )}
                <Link to={`/consumables/${row.id}`}>기기별 교체·상세</Link>
              </div>
            </article>
          ))}
        </div>
        <ListFeedback
          list={list}
          empty="해당 상태의 소모품이 없어요. 규격을 등록한 뒤 여러 기기에 연결할 수 있어요."
        />
      </section>
      <section id="today-care" className="task-section" tabIndex={-1} aria-label="오늘 교체 확인">
        <TodayConsumables />
      </section>
    </>
  );
}
export function ConsumableListPage() {
  return (
    <HomecarePage
      title="소모품 관리"
      description="같은 규격의 재고는 함께 쓰고, 기기별 교체 기준은 따로 관리해요."
      navigation={
        <div className="form-actions">
          <Link className="button-link" to="/consumables/new">
            소모품 등록하기
          </Link>
          <Link to="/purchase-plan">공용 구매 계획·주문</Link>
          <Link to="/appliances">가전 관리</Link>
        </div>
      }
    >
      <ConsumableList />
    </HomecarePage>
  );
}
export function ConsumableNewPage() {
  return (
    <HomecarePage
      title="소모품 등록"
      description="사용자가 정한 규격·단위와 재고 부족 기준을 기록해요."
    >
      <ConsumableEditor />
    </HomecarePage>
  );
}
function ConsumableDetail({ id, edit }: { id: string; edit: boolean }) {
  const origin = useHomecareOrigin();
  const created = useRouteNotice(stateFlag("consumableCreated"));
  const [setupDone, setSetupDone] = useState(false);
  const api = useHomecareApi();
  const navigate = useNavigate();
  const resource = useResource(
    useCallback(
      () =>
        isUuid(id)
          ? api.getConsumable({ consumableId: id })
          : Promise.reject(new ApiError(404, "NOT_FOUND")),
      [api, id],
    ),
  );
  const row = resource.data;
  return (
    <>
      <ResourceFeedback resource={resource} />
      {row &&
        !resource.error &&
        !resource.loading &&
        (edit ? (
          <ConsumableEditor key={`${row.id}:${row.version}`} initial={row} />
        ) : (
          <>
            <section className="card">
              <h2>{row.name}</h2>
              <div className="primary-action-row">
                {row.status === "active" && (
                  <Link className="button-link" to={`/consumables/${id}/stock/new`} state={origin}>
                    입고·재고 조정 기록
                  </Link>
                )}
                <Link to={`/consumables/${id}/edit`}>소모품 정보 수정·사용 종료</Link>
                <Link to={`/consumable-orders?consumable_id=${id}&state=all`} state={origin}>
                  구매 예정·주문 이력
                </Link>
              </div>
              <ConsumableSummary row={row} />
              <DeleteHomecare
                initial={row}
                label="소모품"
                name={row.name}
                read={() => api.getConsumable({ consumableId: id })}
                remove={(current, signal) =>
                  api.deleteConsumable({ consumableId: id, ifMatch: etag(current.version) }, signal)
                }
                render={(current) => <ConsumableSummary row={current} />}
                deleted={() => navigate("/consumables", { replace: true })}
                listPath="/consumables?status=all"
              />
            </section>
            {created && !setupDone && (
              <StockEditor
                initial={row}
                initialSetup
                onSaved={() => {
                  setSetupDone(true);
                  void resource.reload();
                }}
                onCancel={() => setSetupDone(true)}
              />
            )}
            <DeviceLinks consumable={row} />
            <StockMovements consumable={row} />
          </>
        ))}
    </>
  );
}
export function ConsumableDetailPage({ edit = false }: { edit?: boolean }) {
  const { id = "" } = useParams();
  return (
    <HomecarePage
      title={edit ? "소모품 정보 수정" : "소모품 상세"}
      description="공용 재고 원장과 기기별 교체 이력을 함께 확인해요."
    >
      <ConsumableDetail key={`${id}:${edit}`} id={id} edit={edit} />
    </HomecarePage>
  );
}
