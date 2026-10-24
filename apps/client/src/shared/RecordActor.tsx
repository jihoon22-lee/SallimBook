import { createContext, useContext, type ReactNode } from "react";
import { useAuth } from "../features/auth/AuthProvider";
import { useHouseholdMembers } from "../features/finance/FinanceSupport";
import { formatSeoulDateTime } from "./format";
const Actors = createContext<ReturnType<typeof useHouseholdMembers> | null>(null);
function LoadedActors({ children }: { children: ReactNode }) {
  const members = useHouseholdMembers();
  return <Actors.Provider value={members}>{children}</Actors.Provider>;
}
export function RecordActorsProvider({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  return state.status === "authenticated" ? (
    <LoadedActors key={state.member.member_id}>{children}</LoadedActors>
  ) : (
    children
  );
}
export function RecordActor({
  memberId,
  at,
  label = "마지막 수정",
}: {
  memberId?: string | null;
  at?: string | null;
  label?: string;
}) {
  const actors = useContext(Actors);
  if (!at) return null;
  const name = actors?.error
    ? "수정자 확인 실패"
    : actors?.loading
      ? "수정자 확인 중"
      : (actors?.members.find((m) => m.member_id === memberId)?.display_name ?? "구성원 확인 필요");
  return (
    <span className="record-actor">
      {label}: {name} · {formatSeoulDateTime(at)} (서울)
      {actors?.error && (
        <button type="button" onClick={actors.retry}>
          수정자 다시 확인
        </button>
      )}
    </span>
  );
}
export type ModifiedRecord = { updated_by_member_id?: string | null; updated_at?: string | null };
export function LastModified({ record }: { record: ModifiedRecord }) {
  return record.updated_at ? (
    <div>
      <dt>마지막 수정</dt>
      <dd>
        <RecordActor memberId={record.updated_by_member_id} at={record.updated_at} label="수정자" />
      </dd>
    </div>
  ) : null;
}
