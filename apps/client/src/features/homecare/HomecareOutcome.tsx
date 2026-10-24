import { useCallback } from "react";
import { Link, useLocation } from "react-router";
import { useRouteNotice } from "../../shared/routeNotice";
import { isUuid, dateLabel } from "../finance/dates";
import { useResource } from "../finance/queries";
import { useHomecareApi } from "./api";
import { ResourceFeedback } from "./HomecareSupport";
import { movementLabels, type Schema } from "./model";

export type StockOutcome = Schema["StockMutationReference"] & { linkId?: string };
export function useHomecareOrigin() {
  const location = useLocation();
  return { homecareReturnTo: `${location.pathname}${location.search}${location.hash}` };
}
export function useHomecareReturn(): string | null {
  const value: unknown = useLocation().state?.homecareReturnTo;
  if (typeof value !== "string" || value.includes("\\") || /[\r\n]/.test(value)) return null;
  const path = value.split(/[?#]/, 1)[0] ?? "";
  return path === "/" ||
    path === "/purchase-plan" ||
    /^\/(?:consumables|appliances|appliance-consumables|consumable-orders)(?:\/[0-9a-f-]{36})?$/.test(
      path,
    )
    ? value
    : null;
}
function pickOutcome(state: unknown): StockOutcome | null {
  const value = (state as { homecareOutcome?: StockOutcome } | null)?.homecareOutcome;
  return value &&
    isUuid(value.id) &&
    isUuid(value.consumable_id) &&
    Number.isSafeInteger(value.stock_version) &&
    (!value.linkId || isUuid(value.linkId))
    ? value
    : null;
}
export function HomecareOutcome() {
  const outcome = useRouteNotice(pickOutcome);
  return outcome ? (
    <Outcome key={`${outcome.id}:${outcome.stock_version}`} outcome={outcome} />
  ) : null;
}
function Outcome({ outcome }: { outcome: StockOutcome }) {
  const api = useHomecareApi();
  const result = useResource(
    useCallback(async () => {
      const [stock, movement, link] = await Promise.all([
        api.getConsumable({ consumableId: outcome.consumable_id }),
        api.getStockMovement({ consumableId: outcome.consumable_id, movementId: outcome.id }),
        outcome.linkId ? api.getApplianceConsumable({ linkId: outcome.linkId }) : null,
      ]);
      return { stock, movement, link };
    }, [api, outcome.consumable_id, outcome.id, outcome.linkId]),
  );
  const data = result.data;
  return (
    <section className="card review-panel" aria-label="재고 저장 결과">
      <h2>재고 기록을 저장했어요</h2>
      <ResourceFeedback resource={result} />
      {result.error && <p>저장은 완료됐어요. 현재 수량 확인만 다시 시도해 주세요.</p>}
      {data && !result.error && !result.loading && (
        <>
          <p>
            {data.stock.name} · {movementLabels[data.movement.kind]}{" "}
            {data.movement.quantity_delta > 0 ? "+" : ""}
            {data.movement.quantity_delta}
            {data.stock.unit}
          </p>
          {data.stock.version === data.movement.stock_version ? (
            <p role="status">
              공용 재고 {data.stock.stock_quantity - data.movement.quantity_delta} →{" "}
              {data.stock.stock_quantity}
              {data.stock.unit}
            </p>
          ) : (
            <p role="status">
              현재 공용 재고 {data.stock.stock_quantity}
              {data.stock.unit} · 이 기록 이후의 변경도 포함돼요.
            </p>
          )}
          {data.link ? (
            <p>
              다음 확인{" "}
              {data.link.next_check_on ? dateLabel(data.link.next_check_on) : "기준일 미확인"}
            </p>
          ) : (
            <p>입고·조정으로 기기의 교체일은 바뀌지 않아요.</p>
          )}
          <div className="form-actions">
            <Link to={`/consumables/${data.stock.id}/stock/${data.movement.id}`}>
              저장한 재고 기록 보기
            </Link>
            <Link
              to={
                data.link
                  ? `/appliance-consumables/${data.link.id}`
                  : `/consumables/${data.stock.id}`
              }
            >
              {data.link ? "기기별 주기 확인" : "공용 재고·기기 연결 확인"}
            </Link>
          </div>
        </>
      )}
    </section>
  );
}
