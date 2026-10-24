import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { formatKrw } from "../assets/months/model";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { SaveControls } from "../finance/FinancialFeedback";
import { MemberLoadError, useHouseholdMembers } from "../finance/FinanceSupport";
import { dateLabel, isDateOnly, isUuid, todaySeoul } from "../finance/dates";
import { usePagedList, useResource } from "../finance/queries";
import { useHomecareApi } from "./api";
import { etag, movementInput, movementLabels, purchaseUrl, quantity } from "./model";
import type { Consumable, Movement, MovementDraft, Replacement } from "./model";
import { HomecareError, HomecarePage, ListFeedback, ResourceFeedback } from "./HomecareSupport";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { AmountField } from "../../shared/AmountField";
import { FormError, useSubmitAttempt } from "../../shared/formValidation";
import { krwFieldError } from "../../shared/krw";
import { useHomecareReturn, type StockOutcome } from "./HomecareOutcome";
import { formatSeoulDateTime } from "../../shared/format";
export function StockSummary({ row }: { row: Consumable }) {
  return (
    <p>
      현재 {row.name} 공용 재고:{" "}
      <strong>
        {row.stock_quantity.toLocaleString("ko-KR")} {row.unit}
      </strong>{" "}
      · {row.status === "active" ? "사용 중" : "사용 종료"}
    </p>
  );
}
export function MovementSummary({ row, unit }: { row: Movement; unit: string }) {
  return (
    <>
      <dl className="metadata-grid">
        <div>
          <dt>재고 동작</dt>
          <dd>
            {movementLabels[row.kind]} · {row.quantity_delta > 0 ? "+" : ""}
            {row.quantity_delta.toLocaleString("ko-KR")} {unit}
          </dd>
        </div>
        <div>
          <dt>실제 날짜</dt>
          <dd>{dateLabel(row.occurred_on)}</dd>
        </div>
        <div>
          <dt>상태</dt>
          <dd>
            {row.reversed_by
              ? "취소됨 · 원본 보존"
              : row.kind === "reversal"
                ? "취소 보정"
                : "반영된 원본"}
          </dd>
        </div>
        <div>
          <dt>단위당 참고 가격</dt>
          <dd>{formatKrw(row.unit_cost_krw)}</dd>
        </div>
        <div>
          <dt>사유</dt>
          <dd>{row.reason || "미입력"}</dd>
        </div>
        <div>
          <dt>메모</dt>
          <dd>{row.note || "미입력"}</dd>
        </div>
      </dl>
      {row.purchase_url && purchaseUrl(row.purchase_url) && (
        <p>
          <a href={row.purchase_url} target="_blank" rel="noopener noreferrer">
            기록한 구매 링크 열기
          </a>
        </p>
      )}
      {row.reversal_of && (
        <p>
          <Link to={`/consumables/${row.consumable_id}/stock/${row.reversal_of}`}>
            취소 전 원본 보기
          </Link>
        </p>
      )}
      {row.reversed_by && (
        <p>
          <Link to={`/consumables/${row.consumable_id}/stock/${row.reversed_by}`}>
            취소 보정 기록 보기
          </Link>
        </p>
      )}
      <p className="muted">
        작성 시각 {formatSeoulDateTime(row.created_at)} · 재고 동작은 자산·수입·지출을 자동 변경하지
        않아요.
      </p>
    </>
  );
}
export function StockMovements({ consumable }: { consumable: Consumable }) {
  const api = useHomecareApi();
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.listStockMovements({ consumableId: consumable.id, query: { cursor, limit: 50 } }),
      [api, consumable.id],
    ),
  );
  return (
    <section className="card">
      <h2>공용 재고 원장</h2>
      <p>
        입고·사용·반품·조정과 취소 보정을 원본별로 보존해요. 입고만으로 기기의 교체일은 바뀌지
        않아요.
      </p>
      <ul className="finance-list">
        {list.items.map((row) => (
          <li key={row.id}>
            <h3>
              <Link to={`/consumables/${consumable.id}/stock/${row.id}`}>
                {movementLabels[row.kind]} · {row.quantity_delta > 0 ? "+" : ""}
                {row.quantity_delta.toLocaleString("ko-KR")} {consumable.unit}
              </Link>
            </h3>
            <p>
              {dateLabel(row.occurred_on)} ·{" "}
              {row.reversed_by
                ? "취소된 원본"
                : row.kind === "reversal"
                  ? "취소 보정"
                  : "반영된 원본"}
            </p>
          </li>
        ))}
      </ul>
      <ListFeedback
        list={list}
        empty="재고 원장이 없어요. 구매 수량을 입고하거나 기초 수량을 사유와 함께 조정해 주세요."
      />
    </section>
  );
}
export function StockEditor({
  initial,
  initialSetup = false,
  onSaved,
  onCancel,
}: {
  initial: Consumable;
  initialSetup?: boolean;
  onSaved?: (result: StockOutcome) => void;
  onCancel?: () => void;
}) {
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const api = useHomecareApi();
  const navigate = useNavigate();
  const command = useMonthCommand();
  const returnTo = useHomecareReturn();
  const [stock, setStock] = useState(initial);
  const [latest, setLatest] = useState<Consumable | null>(null);
  const [draft, setDraft] = useState<MovementDraft>({
    kind: initialSetup ? "adjustment" : "receipt",
    quantity: "",
    date: todaySeoul(),
    price: "",
    url: "",
    reason: initialSetup ? "처음 확인한 보유 재고" : "",
    note: "",
  });
  const [message, setMessage] = useState("");
  const attempt = useSubmitAttempt();
  const targetQuantity = quantity(draft.quantity);
  const input = initialSetup
    ? targetQuantity === null
      ? null
      : movementInput({ ...draft, quantity: String(targetQuantity - stock.stock_quantity) })
    : movementInput(draft);
  const key = useIdempotencyKey(JSON.stringify({ stock: stock.id, version: stock.version, input }));
  const change = <K extends keyof MovementDraft>(field: K, value: MovementDraft[K]) =>
    setDraft((old) => ({ ...old, [field]: value }));
  async function submit(e: FormEvent<HTMLFormElement>) {
    const form = e.currentTarget;
    e.preventDefault();
    if (stock.status !== "active" || command.error?.status === 409) return;
    if (!input) {
      setMessage(
        initialSetup && targetQuantity === stock.stock_quantity
          ? "현재 재고와 같아요. 추가 조정 없이 ‘재고 설정 건너뛰고 계속’을 선택해 주세요."
          : "수량·날짜·가격·구매 링크를 확인해 주세요. 재고 조정에는 사유가 필요해요.",
      );
      attempt.reject(form);
      return;
    }
    const result = await command.run((signal) =>
      api.createStockMovement(
        { consumableId: stock.id, input, ifMatch: etag(stock.version), idempotencyKey: key },
        signal,
      ),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      if (onSaved) onSaved(result.value);
      else
        navigate(returnTo ?? `/consumables/${stock.id}/stock/${result.value.id}`, {
          replace: true,
          state: { homecareOutcome: result.value },
        });
    }
  }
  async function compare() {
    try {
      const current = await api.getConsumable({ consumableId: stock.id });
      if (command.mounted.current) setLatest(current);
    } catch (e) {
      if (command.mounted.current) command.setError(toApiError(e));
    }
  }
  return (
    <section className="card">
      <h2>{initialSetup ? "현재 보유 재고 설정" : "입고·반품·재고 조정"}</h2>
      <StockSummary row={stock} />
      <p>
        {initialSetup
          ? "지금 실제로 보유한 총수량을 입력하면 현재 재고와의 차이를 사유 있는 조정으로 기록해요. 기기 교체일은 바뀌지 않아요. 재고 설정은 나중에 해도 돼요."
          : "구매한 날짜와 수량을 기록해요. 교체·재고 사용은 기기별 교체 화면에서 기록해 주세요."}
      </p>
      <form
        onInput={() => {
          setDirty(true);
          setMessage("");
        }}
        onSubmit={(e) => void submit(e)}
      >
        <fieldset disabled={command.busy || stock.status !== "active"}>
          <legend>실제 재고 변화</legend>
          <div className="form-grid">
            <div className="form-field">
              <label>
                재고 기록 종류
                <select
                  value={draft.kind}
                  disabled={initialSetup}
                  onChange={(e) => change("kind", e.target.value as MovementDraft["kind"])}
                >
                  {(["receipt", "return_in", "return_out", "adjustment"] as const).map((kind) => (
                    <option key={kind} value={kind}>
                      {movementLabels[kind]}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-field">
              <label>
                {initialSetup
                  ? "현재 보유 총수량"
                  : draft.kind === "adjustment"
                    ? "재고 조정 수량 (증가 양수·감소 음수)"
                    : "입고·반품 수량"}
                <input
                  required
                  inputMode={draft.kind === "adjustment" ? "text" : "numeric"}
                  value={draft.quantity}
                  onChange={(e) => change("quantity", e.target.value)}
                />
              </label>
              <p className="muted">
                {initialSetup
                  ? `현재 ${stock.stock_quantity}${stock.unit}에서 입력한 총수량으로 맞춰요.`
                  : draft.kind === "return_out"
                    ? "양수로 입력한 수량을 재고에서 빼요."
                    : draft.kind === "adjustment"
                      ? "현재 총재고가 아니라 차이를 입력해요. 예: 누락 2개는 -2."
                      : "입력한 수량을 공용 재고에 더해요."}
              </p>
            </div>
            <div className="form-field">
              <label>
                재고 실제 날짜
                <input
                  required
                  type="date"
                  max={todaySeoul()}
                  value={draft.date}
                  onChange={(e) => change("date", e.target.value)}
                />
              </label>
            </div>
            <AmountField
              label="단위당 참고 가격 (원)"
              value={draft.price}
              hint="미입력과 0원은 달라요. 실제 지출 원장을 만들지 않아요."
              error={
                attempt.attempted
                  ? krwFieldError(draft.price, { required: false, positive: false })
                  : null
              }
              onChange={(value) => change("price", value)}
            />
            <div className="form-field">
              <label>
                구매 링크 (HTTPS)
                <input
                  type="url"
                  maxLength={2048}
                  value={draft.url}
                  onChange={(e) => change("url", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                재고 기록 사유{draft.kind === "adjustment" ? " (필수)" : " (선택)"}
                <textarea
                  required={draft.kind === "adjustment"}
                  maxLength={500}
                  value={draft.reason}
                  onChange={(e) => change("reason", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                재고 기록 메모
                <textarea
                  maxLength={2000}
                  value={draft.note}
                  onChange={(e) => change("note", e.target.value)}
                />
              </label>
            </div>
          </div>
        </fieldset>
        <FormError message={message} />
        <HomecareError error={command.error} />
        {command.error?.status === 409 && (
          <section className="review-panel">
            <p>작성한 내용은 유지했어요. 현재 공용 재고와 사용 상태를 확인해 주세요.</p>
            <button type="button" onClick={() => void compare()}>
              현재 재고 비교
            </button>
            {latest && (
              <>
                <StockSummary row={latest} />
                <button
                  type="button"
                  onClick={() => {
                    setStock(latest);
                    setLatest(null);
                    command.setError(null);
                  }}
                >
                  입력 유지하고 현재 재고 기준 적용
                </button>
              </>
            )}
          </section>
        )}
        <SaveControls
          backTo={onCancel ? undefined : (returnTo ?? `/consumables/${stock.id}`)}
          busy={command.busy}
          cancel={command.cancel}
          label={initialSetup ? "현재 보유 재고 저장" : "재고 변화 저장"}
          disabled={stock.status !== "active" || command.error?.status === 409}
        />
        {onCancel && (
          <button
            type="button"
            disabled={command.busy}
            onClick={() => {
              guard.release();
              onCancel();
            }}
          >
            재고 설정 건너뛰고 계속
          </button>
        )}
      </form>
    </section>
  );
}
export function CancelStock({
  initialStock,
  movement,
  replacement,
  saved,
  cancel,
}: {
  initialStock: Consumable;
  movement?: Movement;
  replacement?: Replacement;
  saved: (id: string) => void;
  cancel: () => void;
}) {
  const api = useHomecareApi();
  const command = useMonthCommand();
  const [stock, setStock] = useState(initialStock);
  const [target, setTarget] = useState<Movement | Replacement>(replacement ?? movement!);
  const [latest, setLatest] = useState<{
    stock: Consumable;
    target: Movement | Replacement;
  } | null>(null);
  const [date, setDate] = useState(todaySeoul());
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const attempt = useSubmitAttempt();
  const originalDate = "replaced_on" in target ? target.replaced_on : target.occurred_on;
  const reversed =
    "replaced_on" in target
      ? !!target.cancelled_by_movement_id
      : !!target.reversed_by || target.kind === "reversal" || target.kind === "replacement";
  const input = { occurred_on: date, reason: reason.trim() };
  const valid =
    isDateOnly(date) &&
    date >= originalDate &&
    date <= todaySeoul() &&
    !!input.reason &&
    input.reason.length <= 500 &&
    ack &&
    !reversed;
  const key = useIdempotencyKey(
    JSON.stringify({ id: target.id, stock: stock.id, version: stock.version, input }),
  );
  async function submit(e: FormEvent<HTMLFormElement>) {
    const form = e.currentTarget;
    e.preventDefault();
    if (reversed || command.error?.status === 409) return;
    if (!valid) {
      setMessage("취소 날짜·사유·확인란을 확인해 주세요. 날짜는 원래 기록일과 오늘 사이여야 해요.");
      attempt.reject(form);
      return;
    }
    const options = { input, ifMatch: etag(stock.version), idempotencyKey: key };
    const result = await command.run((signal) =>
      "replaced_on" in target
        ? api.cancelConsumableReplacement(
            { ...options, linkId: target.appliance_consumable_id, replacementId: target.id },
            signal,
          )
        : api.cancelStockMovement(
            { ...options, consumableId: stock.id, movementId: target.id },
            signal,
          ),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      saved(result.value.id);
    }
  }
  async function compare() {
    try {
      const [currentStock, currentTarget] = await Promise.all([
        api.getConsumable({ consumableId: stock.id }),
        "replaced_on" in target
          ? api.getConsumableReplacement({
              linkId: target.appliance_consumable_id,
              replacementId: target.id,
            })
          : api.getStockMovement({ consumableId: stock.id, movementId: target.id }),
      ]);
      if (command.mounted.current) setLatest({ stock: currentStock, target: currentTarget });
    } catch (e) {
      if (command.mounted.current) command.setError(toApiError(e));
    }
  }
  return (
    <section className="card">
      <h3>{replacement ? "교체 기록 취소 검토" : "재고 원본 취소 검토"}</h3>
      <StockSummary row={stock} />
      <p>
        {dateLabel(originalDate)}의 원본은 보존하고 반대 수량의 보정 기록을 추가해요.
        {replacement &&
          " 다음 확인일은 취소되지 않은 실제 교체 이력과 현재 주기·직접 지정일로 다시 계산해요. 이 교체 때 해제한 직접 지정일은 그 뒤 기기 설정을 바꾸지 않았다면 다시 적용해요."}
      </p>
      {reversed && (
        <p role="status">현재 원본은 이 화면에서 취소할 수 없어요. 연결 이력을 확인해 주세요.</p>
      )}
      <form
        onInput={() => {
          setMessage("");
          setDirty(true);
        }}
        onSubmit={(e) => void submit(e)}
      >
        <fieldset disabled={command.busy || reversed}>
          <legend>취소 내용</legend>
          <div className="form-field">
            <label>
              재고 취소일
              <input
                type="date"
                required
                min={originalDate}
                max={todaySeoul()}
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
          </div>
          <div className="form-field">
            <label>
              재고 취소 사유
              <textarea
                required
                maxLength={500}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
          </div>
          <label className="checkbox-field">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            원본 전체 수량을 취소하고 보정 이력을 남겨요
          </label>
        </fieldset>
        <FormError message={message} />
        <HomecareError error={command.error} />
        {command.error?.status === 409 && (
          <section className="review-panel">
            <button type="button" onClick={() => void compare()}>
              취소 전 현재 재고·원본 비교
            </button>
            {latest && (
              <>
                <StockSummary row={latest.stock} />
                <p>
                  현재 원본:{" "}
                  {"replaced_on" in latest.target
                    ? latest.target.cancelled_by_movement_id
                      ? "이미 취소됨"
                      : "교체 반영됨"
                    : latest.target.reversed_by
                      ? "이미 취소됨"
                      : "재고 반영됨"}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setStock(latest.stock);
                    setTarget(latest.target);
                    setLatest(null);
                    setAck(false);
                    command.setError(null);
                  }}
                >
                  작성한 사유 유지하고 현재 상태 적용
                </button>
              </>
            )}
          </section>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          label="원본 취소·재고 보정"
          disabled={reversed || command.error?.status === 409}
        />
        <button type="button" disabled={command.busy} onClick={cancel}>
          취소 검토 닫기
        </button>
      </form>
    </section>
  );
}
function StockNew({ id }: { id: string }) {
  const api = useHomecareApi();
  const resource = useResource(
    useCallback(
      () =>
        isUuid(id)
          ? api.getConsumable({ consumableId: id })
          : Promise.reject(new ApiError(404, "NOT_FOUND")),
      [api, id],
    ),
  );
  return (
    <>
      <ResourceFeedback resource={resource} />
      {resource.data && !resource.error && !resource.loading && (
        <StockEditor initial={resource.data} />
      )}
    </>
  );
}
export function StockNewPage() {
  const { id = "" } = useParams();
  return (
    <HomecarePage
      title="입고·재고 조정 기록"
      description="실제 수량 변화를 원본으로 기록하고 같은 요청은 한 번만 반영해요."
    >
      <StockNew key={id} id={id} />
    </HomecarePage>
  );
}
function StockDetail({ id, movementId }: { id: string; movementId: string }) {
  const api = useHomecareApi();
  const navigate = useNavigate();
  const [cancelling, setCancelling] = useState(false);
  const members = useHouseholdMembers();
  const resource = useResource(
    useCallback(async () => {
      if (!isUuid(id) || !isUuid(movementId)) throw new ApiError(404, "NOT_FOUND");
      const [stock, movement] = await Promise.all([
        api.getConsumable({ consumableId: id }),
        api.getStockMovement({ consumableId: id, movementId }),
      ]);
      return { stock, movement };
    }, [api, id, movementId]),
  );
  const data = resource.data;
  return (
    <>
      <ResourceFeedback resource={resource} />
      {data && !resource.error && !resource.loading && (
        <>
          <section className="card">
            <h2>{data.stock.name} 재고 원본</h2>
            <StockSummary row={data.stock} />
            <MovementSummary row={data.movement} unit={data.stock.unit} />
            <p>
              작성자:{" "}
              {members.members.find((m) => m.member_id === data.movement.created_by_member_id)
                ?.display_name ?? "구성원 확인 필요"}
            </p>
            <MemberLoadError error={members.error} retry={members.retry} />
            <div className="form-actions">
              <Link to={`/consumables/${id}`}>공용 재고와 기기별 교체로 돌아가기</Link>
              {!data.movement.reversed_by &&
                data.movement.kind !== "reversal" &&
                data.movement.kind !== "replacement" && (
                  <button type="button" onClick={() => setCancelling(true)}>
                    재고 원본 취소 검토
                  </button>
                )}
            </div>
            {data.movement.kind === "replacement" && (
              <p>기기별 교체 이력에서 원본을 확인하고 취소해 주세요.</p>
            )}
          </section>
          {cancelling && (
            <CancelStock
              initialStock={data.stock}
              movement={data.movement}
              cancel={() => setCancelling(false)}
              saved={(newId) => navigate(`/consumables/${id}/stock/${newId}`)}
            />
          )}
        </>
      )}
    </>
  );
}
export function StockDetailPage() {
  const { id = "", movementId = "" } = useParams();
  return (
    <HomecarePage title="재고 원본 상세" description="원본과 취소 보정을 삭제 없이 함께 확인해요.">
      <StockDetail key={`${id}:${movementId}`} id={id} movementId={movementId} />
    </HomecarePage>
  );
}
