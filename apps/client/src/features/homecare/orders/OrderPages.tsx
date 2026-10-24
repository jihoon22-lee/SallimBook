import { useCallback, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router";
import { ApiError } from "../../../platform/api";
import { NameSearch } from "../../../shared/NameSearch";
import { RecordActor } from "../../../shared/RecordActor";
import { TaskPanel } from "../../../shared/TaskLayout";
import { useRouteNotice } from "../../../shared/routeNotice";
import { formatKrw, parseKrw } from "../../assets/months/model";
import { dateLabel, isUuid } from "../../finance/dates";
import {
  MemberLoadError,
  useHouseholdMembers,
  type HouseholdMember,
} from "../../finance/FinanceSupport";
import { usePagedList, useResource } from "../../finance/queries";
import { useHomecareApi } from "../api";
import { useHomecareOrigin, useHomecareReturn } from "../HomecareOutcome";
import { HomecarePage, ListFeedback, ResourceFeedback } from "../HomecareSupport";
import { purchaseUrl, quantity, type Consumable } from "../model";
import { StockSummary } from "../StockPages";
import { usePurchaseApi } from "./api";
import { count, orderStates, type Order, type OrderDraft } from "./model";
import { OrderEditor } from "./OrderEditor";
import { OrderCommand, type OrderAction } from "./OrderCommand";

function memberName(id: string | null, members: HouseholdMember[]) {
  return members.find((member) => member.member_id === id)?.display_name ?? "구성원 확인 필요";
}
function Actors({ row, members }: { row: Order; members: HouseholdMember[] }) {
  return (
    <p className="muted">
      작성자 {memberName(row.created_by_member_id, members)}
      {row.ordered_by_member_id && <> · 주문자 {memberName(row.ordered_by_member_id, members)}</>}
      {row.received_by_member_id && (
        <> · 입고 기록자 {memberName(row.received_by_member_id, members)}</>
      )}
    </p>
  );
}
function OrderList() {
  const api = usePurchaseApi();
  const members = useHouseholdMembers();
  const origin = useHomecareOrigin();
  const [params, setParams] = useSearchParams();
  const raw = params.get("state") ?? "open";
  const state = ["open", "all", ...Object.keys(orderStates)].includes(raw)
    ? (raw as "open" | "all" | Order["state"])
    : "open";
  const stockId = params.get("consumable_id") ?? "";
  const q = params.get("q") ?? "";
  const list = usePagedList(
    useCallback(
      (cursor?: string) => {
        if (stockId && !isUuid(stockId)) throw new ApiError(422, "INVALID_HOMECARE_INPUT");
        return api.listConsumableOrders({
          query: {
            state,
            consumable_id: stockId || undefined,
            q: q || undefined,
            cursor,
            limit: 50,
          },
        });
      },
      [api, state, stockId, q],
    ),
    undefined,
    `consumable-orders:${params.toString()}`,
  );
  return (
    <>
      <NameSearch label="주문 소모품 이름·규격 검색" />
      <section className="card" aria-label="주문 상태 필터">
        <div className="form-field">
          <label htmlFor="order-state-filter">구매·주문 상태</label>
          <select
            id="order-state-filter"
            value={state}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              next.set("state", event.target.value);
              setParams(next);
            }}
          >
            <option value="open">구매 예정·주문 중</option>
            {Object.entries(orderStates).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
            <option value="all">모든 기록</option>
          </select>
        </div>
        {stockId && (
          <p>
            선택한 소모품의 주문을 보고 있어요.{" "}
            <Link to="/consumable-orders">전체 소모품 주문</Link>
          </p>
        )}
        <button type="button" disabled={list.loading} onClick={() => void list.reload()}>
          주문 목록 새로고침
        </button>
      </section>
      <MemberLoadError error={members.error} retry={members.retry} />
      <ul className="finance-list">
        {list.items.map((row) => (
          <li className="card" key={row.id}>
            <div className="item-heading">
              <h2>
                <Link to={`/consumable-orders/${row.id}`} state={origin}>
                  {row.consumable_name} · {count(row.quantity)} {row.unit}
                </Link>
              </h2>
              <span className="status-chip">
                {row.receipt_reversed_by ? "입고 취소됨 · 원본 보존" : orderStates[row.state]}
              </span>
            </div>
            <p>
              {row.sku_or_model || "규격 미입력"} · 단가 {formatKrw(row.unit_cost_krw ?? null)}
            </p>
            <Actors row={row} members={members.members} />
            <p>
              주문일 {dateLabel(row.ordered_on)} · 입고일 {dateLabel(row.received_on)}
            </p>
            <RecordActor memberId={row.updated_by_member_id} at={row.updated_at} />
          </li>
        ))}
      </ul>
      <ListFeedback
        list={list}
        empty="이 조건의 구매·주문 기록이 없어요. 구매 계획에서 소모품을 선택해 예정 수량을 추가할 수 있어요."
      />
    </>
  );
}
export function OrderListPage() {
  return (
    <HomecarePage
      title="구매 예정·주문 목록"
      description="누가 주문했는지 함께 확인하고 실제 도착했을 때 입고해요."
      navigation={
        <div className="form-actions">
          <Link className="button-link" to="/purchase-plan">
            구매 계획에서 예정 추가
          </Link>
          <Link to="/consumables">공용 재고 관리</Link>
        </div>
      }
    >
      <OrderList />
    </HomecarePage>
  );
}
function seedDraft(value: unknown): OrderDraft | undefined {
  if (!value || typeof value !== "object") return;
  const seed = value as Record<string, unknown>;
  return {
    quantity:
      typeof seed.quantity === "number" && quantity(String(seed.quantity), true) !== null
        ? String(seed.quantity)
        : "",
    price:
      typeof seed.unit_cost_krw === "string" && parseKrw(seed.unit_cost_krw) !== null
        ? seed.unit_cost_krw
        : "",
    url:
      typeof seed.purchase_url === "string" && purchaseUrl(seed.purchase_url)
        ? seed.purchase_url
        : "",
    note: "",
  };
}
function NewOrder() {
  const inventory = useHomecareApi();
  const [params] = useSearchParams();
  const location = useLocation();
  const backTo = useHomecareReturn() ?? "/purchase-plan";
  const id = params.get("consumable_id") ?? "";
  const resource = useResource(
    useCallback(() => {
      if (!isUuid(id)) throw new ApiError(422, "INVALID_HOMECARE_INPUT");
      return inventory.getConsumable({ consumableId: id });
    }, [inventory, id]),
  );
  return (
    <>
      <ResourceFeedback resource={resource} keepsData />
      {resource.data && (
        <div className="card">
          <StockSummary row={resource.data} />
          <OrderEditor
            key={resource.data.id}
            stock={resource.data}
            seed={seedDraft(location.state?.purchaseSeed)}
            backTo={backTo}
          />
        </div>
      )}
      <Link to={backTo}>구매 계획으로 돌아가기</Link>
    </>
  );
}
export function OrderNewPage() {
  return (
    <HomecarePage
      title="구매 예정 추가"
      description="수량과 참고 가격을 검토해 부부가 함께 볼 구매 계획으로 저장해요."
    >
      <NewOrder />
    </HomecarePage>
  );
}
type Current = { order: Order; stock: Consumable };
type Panel = { action: OrderAction | "edit"; initial: Current };
function Detail({ id }: { id: string }) {
  const api = usePurchaseApi();
  const inventory = useHomecareApi();
  const members = useHouseholdMembers();
  const returnPath = useHomecareReturn();
  const [backTo] = useState(returnPath ?? "/purchase-plan");
  const justCreated = useRouteNotice(
    (state) => Boolean((state as { orderSaved?: boolean } | null)?.orderSaved) || null,
  );
  const [notice, setNotice] = useState("");
  const [panel, setPanel] = useState<Panel | null>(null);
  const resource = useResource(
    useCallback(async () => {
      if (!isUuid(id)) throw new ApiError(422, "INVALID_HOMECARE_INPUT");
      const order = await api.getConsumableOrder({ orderId: id });
      const stock = await inventory.getConsumable({ consumableId: order.consumable_id });
      return { order, stock };
    }, [api, inventory, id]),
  );
  function saved(action: Panel["action"]) {
    setPanel(null);
    setNotice(
      action === "receive"
        ? "전체 입고 기록을 저장했어요. 현재 공용 재고를 다시 확인하고 있어요."
        : action === "submit"
          ? "주문 중으로 저장했어요. 아직 재고에는 반영하지 않았어요."
          : action === "cancel"
            ? "주문 취소를 기록했어요."
            : "주문 내용을 저장했어요.",
    );
    void resource.reload();
  }
  const current = resource.data;
  const row = current?.order;
  const blocked = resource.loading || Boolean(resource.error) || Boolean(panel);
  return (
    <>
      {(justCreated || notice) && (
        <p role="status">
          {notice || "구매 예정을 저장했어요. 실제 주문 후 주문 중으로 표시해 주세요."}
        </p>
      )}
      <ResourceFeedback resource={resource} keepsData />
      {resource.loading && current && (
        <p role="status">기존 내용을 유지하며 현재 주문·재고를 확인하고 있어요.</p>
      )}
      {current && row && (
        <>
          <section className="card" aria-label="소모품 주문 원본">
            <div className="item-heading">
              <h2>{row.consumable_name}</h2>
              <span className="status-chip">
                {row.receipt_reversed_by ? "입고 취소됨 · 원본 보존" : orderStates[row.state]}
              </span>
            </div>
            <Actors row={row} members={members.members} />
            <MemberLoadError error={members.error} retry={members.retry} />
            <dl className="metadata-grid">
              <div>
                <dt>주문 수량</dt>
                <dd>
                  {count(row.quantity)} {row.unit}
                </dd>
              </div>
              <div>
                <dt>단위당 참고 가격</dt>
                <dd>{formatKrw(row.unit_cost_krw ?? null)}</dd>
              </div>
              <div>
                <dt>규격</dt>
                <dd>{row.sku_or_model || "미입력"}</dd>
              </div>
              <div>
                <dt>실제 주문일</dt>
                <dd>{dateLabel(row.ordered_on)}</dd>
              </div>
              <div>
                <dt>실제 입고일</dt>
                <dd>{dateLabel(row.received_on)}</dd>
              </div>
              <div>
                <dt>메모</dt>
                <dd>{row.note || "미입력"}</dd>
              </div>
              {row.cancel_reason && (
                <div>
                  <dt>취소 사유</dt>
                  <dd>{row.cancel_reason}</dd>
                </div>
              )}
            </dl>
            <RecordActor memberId={row.created_by_member_id} at={row.created_at} label="작성" />
            <RecordActor memberId={row.updated_by_member_id} at={row.updated_at} />
            <StockSummary row={current.stock} />
            <div className="form-actions">
              {row.state === "planned" && (
                <button
                  type="button"
                  className="primary-button"
                  disabled={blocked || current.stock.status !== "active"}
                  onClick={() => setPanel({ action: "submit", initial: current })}
                >
                  실제 주문 확인
                </button>
              )}
              {row.state === "ordered" && (
                <button
                  type="button"
                  className="primary-button"
                  disabled={blocked || current.stock.status !== "active"}
                  onClick={() => setPanel({ action: "receive", initial: current })}
                >
                  전체 입고 확인
                </button>
              )}
              {["planned", "ordered"].includes(row.state) && (
                <>
                  <button
                    type="button"
                    disabled={blocked || current.stock.status !== "active"}
                    onClick={() => setPanel({ action: "edit", initial: current })}
                  >
                    주문 내용 수정
                  </button>
                  <button
                    type="button"
                    disabled={blocked}
                    onClick={() => setPanel({ action: "cancel", initial: current })}
                  >
                    주문 취소 검토
                  </button>
                </>
              )}
              {row.purchase_url && purchaseUrl(row.purchase_url) && (
                <a href={row.purchase_url} target="_blank" rel="noopener noreferrer">
                  기록한 구매 링크 열기
                </a>
              )}
              <button
                type="button"
                disabled={resource.loading}
                onClick={() => void resource.reload()}
              >
                주문·재고 새로고침
              </button>
            </div>
            {current.stock.status !== "active" && (
              <p>
                사용 종료된 소모품이에요. 새 주문·입고 전에 소모품의 사용 상태를 먼저 확인해 주세요.
              </p>
            )}
            {row.stock_movement_id && (
              <p>
                <Link to={`/consumables/${row.consumable_id}/stock/${row.stock_movement_id}`}>
                  연결된 입고 원본과 취소 기록
                </Link>
              </p>
            )}
            {row.receipt_reversed_by && (
              <p className="month-warning">
                이 입고는 재고 원장에서 취소됐어요. 구매·입고 원본은 보존하며 다시 필요하면 새
                계획을 추가해 주세요.
              </p>
            )}
          </section>
          {panel && (
            <TaskPanel
              label={panel.action === "edit" ? "주문 내용 수정 작업" : "주문 상태 확인 작업"}
            >
              {panel.action === "edit" ? (
                <OrderEditor
                  stock={panel.initial.stock}
                  initial={panel.initial.order}
                  backTo={backTo}
                  saved={() => saved("edit")}
                  close={() => setPanel(null)}
                />
              ) : (
                <OrderCommand
                  order={panel.initial.order}
                  stock={panel.initial.stock}
                  action={panel.action}
                  saved={() => saved(panel.action)}
                  close={() => setPanel(null)}
                />
              )}
            </TaskPanel>
          )}
          <div className="form-actions">
            <Link to={backTo}>시작 화면으로 돌아가기</Link>
            <Link to="/consumable-orders">구매·주문 목록</Link>
            <Link to={`/consumables/${row.consumable_id}`}>이 소모품의 공용 재고·기기 연결</Link>
          </div>
        </>
      )}
    </>
  );
}
export function OrderDetailPage() {
  const { id = "" } = useParams();
  return (
    <HomecarePage
      title="소모품 주문 상세"
      description="구매 예정과 실제 주문, 재고에 반영한 입고를 구분해요."
    >
      <Detail key={id} id={id} />
    </HomecarePage>
  );
}
