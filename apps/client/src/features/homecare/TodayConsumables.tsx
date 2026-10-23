import { Icon } from "../../shared/Icon";
import { useCallback, useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../../platform/api";
import { SessionStatus } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import { dateLabel } from "../finance/dates";
import { useResource } from "../finance/queries";
import { useHomecareApi } from "./api";
import {
  attentionRank,
  compareAttention,
  dueSoon,
  matchesTodayFilter,
  type Schema,
  type TodayFilter,
} from "./model";
import { HomeWarranties } from "./HomeWarranties";
import { ResourceFeedback, useSeoulDayRefresh } from "./HomecareSupport";
export async function completeToday(
  read: (cursor?: string) => Promise<Schema["HomecareStatusResponse"]>,
): Promise<Schema["HomecareStatusResponse"]> {
  const first = await read();
  const items = [...first.items];
  let cursor = first.next_cursor;
  const seen = new Set<string>();
  while (cursor) {
    if (seen.has(cursor) || seen.size >= 100) throw new ApiError(0, "REQUEST_FAILED");
    seen.add(cursor);
    const page = await read(cursor);
    if (
      page.as_of !== first.as_of ||
      page.items.some((row) => row.as_of !== first.as_of || items.some((old) => old.id === row.id))
    )
      throw new ApiError(409, "VERSION_CONFLICT");
    items.push(...page.items);
    cursor = page.next_cursor;
  }
  if (items.some((row) => row.as_of !== first.as_of)) throw new ApiError(409, "VERSION_CONFLICT");
  return { ...first, items, next_cursor: null };
}
function TodayList({ compact }: { compact: boolean }) {
  const api = useHomecareApi();
  const [filter, setFilter] = useState<TodayFilter>("attention");
  const resource = useResource(
    useCallback(
      () => completeToday((cursor) => api.getHomecareStatus({ query: { cursor, limit: 200 } })),
      [api],
    ),
  );
  useSeoulDayRefresh(resource.reload);
  const shown =
    resource.data?.items.filter((row) => matchesTodayFilter(row, filter)).sort(compareAttention) ??
    [];
  const filterControl = (
    <div className="form-field">
      <label>
        오늘 소모품 보기
        <select value={filter} onChange={(e) => setFilter(e.target.value as TodayFilter)}>
          <option value="attention">확인할 항목</option>
          <option value="due">교체 확인 필요</option>
          <option value="soon">곧 교체</option>
          <option value="purchase">구매 필요</option>
          <option value="unknown">교체일 미확인</option>
          <option value="all">모든 연결</option>
        </select>
      </label>
    </div>
  );
  const attentionCount = resource.data?.items.filter((row) => attentionRank(row) < 5).length;
  return (
    <div aria-busy={resource.loading}>
      <ResourceFeedback resource={resource} keepsData />
      {resource.data && !resource.error && (
        <>
          <div className="care-summary">
            <p className="eyebrow">오늘 기준 · {dateLabel(resource.data.as_of)}</p>
            {compact && (
              <p className="care-count" role="status">
                확인할 소모품 <strong>{attentionCount}개</strong>
              </p>
            )}
          </div>
          {!compact && filterControl}
          {!resource.data.items.length ? (
            <p>
              사용 중인 가전과 소모품 연결이 없어요. 소모품을 기기에 연결하면 여기서 오늘 상태를
              확인할 수 있어요.
            </p>
          ) : !shown.length ? (
            <p>선택한 조건에 해당하는 소모품이 없어요. 모든 연결에서 다음 확인일을 볼 수 있어요.</p>
          ) : (
            <ul className={`finance-list care-list${compact ? " compact" : ""}`}>
              {shown.slice(0, compact ? 4 : undefined).map((row) => (
                <li className="care-row" key={row.id}>
                  <div className="care-row-heading">
                    <span className="care-item-icon">
                      <Icon name="package" />
                    </span>
                    <h3>
                      <Link to={`/appliance-consumables/${row.id}`}>
                        {row.appliance_name} · {row.consumable_name}
                      </Link>
                    </h3>
                  </div>
                  <p
                    className="care-status"
                    data-attention={
                      row.purchase_needed
                        ? "purchase"
                        : row.replacement_due === null
                          ? "unknown"
                          : row.replacement_due
                            ? "due"
                            : dueSoon(row)
                              ? "soon"
                              : "ready"
                    }
                  >
                    {row.replacement_due === null
                      ? "교체 기준일 미확인"
                      : row.replacement_due
                        ? "교체 확인 필요"
                        : dueSoon(row)
                          ? "곧 교체"
                          : "다음 확인일 전"}{" "}
                    · {row.purchase_needed ? "교체 수량 부족 · 구매 필요" : "교체할 재고 있음"}
                    {row.low_stock && " · 재고 부족 임계 이하"}
                  </p>
                  <p className="care-item-meta">
                    {row.appliance_location || "장소 미입력"} · {row.sku_or_model || "규격 미입력"}
                  </p>
                  <p className="care-item-stock">
                    다음 확인 {row.next_check_on ? dateLabel(row.next_check_on) : "미확인"} · 공용
                    재고 {row.stock_quantity.toLocaleString("ko-KR")} {row.unit}
                  </p>
                  <div className="form-actions care-item-actions">
                    <Link to={`/appliance-consumables/${row.id}/replace`}>교체 기록</Link>
                    <Link to={`/consumables/${row.consumable_id}/stock/new`}>입고 기록</Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {compact && shown.length > 4 && (
            <p>
              <Link to="/consumables">나머지 {shown.length - 4}개 확인할 소모품 보기</Link>
            </p>
          )}
          {compact && filterControl}
          <button type="button" onClick={() => void resource.reload()}>
            오늘 소모품 상태 새로 확인
          </button>
        </>
      )}
    </div>
  );
}
export function TodayConsumables({ compact = false }: { compact?: boolean }) {
  const { state } = useAuth();
  return (
    <section
      className={`card today-card${compact ? " home-today" : ""}`}
      aria-labelledby={compact ? "consumables-title" : "today-consumables-title"}
    >
      <div className="section-title">
        <div>
          <p className="eyebrow">오늘 기준</p>
          <h2 id={compact ? "consumables-title" : "today-consumables-title"}>살펴볼 소모품</h2>
        </div>
        <span className="section-icon warm">
          <Icon name="package" size={22} />
        </span>
      </div>
      {!compact && (
        <p className="muted care-intro">
          과거 자산 월을 골라도 소모품은 서울의 오늘 상태예요. 직접 정한 교체 기준과 현재 공용
          재고를 확인해요.
        </p>
      )}
      {state.status === "authenticated" ? (
        <>
          <TodayList compact={compact} />
          {compact && (
            <>
              <details className="care-help">
                <summary>오늘 기준 안내</summary>
                <p className="muted care-intro">
                  과거 자산 월을 골라도 소모품은 서울의 오늘 상태예요. 직접 정한 교체 기준과 현재
                  공용 재고를 확인해요.
                </p>
              </details>
              <HomeWarranties />
            </>
          )}
        </>
      ) : compact ? (
        <>
          <p>로그인하면 우리 가계의 공용 재고와 기기별 교체 상태를 확인할 수 있어요.</p>
          <Link to="/login">로그인하기</Link>
        </>
      ) : (
        <SessionStatus />
      )}
      <Link className="button-link" to={compact ? "/consumables" : "/appliances"}>
        {compact ? "소모품 전체 관리" : "가전에 소모품 연결하기"}
      </Link>
    </section>
  );
}
