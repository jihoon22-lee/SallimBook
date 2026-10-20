import { useCallback } from "react";
import { Link } from "react-router";
import { ApiError } from "../../platform/api";
import { dateLabel } from "../finance/dates";
import { allPages, useResource } from "../finance/queries";
import { useHomecareApi } from "./api";
import { ResourceFeedback, useSeoulDayRefresh } from "./HomecareSupport";
import { warrantyLabels } from "./model";
export function HomeWarranties() {
  const api = useHomecareApi();
  const resource = useResource(
    useCallback(async () => {
      const rows = await allPages((cursor) =>
        api.listAppliances({ query: { status: "active", cursor, limit: 200 } }),
      );
      if (rows.some((row) => row.as_of !== rows[0]?.as_of))
        throw new ApiError(409, "VERSION_CONFLICT");
      return rows;
    }, [api]),
  );
  useSeoulDayRefresh(resource.reload);
  const rows = [...(resource.data ?? [])].sort(
    (a, b) =>
      Number(b.warranty_status === "expired") - Number(a.warranty_status === "expired") ||
      (a.warranty_until ?? "9999").localeCompare(b.warranty_until ?? "9999"),
  );
  return (
    <details className="home-warranties">
      <summary>가전 보증 기한 확인</summary>
      <ResourceFeedback resource={resource} />
      {resource.data && !resource.loading && !resource.error && (
        <>
          {!rows.length ? (
            <p>사용 중인 가전이 없어요.</p>
          ) : (
            <>
              <p className="muted">
                {dateLabel(rows[0]!.as_of)} 기준 · 기록한 보증기한을 표시해요. 실제 보증 범위는 구매
                문서로 확인해 주세요.
              </p>
              <ul>
                {rows.slice(0, 3).map((row) => (
                  <li key={row.id}>
                    <Link to={`/appliances/${row.id}`}>
                      {row.name} · {warrantyLabels[row.warranty_status]}
                    </Link>
                    <p>{dateLabel(row.warranty_until ?? null)}</p>
                  </li>
                ))}
              </ul>
              {rows.length > 3 && (
                <p>이외 {rows.length - 3}개 가전의 기한은 가전 목록에서 확인해 주세요.</p>
              )}
            </>
          )}
        </>
      )}
      <Link to="/appliances">가전 구매·보증 목록</Link>
    </details>
  );
}
