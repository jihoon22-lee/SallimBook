import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { useMounted, SessionStatus } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import { FinanceError, useHouseholdMembers, MemberLoadError } from "../finance/FinanceSupport";
export function InsurancePage({ title, description, children, navigation }: { title: string; description: string; children: ReactNode; navigation?: ReactNode }) {
  const { state } = useAuth();
  return <><div className="intro"><p className="eyebrow">사건과 실제 기록을 함께</p><h1>{title}</h1><p>{description}</p></div>{navigation}{state.status === "authenticated" ? children : <SessionStatus />}</>;
}
export function InsuranceError({ error }: { error: ApiError | null }) {
  const messages: Partial<Record<ApiError["code"], string>> = {
    VALUATION_ASSET_UNAVAILABLE: "확인한 환급·적립 평가액과 연결할 사용 중인 금융 자산을 선택해 주세요.",
    INVALID_INSURANCE_INPUT: "필수 항목과 계약·보장·납입 기간을 확인해 주세요.",
    POLICY_NUMBER_NOT_SET: "등록된 증권번호가 없어요.", POLICY_NUMBER_UNAVAILABLE: "증권번호를 열 수 없어요. 다시 인증한 뒤 확인해 주세요.",
    FIELD_ENCRYPTION_UNAVAILABLE: "증권번호 보호 설정을 확인하지 못했어요. 번호 저장과 열람은 잠시 사용할 수 없어요.",
    POLICY_UNAVAILABLE: "현재 사용할 수 있는 보험 계약을 선택해 주세요.", RECURRING_RULE_UNAVAILABLE: "연결할 수 있는 납부 규칙을 다시 확인해 주세요.", PREMIUM_RULE_ALREADY_LINKED: "이미 연결된 보험료 규칙이에요. 기존 연결을 확인해 주세요.",
    INVALID_MEDICAL_DATES: "진료 시작일과 종료일을 확인해 주세요.", MEDICAL_NODE_CYCLE: "자기 자신이나 하위 진료 아래로 이동할 수 없어요.", MEDICAL_NODE_IN_USE: "하위 진료나 비용이 있어 삭제할 수 없어요. 연결된 기록을 먼저 확인해 주세요.",
  };
  return error && messages[error.code] ? <div role="alert" className="auth-message"><p>{messages[error.code]}</p></div> : <FinanceError error={error} />;
}
export function MemberSelect({ value, onChange, label, required = false, disabled = false }: { value: string; onChange: (value: string) => void; label: string; required?: boolean; disabled?: boolean }) {
  const members = useHouseholdMembers(); return <div className="form-field"><label>{label}<select required={required} value={value} disabled={disabled || members.loading} onChange={(e) => onChange(e.target.value)}><option value="">{required ? "구성원 선택" : "미지정"}</option>{members.members.map((m) => <option key={m.member_id} value={m.member_id}>{m.display_name}</option>)}</select></label><MemberLoadError error={members.error} retry={members.retry} /></div>;
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
  return <><InsuranceError error={command.error} />{command.uncertain && <section className="review-panel"><p>등록됐을 수 있어요. <Link to={listPath}>현재 목록</Link>에서 등록 여부를 확인한 뒤 다시 요청해 주세요.</p><button type="button" onClick={command.resolveUncertain}>목록에서 등록되지 않은 것을 확인했어요</button></section>}</>;
}
export function ConflictReview({ error, compare, latest, adopt, replace, children }: { error: ApiError | null; compare: () => void; latest: boolean; adopt: () => void; replace: () => void; children: ReactNode }) {
  return error?.status === 409 && <section className="review-panel" aria-label="보험 변경 충돌 비교"><h3>현재 내용과 내 수정 비교</h3><p>작성한 내용은 유지했어요. 다른 곳의 변경을 확인한 뒤 계속해 주세요.</p><button type="button" onClick={compare}>보험 현재 내용 비교</button>{latest && <>{children}<p>내가 바꾼 항목만 유지하고 다른 항목은 현재 내용으로 채워요.</p><div className="form-actions"><button type="button" onClick={adopt}>비교한 보험 수정 유지</button><button type="button" onClick={replace}>현재 보험 내용으로 교체</button></div></>}</section>;
}
