import { useState, type FormEvent } from "react";
import { DateInput } from "../../../shared/DateInput";
import { FormError, useSubmitAttempt } from "../../../shared/formValidation";
import { RecordActor } from "../../../shared/RecordActor";
import { useTaskPanelRelease } from "../../../shared/TaskLayout";
import { useIdempotencyKey, useMonthCommand } from "../../assets/months/useMonthCommand";
import { SaveControls } from "../../finance/FinancialFeedback";
import { dateLabel, isDateOnly, todaySeoul } from "../../finance/dates";
import { useHomecareApi } from "../api";
import { HomecareError } from "../HomecareSupport";
import { etag, type Consumable } from "../model";
import { usePurchaseApi } from "./api";
import { count, orderStates, type Order } from "./model";
export type OrderAction = "submit" | "receive" | "cancel";
const titles = {
  submit: "실제 주문 확인",
  receive: "전체 입고 확인",
  cancel: "구매 예정·주문 취소",
};
export function OrderCommand({
  order,
  stock,
  action,
  saved,
  close,
}: {
  order: Order;
  stock: Consumable;
  action: OrderAction;
  saved: () => void;
  close: () => void;
}) {
  const api = usePurchaseApi();
  const inventory = useHomecareApi();
  const command = useMonthCommand();
  const releasePanel = useTaskPanelRelease();
  const [base, setBase] = useState({ order, stock });
  const [latest, setLatest] = useState<typeof base | null>(null);
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [message, setMessage] = useState("");
  const attempt = useSubmitAttempt();
  const key = useIdempotencyKey(
    JSON.stringify({
      id: base.order.id,
      version: base.order.version,
      stock: action === "receive" ? base.stock.version : null,
      action,
      date,
      reason,
    }),
  );
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (command.busy || conflict) return;
    if (
      action === "cancel"
        ? !reason.trim()
        : !ack ||
          !isDateOnly(date) ||
          date > todaySeoul() ||
          (action === "receive" && date < (base.order.ordered_on ?? ""))
    ) {
      setMessage(
        action === "cancel"
          ? "취소 사유를 입력해 주세요."
          : "실제 날짜와 수량·상태를 확인해 주세요. 입고일은 주문일보다 빠를 수 없어요.",
      );
      attempt.reject(event.currentTarget);
      return;
    }
    setMessage("");
    const result = await command.run((signal) => {
      const options = {
        orderId: base.order.id,
        ifMatch: etag(base.order.version),
        idempotencyKey: key,
      };
      if (action === "submit")
        return api.submitConsumableOrder({ ...options, input: { ordered_on: date } }, signal);
      if (action === "receive")
        return api.receiveConsumableOrder(
          { ...options, input: { received_on: date, stock_version: base.stock.version } },
          signal,
        );
      return api.cancelConsumableOrder({ ...options, input: { reason: reason.trim() } }, signal);
    });
    if (!command.mounted.current) return;
    if (result.ok) {
      releasePanel();
      saved();
    } else {
      if (result.error.status === 409) setConflict(true);
      setUncertain(result.error.status === 0 || result.error.status >= 500);
    }
  }
  async function compare() {
    const result = await command.run(async (signal) => {
      const [currentOrder, currentStock] = await Promise.all([
        api.getConsumableOrder({ orderId: order.id }, signal),
        inventory.getConsumable({ consumableId: stock.id }, signal),
      ]);
      return { order: currentOrder, stock: currentStock };
    });
    if (result.ok && command.mounted.current) setLatest(result.value);
  }
  const canAdopt =
    latest &&
    (action === "cancel"
      ? ["planned", "ordered"].includes(latest.order.state)
      : latest.stock.status === "active" &&
        latest.order.state === (action === "submit" ? "planned" : "ordered"));
  return (
    <section aria-label={titles[action]}>
      <h2>{titles[action]}</h2>
      <p>
        {base.order.consumable_name} · {count(base.order.quantity)} {base.order.unit}
      </p>
      {action === "receive" ? (
        <>
          <p>
            현재 공용 재고 {count(base.stock.stock_quantity)} {base.stock.unit}. 도착한 전체 수량{" "}
            {count(base.order.quantity)} {base.order.unit}만 재고 입고로 기록해요.
          </p>
          <p className="muted">
            일부만 도착했다면 먼저 주문 내용을 도착한 묶음 수량으로 수정하고 나머지는 별도 주문으로
            남겨 주세요. 교체일·자산·수입·납부는 바뀌지 않아요.
          </p>
        </>
      ) : action === "submit" ? (
        <p>판매처에서 실제 주문을 마친 뒤 표시해요. 주문 중에는 재고가 늘어나지 않아요.</p>
      ) : (
        <p>구매 계획·주문 상태만 취소해요. 판매처의 실제 주문은 별도로 취소해 주세요.</p>
      )}
      <form className="finance-form" onSubmit={(event) => void submit(event)}>
        <fieldset className="finance-fields" disabled={command.busy || uncertain}>
          <legend>{titles[action]} 입력</legend>
          {action === "cancel" ? (
            <div className="form-field">
              <label htmlFor="order-cancel-reason">주문 취소 사유</label>
              <textarea
                id="order-cancel-reason"
                required
                maxLength={500}
                rows={3}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </div>
          ) : (
            <>
              <div className="form-field">
                <label htmlFor="order-actual-date">
                  {action === "submit" ? "실제 주문일" : "실제 입고일"}
                </label>
                <DateInput
                  id="order-actual-date"
                  required
                  value={date}
                  min={action === "receive" ? (base.order.ordered_on ?? undefined) : undefined}
                  max={todaySeoul()}
                  onChange={(event) => setDate(event.target.value)}
                />
                <button type="button" onClick={() => setDate(todaySeoul())}>
                  오늘 날짜 사용
                </button>
              </div>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  required
                  checked={ack}
                  onChange={(event) => setAck(event.target.checked)}
                />
                {action === "submit"
                  ? "판매처에서 실제 주문을 완료한 것을 확인했어요"
                  : "표시된 전체 수량이 도착했고 재고에 더할 것을 확인했어요"}
              </label>
            </>
          )}
        </fieldset>
        <FormError message={message} />
        <HomecareError error={command.error} />
        {uncertain && (
          <p role="status">
            반영됐을 수 있어 입력을 유지했어요. 같은 내용으로 다시 확인하면 한 번만 처리돼요.
          </p>
        )}
        {conflict && (
          <section className="review-panel" aria-label="주문·재고 충돌 비교">
            <h3>현재 주문과 재고 확인</h3>
            <p>날짜와 사유를 유지했어요. 상태·수량 변경을 먼저 확인해 주세요.</p>
            <button type="button" disabled={command.busy} onClick={() => void compare()}>
              현재 주문·재고와 비교
            </button>
            {latest && (
              <>
                <RecordActor
                  memberId={latest.order.updated_by_member_id}
                  at={latest.order.updated_at}
                />
                <dl className="metadata-grid">
                  <div>
                    <dt>현재 주문 상태</dt>
                    <dd>{orderStates[latest.order.state]}</dd>
                  </div>
                  <div>
                    <dt>검토했던 수량 · 현재 수량</dt>
                    <dd>
                      {count(base.order.quantity)} · {count(latest.order.quantity)} {stock.unit}
                    </dd>
                  </div>
                  <div>
                    <dt>검토했던 재고 · 현재 재고</dt>
                    <dd>
                      {count(base.stock.stock_quantity)} · {count(latest.stock.stock_quantity)}{" "}
                      {stock.unit}
                    </dd>
                  </div>
                  <div>
                    <dt>현재 주문일</dt>
                    <dd>{dateLabel(latest.order.ordered_on)}</dd>
                  </div>
                </dl>
                {canAdopt ? (
                  <button
                    type="button"
                    onClick={() => {
                      setBase(latest);
                      setLatest(null);
                      setConflict(false);
                      setAck(false);
                      command.setError(null);
                    }}
                  >
                    확인한 현재 기록으로 다시 검토
                  </button>
                ) : (
                  <p>
                    현재 상태에서는 이 작업을 다시 할 수 없어요. 입력 취소 후 현재 기록을 확인해
                    주세요.
                  </p>
                )}
              </>
            )}
          </section>
        )}
        <SaveControls
          busy={command.busy}
          cancel={command.cancel}
          disabled={conflict}
          label={
            uncertain
              ? "같은 주문 처리 다시 확인"
              : action === "receive"
                ? "전체 입고·재고 저장"
                : action === "submit"
                  ? "주문 중으로 저장"
                  : "주문 취소 저장"
          }
          onDismiss={close}
        />
      </form>
    </section>
  );
}
