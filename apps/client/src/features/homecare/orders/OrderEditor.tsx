import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { AmountField } from "../../../shared/AmountField";
import { FormError, useSubmitAttempt } from "../../../shared/formValidation";
import { krwFieldError } from "../../../shared/krw";
import { RecordActor } from "../../../shared/RecordActor";
import { useTaskPanelRelease } from "../../../shared/TaskLayout";
import { useUnsavedChangesGuard } from "../../../shared/UnsavedChanges";
import { formatKrw } from "../../assets/months/model";
import { useIdempotencyKey, useMonthCommand } from "../../assets/months/useMonthCommand";
import { SaveControls } from "../../finance/FinancialFeedback";
import { HomecareError } from "../HomecareSupport";
import { etag, preserveDraft, purchaseUrl, quantity, type Consumable } from "../model";
import { usePurchaseApi } from "./api";
import { orderDraft, orderInput, orderStates, type Order, type OrderDraft } from "./model";

export function OrderEditor({
  stock,
  initial,
  seed,
  saved,
  close,
  backTo,
}: {
  stock: Consumable;
  initial?: Order;
  seed?: OrderDraft;
  saved?: () => void;
  close?: () => void;
  backTo: string;
}) {
  const api = usePurchaseApi();
  const navigate = useNavigate();
  const command = useMonthCommand();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState<OrderDraft>(() =>
    initial ? orderDraft(initial) : (seed ?? orderDraft()),
  );
  const [latest, setLatest] = useState<Order | null>(null);
  const [message, setMessage] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const releasePanel = useTaskPanelRelease();
  const attempt = useSubmitAttempt();
  const input = orderInput(draft);
  const key = useIdempotencyKey(JSON.stringify({ id: stock.id, input }));
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (conflict || command.busy) return;
    if (!input) {
      setMessage(
        "수량은 1 이상 1,000,000 이하 정수로, 가격은 정수 원으로 입력해 주세요. 구매 링크는 https 주소를 사용해 주세요.",
      );
      attempt.reject(event.currentTarget);
      return;
    }
    setMessage("");
    const result = await command.run((signal) =>
      base
        ? api.updateConsumableOrder(
            { orderId: base.id, input, ifMatch: etag(base.version) },
            signal,
          )
        : api.createConsumableOrder(
            { input: { ...input, consumable_id: stock.id }, idempotencyKey: key },
            signal,
          ),
    );
    if (!command.mounted.current) return;
    if (result.ok) {
      guard.release();
      releasePanel();
      if (saved) saved();
      else
        navigate(`/consumable-orders/${result.value.id}`, {
          replace: true,
          state: { orderSaved: true, homecareReturnTo: backTo },
        });
    } else {
      setUncertain(!base && (result.error.status === 0 || result.error.status >= 500));
      if (base && result.error.status === 409) setConflict(true);
    }
  }
  async function compare() {
    if (!base) return;
    const result = await command.run((signal) =>
      api.getConsumableOrder({ orderId: base.id }, signal),
    );
    if (result.ok && command.mounted.current) {
      setLatest(result.value);
      // The separate conflict gate stays until explicit adoption.
    }
  }
  function adopt(keep: boolean) {
    if (!base || !latest || !["planned", "ordered"].includes(latest.state)) return;
    setDraft(
      keep ? preserveDraft(orderDraft(base), draft, orderDraft(latest)) : orderDraft(latest),
    );
    setBase(latest);
    setLatest(null);
    setConflict(false);
    command.setError(null);
  }
  const change = (field: keyof OrderDraft, value: string) =>
    setDraft((old) => ({ ...old, [field]: value }));
  return (
    <section aria-label={base ? "주문 내용 수정" : "구매 예정 입력"}>
      <h2>{base ? "주문 내용 수정" : "구매 예정 입력"}</h2>
      <p>
        {stock.name} · 수량 단위 {stock.unit}. 이 저장으로 실제 주문이나 재고 입고가 발생하지
        않아요.
      </p>
      <form
        className="finance-form"
        onInput={() => setDirty(true)}
        onSubmit={(event) => void submit(event)}
      >
        <fieldset
          className="finance-fields"
          disabled={command.busy || uncertain || stock.status !== "active"}
        >
          <legend>함께 확인할 구매 내용</legend>
          <div className="form-field">
            <label htmlFor="order-quantity">구매 수량 ({stock.unit})</label>
            <input
              id="order-quantity"
              inputMode="numeric"
              required
              value={draft.quantity}
              aria-invalid={
                (attempt.attempted && quantity(draft.quantity, true) === null) || undefined
              }
              onChange={(event) => change("quantity", event.target.value)}
            />
            {attempt.attempted && quantity(draft.quantity, true) === null && (
              <p className="field-error">1 이상 1,000,000 이하 정수로 입력해 주세요.</p>
            )}
          </div>
          <AmountField
            label="단위당 참고 가격 (원, 선택)"
            value={draft.price}
            error={
              attempt.attempted
                ? krwFieldError(draft.price, { required: false, positive: false })
                : null
            }
            onChange={(value) => change("price", value)}
          />
          <div className="form-field">
            <label htmlFor="order-url">구매 링크 (선택)</label>
            <input
              id="order-url"
              type="url"
              maxLength={2048}
              value={draft.url}
              aria-invalid={
                (attempt.attempted && Boolean(draft.url) && !purchaseUrl(draft.url)) || undefined
              }
              onChange={(event) => change("url", event.target.value)}
            />
            <p className="muted">
              https 주소를 보관해요. 실제 주문은 판매처에서 직접 진행해 주세요.
            </p>
          </div>
          <div className="form-field">
            <label htmlFor="order-note">주문 메모 (선택)</label>
            <textarea
              id="order-note"
              rows={3}
              maxLength={2000}
              value={draft.note}
              onChange={(event) => change("note", event.target.value)}
            />
          </div>
        </fieldset>
        <FormError message={message} />
        <HomecareError error={command.error} />
        {uncertain && (
          <p role="status">
            구매 예정이 이미 저장됐을 수 있어 입력을 유지했어요. 같은 내용으로 다시 확인하면 한 번만
            저장돼요.
          </p>
        )}
        {conflict && base && (
          <section className="review-panel" aria-label="주문 내용 충돌 비교">
            <h3>내 수정과 현재 주문 비교</h3>
            <p>작성한 내용을 유지했어요. 다른 기기의 변경을 확인해 주세요.</p>
            <button type="button" disabled={command.busy} onClick={() => void compare()}>
              현재 주문과 비교
            </button>
            {latest && (
              <>
                <RecordActor memberId={latest.updated_by_member_id} at={latest.updated_at} />
                <dl className="metadata-grid">
                  <div>
                    <dt>현재 상태</dt>
                    <dd>{orderStates[latest.state]}</dd>
                  </div>
                  <div>
                    <dt>내 수량 · 현재 수량</dt>
                    <dd>
                      {draft.quantity} · {latest.quantity} {stock.unit}
                    </dd>
                  </div>
                  <div>
                    <dt>내 단가 · 현재 단가</dt>
                    <dd>
                      {formatKrw(input?.unit_cost_krw ?? null)} ·{" "}
                      {formatKrw(latest.unit_cost_krw ?? null)}
                    </dd>
                  </div>
                  <div>
                    <dt>현재 구매 링크</dt>
                    <dd>{latest.purchase_url || "미입력"}</dd>
                  </div>
                  <div>
                    <dt>현재 메모</dt>
                    <dd>{latest.note || "미입력"}</dd>
                  </div>
                </dl>
                {["planned", "ordered"].includes(latest.state) ? (
                  <div className="form-actions">
                    <button type="button" onClick={() => adopt(true)}>
                      내 수정만 유지하고 현재 내용 반영
                    </button>
                    <button type="button" onClick={() => adopt(false)}>
                      내 입력 버리고 현재 내용 사용
                    </button>
                  </div>
                ) : (
                  <p>
                    이미 완료된 주문은 수정할 수 없어요. 입력 취소 후 현재 주문을 확인해 주세요.
                  </p>
                )}
              </>
            )}
          </section>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          label={
            uncertain ? "같은 구매 예정 다시 확인" : base ? "주문 내용 저장" : "구매 예정 저장"
          }
          disabled={conflict || stock.status !== "active"}
          backTo={backTo}
          onDismiss={close}
        />
      </form>
    </section>
  );
}
