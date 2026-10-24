import { FilterPanel } from "../../../shared/TaskLayout";
import { useCallback } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError } from "../../../platform/api";
import { DateInput } from "../../../shared/DateInput";
import { NameSearch } from "../../../shared/NameSearch";
import { formatSeoulDateTime } from "../../../shared/format";
import { formatKrw } from "../../assets/months/model";
import { dateLabel, isDateOnly, todaySeoul } from "../../finance/dates";
import { useResource } from "../../finance/queries";
import { HomecarePage, ResourceFeedback, useSeoulDayRefresh } from "../HomecareSupport";
import { purchaseUrl } from "../model";
import { useHomecareOrigin } from "../HomecareOutcome";
import { usePurchaseApi } from "./api";
import { completePlan, count, daysAfter, type PlanItem } from "./model";

function PlanRow({ row }: { row: PlanItem }) {
  const stock = row.consumable;
  const origin = useHomecareOrigin();
  const seed = {
    quantity: row.additional_quantity,
    unit_cost_krw: row.last_receipt?.unit_cost_krw ?? null,
    purchase_url: row.last_receipt?.purchase_url ?? null,
    note: null,
  };
  return (
    <li className="card" aria-label={`${stock.name} 구매 계획`}>
      <div className="item-heading">
        <h2>
          <Link to={`/consumables/${stock.id}`}>{stock.name}</Link>
        </h2>
        <span className="status-chip">{stock.sku_or_model || "규격 미입력"}</span>
      </div>
      <dl className="metadata-grid">
        <div>
          <dt>확인된 기간 수요</dt>
          <dd>
            {count(row.demand_quantity)} {stock.unit}
          </dd>
        </div>
        <div>
          <dt>현재 공용 재고</dt>
          <dd>
            {count(stock.stock_quantity)} {stock.unit}
          </dd>
        </div>
        <div>
          <dt>현재 재고로 부족</dt>
          <dd>
            <strong>
              {count(row.shortage_quantity)} {stock.unit}
            </strong>
          </dd>
        </div>
        <div>
          <dt>구매 예정 · 주문 중</dt>
          <dd>
            {count(row.planned_quantity)} · {count(row.ordered_quantity)} {stock.unit}
          </dd>
        </div>
        <div>
          <dt>추가 계획 참고 수량</dt>
          <dd>
            {count(row.additional_quantity)} {stock.unit}
          </dd>
        </div>
        <div>
          <dt>마지막 입고 단가</dt>
          <dd>{formatKrw(row.last_receipt?.unit_cost_krw ?? null)}</dd>
        </div>
      </dl>
      {row.unscheduled_link_count > 0 && (
        <p className="month-warning">
          다음 확인일 미정 {count(row.unscheduled_link_count)}개 연결은 수요 합계에 넣지 않았어요.
          일정을 확인한 뒤 구매량을 정해 주세요.
        </p>
      )}
      {row.open_order_count > 1 && (
        <p className="month-warning">
          진행 중인 계획·주문 {count(row.open_order_count)}건이 있어요. 중복 주문인지 함께 확인해
          주세요.
        </p>
      )}
      {row.last_receipt && (
        <p className="muted">
          마지막 유효 입고 {dateLabel(row.last_receipt.occurred_on)} ·{" "}
          <Link to={`/consumables/${stock.id}/stock/${row.last_receipt.id}`}>입고 원본</Link>
        </p>
      )}
      <div className="form-actions">
        <Link
          className="button-link"
          to={`/consumable-orders/new?consumable_id=${stock.id}`}
          state={{ ...origin, purchaseSeed: seed }}
        >
          구매 예정 추가
        </Link>
        <Link to={`/consumable-orders?consumable_id=${stock.id}`}>
          이 소모품의 진행 주문 {row.open_order_count}건
        </Link>
        {row.last_receipt?.purchase_url && purchaseUrl(row.last_receipt.purchase_url) && (
          <a href={row.last_receipt.purchase_url} target="_blank" rel="noopener noreferrer">
            마지막 구매 링크
          </a>
        )}
      </div>
      <details className="record-details">
        <summary>기기별 수요 근거</summary>
        {row.demand_sources.length ? (
          <ul>
            {row.demand_sources.map((source) => (
              <li key={source.link_id}>
                <Link to={`/appliance-consumables/${source.link_id}`}>{source.appliance_name}</Link>{" "}
                · 다음 확인 {dateLabel(source.next_check_on)} ·{" "}
                {source.quantity === null
                  ? "일정 미정"
                  : `${count(source.replacement_count!)}회 · ${count(source.quantity)} ${stock.unit}`}
              </li>
            ))}
          </ul>
        ) : (
          <p>사용 중인 기기에 연결되지 않았어요. 필요한 구매 수량은 직접 정할 수 있어요.</p>
        )}
        {row.additional_source_count > 0 && (
          <p>
            나머지 {count(row.additional_source_count)}개 연결도 함께 확인했어요.{" "}
            <Link to={`/consumables/${stock.id}`}>연결 전체 확인</Link>
          </p>
        )}
      </details>
    </li>
  );
}
function PurchasePlanWorkspace() {
  const api = usePurchaseApi();
  const [params, setParams] = useSearchParams();
  const through = params.get("through") ?? "";
  const query = params.get("q") ?? "";
  const resource = useResource(
    useCallback(() => {
      if (through && !isDateOnly(through)) throw new ApiError(422, "INVALID_HOMECARE_INPUT");
      return completePlan((cursor) =>
        api.getPurchasePlan({
          query: { ...(through ? { through } : {}), q: query || undefined, cursor, limit: 200 },
        }),
      );
    }, [api, through, query]),
  );
  useSeoulDayRefresh(resource.reload);
  function period(value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set("through", value);
    else next.delete("through");
    setParams(next);
  }
  const today = resource.data?.as_of ?? todaySeoul();
  const rows = [...(resource.data?.items ?? [])].sort(
    (a, b) =>
      b.shortage_quantity - a.shortage_quantity ||
      b.unscheduled_link_count - a.unscheduled_link_count ||
      a.consumable.name.localeCompare(b.consumable.name, "ko"),
  );
  return (
    <>
      <div className="form-actions">
        <button type="button" onClick={() => period("")}>
          오늘만 확인
        </button>
        <button type="button" onClick={() => period(daysAfter(today, 30))}>
          앞으로 30일
        </button>
        <button
          type="button"
          aria-label="구매 계획 새로고침"
          disabled={resource.loading}
          onClick={() => void resource.reload()}
        >
          새로고침
        </button>
      </div>
      <FilterPanel
        title="계획 기간·소모품 검색"
        activeCount={Number(Boolean(through)) + Number(Boolean(query))}
        defaultLabel="오늘 · 모든 소모품"
      >
        <div className="form-field">
          <label htmlFor="purchase-through">수요를 확인할 마지막 날짜</label>
          <DateInput
            id="purchase-through"
            value={through || today}
            min={today}
            max={daysAfter(today, 365)}
            onChange={(event) => period(event.target.value)}
          />
        </div>

        <p>
          같은 소모품을 쓰는 기기의 수요를 합친 뒤 공용 재고 한 번과 비교해요. 구매 예정·주문 중은
          아직 재고가 아니에요.
        </p>
        <details className="record-details">
          <summary>기간 수요 계산 기준</summary>
          <p>
            지난 교체 예정은 오늘 확인할 한 번으로 계산해요. 이후 수요는 예정일에 교체하고 현재
            주기를 유지한다는 가정이에요. 실제 교체나 재고 사용을 자동 기록하지 않아요. 직접 확인
            주기는 정한 다음 날짜 한 번만 포함해요.
          </p>
          <p>
            추가 계획 참고 수량은 현재 부족에서 구매 예정·주문 중 수량을 뺀 값이에요. 주문
            도착일이나 실제 사용량에 따라 달라질 수 있어요.
          </p>
        </details>
        <NameSearch label="구매 계획 소모품 이름·규격 검색" />
      </FilterPanel>
      <ResourceFeedback resource={resource} keepsData />
      {resource.checkedAt && (
        <p className="muted">
          최근 확인 {formatSeoulDateTime(new Date(resource.checkedAt).toISOString())} (서울)
          {resource.loading ? " · 갱신 중" : ""}
        </p>
      )}
      {resource.data && !resource.error && (
        <>
          <p>
            {dateLabel(resource.data.as_of)} ~ {dateLabel(resource.data.through)} · 소모품{" "}
            {rows.length}종
          </p>
          {rows.length ? (
            <ul className="finance-list">
              {rows.map((row) => (
                <PlanRow key={row.consumable.id} row={row} />
              ))}
            </ul>
          ) : (
            <div className="card">
              <p>선택한 조건의 사용 중인 소모품이 없어요.</p>
              <Link to="/consumables/new">소모품 등록하기</Link>
            </div>
          )}
        </>
      )}
    </>
  );
}
export function PurchasePlanPage() {
  return (
    <HomecarePage
      title="공용 소모품 구매 계획"
      description="기기별 수요를 합치고 함께 주문할 수량을 정해요."
      navigation={
        <div className="form-actions">
          <Link to="/consumable-orders">구매 예정·주문 목록</Link>
          <Link to="/consumables">공용 재고 관리</Link>
        </div>
      }
    >
      <PurchasePlanWorkspace />
    </HomecarePage>
  );
}
