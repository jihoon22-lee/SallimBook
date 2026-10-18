import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { SessionStatus, useMounted } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import { todaySeoul } from "../finance/dates";
import { FinanceError } from "../finance/FinanceSupport";
export function HomecarePage({ title, children, description, navigation }: { title: string; description: string; children: ReactNode; navigation?: ReactNode }) {
  const { state } = useAuth(); return <><div className="intro"><p className="eyebrow">우리 집 물건과 공용 재고</p><h1>{title}</h1><p>{description}</p></div>{navigation}{state.status === "authenticated" ? children : <SessionStatus />}</>;
}
export function HomecareError({ error }: { error: ApiError | null }) {
  const messages: Partial<Record<ApiError["code"], string>> = {
    APPLIANCE_IN_USE: "연결 소모품이나 사용·문서 이력이 있는 가전은 삭제할 수 없어요. 사용 종료로 기록을 보존해 주세요.",
    CONSUMABLE_IN_USE: "기기 연결이나 재고·문서 이력이 있는 소모품은 삭제할 수 없어요. 사용 종료로 기록을 보존해 주세요.",
    APPLIANCE_CONSUMABLE_IN_USE: "교체 이력이 있는 기기 연결은 삭제할 수 없어요. 연결 사용을 중지하면 과거 기록을 보존할 수 있어요.",
    REQUEST_CANCELLED: "요청 대기를 중단했어요. 서버에 반영됐을 수 있으니 현재 기록을 확인해 주세요. 같은 재고 입력으로 재시도하면 같은 작업을 확인해요.",
    INVALID_HOMECARE_DATE: "실제 구매·사용 종료·입고·교체·취소 날짜는 서울 기준 오늘을 넘을 수 없어요.",
    INVALID_HOMECARE_INPUT: "제품 정보와 수량·주기·날짜를 확인해 주세요.",
    APPLIANCE_UNAVAILABLE: "사용 중인 가전을 선택해 주세요. 종료된 가전의 과거 기록은 보존돼요.",
    CONSUMABLE_UNAVAILABLE: "사용 중인 소모품을 선택해 주세요. 종료된 소모품의 재고 이력은 보존돼요.",
    APPLIANCE_CONSUMABLE_UNAVAILABLE: "중지된 기기 연결이에요. 주기 설정에서 연결을 다시 사용한 뒤 교체해 주세요.",
    CONSUMABLE_SKU_EXISTS: "이미 등록한 규격이에요. 기존 소모품의 공용 재고를 확인해 주세요.",
    CONSUMABLE_UNIT_IN_USE: "재고 이력이 있어 단위를 바꿀 수 없어요. 기존 단위를 유지해 주세요.",
    APPLIANCE_CONSUMABLE_EXISTS: "이미 연결한 소모품이에요. 중지된 연결도 목록에서 다시 사용할 수 있어요.",
    INSUFFICIENT_STOCK: "공용 재고가 부족해요. 다른 기기의 사용과 현재 재고를 확인한 뒤 입고하거나 사용 수량을 조정해 주세요.",
    STOCK_LIMIT_EXCEEDED: "재고는 1,000,000개 단위를 넘을 수 없어요. 현재 수량과 입력 수량을 확인해 주세요.",
    INVALID_STOCK_REVERSAL: "취소 보정 기록을 다시 취소할 수 없어요. 실물과 차이가 있으면 사유 있는 재고 조정을 기록해 주세요.",
    STOCK_MOVEMENT_ALREADY_REVERSED: "이미 취소된 재고 기록이에요. 현재 원본과 보정 기록을 확인해 주세요.",
    REPLACEMENT_CANCEL_REQUIRED: "교체 사용은 기기별 교체 이력에서 취소해 주세요.",
  };
  return error && messages[error.code] ? <div role="alert" className="auth-message"><p>{messages[error.code]}</p></div> : <FinanceError error={error} />;
}
export function useMetadataCommand() {
  const mounted = useMounted(); const flight = useRef(false); const [busy, setBusy] = useState(false); const [error, setError] = useState<ApiError | null>(null); const [uncertain, setUncertain] = useState(false);
  async function run<T>(write: () => Promise<T>, creating = false): Promise<T | undefined> {
    if (flight.current || uncertain) return; flight.current = true; setBusy(true); setError(null);
    try { return await write(); } catch (failure) { if (mounted.current) { const problem = toApiError(failure); setError(problem); if (creating && problem.status === 0) setUncertain(true); } }
    finally { flight.current = false; if (mounted.current) setBusy(false); }
  }
  return { mounted, busy, error, setError, run, uncertain, resolveUncertain: () => { setUncertain(false); setError(null); } };
}
export function MetadataFeedback({ command, listPath }: { command: ReturnType<typeof useMetadataCommand>; listPath: string }) {
  return <><HomecareError error={command.error} />{command.uncertain && <section className="review-panel"><p>등록됐을 수 있어요. <Link to={listPath}>현재 목록</Link>에서 등록 여부를 확인한 뒤 다시 요청해 주세요.</p><button type="button" onClick={command.resolveUncertain}>목록에서 등록되지 않은 것을 확인했어요</button></section>}</>;
}
export function ConflictReview({ error, compare, latest, adopt, replace, children }: { error: ApiError | null; compare: () => void; latest: boolean; adopt: () => void; replace: () => void; children: ReactNode }) {
  return error?.status === 409 && <section className="review-panel" aria-label="가전 소모품 변경 비교"><h3>현재 내용과 내 수정 비교</h3><p>작성한 내용은 유지했어요. 현재 내용을 확인한 뒤 계속해 주세요.</p><button type="button" onClick={compare}>현재 가전·소모품 내용 비교</button>{latest && <>{children}<p>내가 바꾼 항목만 유지하고 다른 항목은 현재 내용으로 채워요.</p><div className="form-actions"><button type="button" onClick={adopt}>비교한 수정 유지</button><button type="button" onClick={replace}>현재 내용으로 교체</button></div></>}</section>;
}
export function ListFeedback({ list, empty }: { list: { loading: boolean; error: ApiError | null; items: unknown[]; cursor: string | null; reload: () => Promise<void>; more: () => Promise<void> }; empty: string }) {
  return <>{list.loading && <p className="loading-state" role="status">기록을 불러오고 있어요.</p>}<HomecareError error={list.error} />{list.error && <button type="button" onClick={() => void list.reload()}>목록 다시 확인</button>}{!list.loading && !list.error && !list.items.length && <p>{empty}</p>}{list.cursor && <button type="button" disabled={list.loading} onClick={() => void list.more()}>기록 더 보기</button>}</>;
}
export function ResourceFeedback({ resource }: { resource: { loading: boolean; error: ApiError | null; reload: () => Promise<void> } }) { return <>{resource.loading && <p className="loading-state" role="status">현재 기록을 확인하고 있어요.</p>}<HomecareError error={resource.error} />{resource.error && <button type="button" onClick={() => void resource.reload()}>현재 기록 다시 확인</button>}</>; }
export const recordedLabel = (value: string) => new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(value));

export function useSeoulDayRefresh(reload: () => Promise<void>) { useEffect(() => { let observedDay = todaySeoul(); const check = () => { const day = todaySeoul(); if (day !== observedDay) { observedDay = day; void reload(); } }; const timer = window.setInterval(check, 30000); window.addEventListener("focus", check); document.addEventListener("visibilitychange", check); return () => { window.clearInterval(timer); window.removeEventListener("focus", check); document.removeEventListener("visibilitychange", check); }; }, [reload]); }
