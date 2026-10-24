import { useCallback } from "react";
import { RecordActor } from "../../shared/RecordActor";
import { useResource } from "../finance/queries";
import { useAuditApi } from "./api";

/** For older domain responses without actor fields, match the displayed version to its audit fact. */
export function LastAuditActor({
  kind,
  id,
  version,
}: {
  kind: string;
  id: string;
  version: number;
}) {
  const api = useAuditApi();
  const state = useResource(
    useCallback(async () => {
      const page = await api.list({ entity_type: kind, entity_id: id, limit: 1 });
      const latest = page.items[0];
      return latest?.after_version === version ? latest : null;
    }, [api, kind, id, version]),
  );
  if (state.loading) return <p className="muted">마지막 작업자를 확인하고 있어요.</p>;
  if (state.error || !state.data)
    return (
      <p className="muted">
        이 버전의 수정자·시각을 확인할 수 없어요.{" "}
        <button type="button" onClick={() => void state.reload()}>
          작업자 다시 확인
        </button>
      </p>
    );
  return <RecordActor memberId={state.data.actor_member_id} at={state.data.occurred_at} />;
}
