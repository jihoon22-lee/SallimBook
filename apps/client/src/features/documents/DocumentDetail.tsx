import { useCallback, useRef, useState } from "react";
import { Link } from "react-router";
import { useHouseholdMembers } from "../finance/FinanceSupport";
import { isNativeAuth } from "../../platform/nativeAuth";
import { ApiError } from "../../platform/api";
import { allPages, usePagedList, useResource } from "../finance/queries";
import { recordedLabel } from "../homecare/HomecareSupport";
import type { DocumentsApi } from "./api";
import { checksum, etag, expired, stateLabel, targetLabels } from "./model";
import type { Document, DocumentLink, Target } from "./model";
import { CommandFeedback, DocumentError, useDocumentCommand } from "./DocumentSupport";
import { WebUpload } from "./WebUpload";
export function DocumentMetadata({ row }: { row: Document }) { return <dl className="metadata-grid"><div><dt>파일 이름</dt><dd>{row.original_name}</dd></div><div><dt>파일 형식·크기</dt><dd>{row.mime_type} · {row.size_bytes.toLocaleString("ko-KR")}바이트</dd></div><div><dt>보관 상태</dt><dd>{stateLabel(row)}</dd></div><div><dt>현재 연결</dt><dd>{row.active_link_count}개</dd></div><div><dt>등록 시각</dt><dd>{recordedLabel(row.created_at)}</dd></div>{row.stored_at && <div><dt>보관 시각</dt><dd>{recordedLabel(row.stored_at)}</dd></div>}{row.state === "pending" && <div><dt>업로드 기한</dt><dd>{recordedLabel(row.pending_expires_at)}</dd></div>}{row.orphaned_at && <div><dt>마지막 연결 종료</dt><dd>{recordedLabel(row.orphaned_at)}</dd></div>}{row.deleted_at && <div><dt>삭제 시각</dt><dd>{recordedLabel(row.deleted_at)}</dd></div>}<div><dt>문서 버전</dt><dd>{row.version}</dd></div></dl>; }
function TargetLabel({ target, current }: { target: Target; current: Target }) {
  if (target.kind === current.kind && target.id === current.id) return <>{targetLabels[target.kind]} · 현재 대상</>;
  const paths = { policy: "/insurance/policies", case: "/insurance/cases", expense: "/insurance/expenses", claim: "/insurance/claims", appliance: "/appliances", asset: "/assets" };
  return target.kind === "medical_node" ? <>다른 진료·약국</> : <Link to={`${paths[target.kind]}/${target.id}`}>연결된 {targetLabels[target.kind]} 보기</Link>;
}
type PendingCommand = { label: string; run: (signal: AbortSignal) => Promise<unknown> };
export function DocumentDetail({ id, api, target, changed }: { id: string; api: DocumentsApi; target: Target; changed: () => void }) {
  const members = useHouseholdMembers(); const memberName = (id: string) => members.members.find((row) => row.member_id === id)?.display_name ?? "가계 구성원"; const resource = useResource(useCallback(() => api.get(id), [api, id])); const links = usePagedList(useCallback((cursor?: string) => api.links({ documentId: id, query: { cursor, limit: 50 } }), [api, id])); const command = useDocumentCommand(); const operation = useRef<PendingCommand | null>(null); const [pendingLabel, setPendingLabel] = useState(""); const [reason, setReason] = useState(""); const [deleteAck, setDeleteAck] = useState(false); const [saveAck, setSaveAck] = useState(false); const [notice, setNotice] = useState(""); const [comparison, setComparison] = useState<{ row: Document; links: DocumentLink[] } | null>(null); const row = resource.data;
  const linksComplete = !links.loading && !links.error && links.cursor === null;
  const alreadyLinked = links.items.some((entry) => entry.active && entry.target.kind === target.kind && entry.target.id === target.id);
  async function reload() { await Promise.all([resource.reload(), links.reload()]); changed(); }
  async function execute(next?: PendingCommand) {
    if (!operation.current && next) { operation.current = next; setPendingLabel(next.label); }
    const action = operation.current; if (!action) return;
    const result = await command.run(async (signal) => { await action.run(signal); return true; });
    if (result) { operation.current = null; setPendingLabel(""); setReason(""); setDeleteAck(false); setComparison(null); setNotice(`${action.label} 완료`); await reload(); }
  }
  function link() { if (!row || operation.current || !linksComplete || alreadyLinked) return; const key = crypto.randomUUID(); void execute({ label: "현재 대상에 연결", run: (signal) => api.link({ input: { document_id: id, target }, ifMatch: etag(row.version), idempotencyKey: key }, signal) }); }
  function end(link: DocumentLink) { if (!reason.trim() || operation.current) return; const key = crypto.randomUUID(); const input = { reason: reason.trim() }; void execute({ label: "문서 연결 종료", run: (signal) => api.end({ linkId: link.id, input, ifMatch: etag(link.version), idempotencyKey: key }, signal) }); }
  function remove() { if (!row || !reason.trim() || !deleteAck || operation.current) return; const key = crypto.randomUUID(); const input = { reason: reason.trim() }; void execute({ label: "문서 삭제", run: (signal) => api.remove({ documentId: id, input, ifMatch: etag(row.version), idempotencyKey: key }, signal) }); }
  async function compare() { const current = await command.run(async (signal) => ({ row: await api.get(id, signal), links: await allPages((cursor) => api.links({ documentId: id, query: { cursor, limit: 200 } }, signal)) })); if (current) setComparison(current); }
  async function download() {
    if (!row || !saveAck || operation.current) return;
    const result = await command.run(async (signal) => {
      if (isNativeAuth()) return (await api.nativeDownload({ documentId: id }, signal)).status === "downloaded";
      let bytes: ArrayBuffer | undefined; let url: string | undefined;
      try {
        bytes = await api.download(id, signal);
        if (signal.aborted || !command.mounted.current) throw new DOMException("", "AbortError");
        if (bytes.byteLength !== row.size_bytes || await checksum(bytes) !== row.checksum_sha256) throw new ApiError(422, "DOCUMENT_CONTENT_MISMATCH");
        if (signal.aborted || !command.mounted.current) throw new DOMException("", "AbortError");
        url = URL.createObjectURL(new Blob([bytes], { type: row.mime_type })); const anchor = document.createElement("a"); anchor.href = url; anchor.download = row.original_name; anchor.rel = "noopener"; document.body.append(anchor); anchor.click(); anchor.remove();
        return true;
      } finally { if (url) URL.revokeObjectURL(url); if (bytes) new Uint8Array(bytes).fill(0); }
    });
    if (result !== undefined) { setSaveAck(false); setNotice(result ? "원본 저장 요청을 보냈어요. 브라우저 또는 기기의 저장 결과를 확인해 주세요." : "원본 저장을 취소했어요."); }
  }
  return <section className="review-panel" aria-label="문서 상세"><h3>문서 상세</h3><DocumentError error={resource.error} />{resource.loading && <p className="loading-state" role="status">문서를 확인하고 있어요.</p>}{resource.error && <button onClick={() => void resource.reload()}>문서 다시 확인</button>}{row && !resource.error && !resource.loading && <><DocumentMetadata row={row} />{notice && <p role="status">{notice}</p>}<CommandFeedback command={command} />{row.state === "ready" && row.active_link_count > 0 && <><label className="checkbox-field"><input type="checkbox" checked={saveAck} disabled={command.busy || !!pendingLabel} onChange={(e) => setSaveAck(e.target.checked)} />기기에 저장한 사본은 앱 잠금·문서 삭제 후에도 남는 것을 확인했어요</label><button disabled={!saveAck || command.busy || !!pendingLabel} onClick={() => void download()}>원본 파일 저장</button></>}{row.state === "pending" && !expired(row) && !isNativeAuth() && <WebUpload key={`${id}:${row.version}`} api={api} target={target} pending={row} saved={() => void reload()} />}{row.state === "pending" && isNativeAuth() && <p>Android 업로드의 재시도는 파일을 선택한 보호 화면에서 진행해 주세요. 종료된 대기 기록은 삭제 후 새로 첨부할 수 있어요.</p>}{row.state === "ready" && !row.active_link_count && <p>연결이 없어도 보관 문서는 남아요. 다시 연결하거나 명시적으로 삭제해 주세요.</p>}<h4>연결 이력</h4><DocumentError error={links.error} />{links.error && <button onClick={() => void links.reload()}>연결 이력 다시 확인</button>}<ul className="record-list">{links.items.map((entry) => <li key={entry.id}><p><TargetLabel target={entry.target} current={target} /> · {entry.active ? "연결 중" : "연결 종료"}</p><p>연결 {recordedLabel(entry.created_at)} · 작성자 {memberName(entry.created_by_member_id)}</p>{entry.ended_at && <p>종료 {recordedLabel(entry.ended_at)} · {entry.end_reason} · 변경자 {memberName(entry.updated_by_member_id)}</p>}{entry.active && row.state !== "deleted" && <button disabled={!reason.trim() || reason.trim().length > 500 || command.busy || !!pendingLabel} onClick={() => end(entry)}>이 문서 연결 종료</button>}</li>)}</ul>{links.cursor && <><p>연결 여부를 확인하려면 남은 연결 이력을 모두 확인해 주세요.</p><button disabled={links.loading} onClick={() => void links.more()}>연결 이력 더 보기</button></>}{row.state !== "deleted" && <><p>연결 종료는 파일을 삭제하지 않아요. 문서 삭제는 모든 대상의 연결을 종료하고 원본 접근을 막아요.</p><label>문서 연결 종료·삭제 사유<textarea maxLength={500} value={reason} disabled={command.busy || !!pendingLabel} onChange={(e) => setReason(e.target.value)} /></label><button disabled={command.busy || !!pendingLabel || expired(row) || !linksComplete || alreadyLinked} onClick={link}>현재 대상에 문서 연결</button><label className="checkbox-field"><input type="checkbox" disabled={command.busy || !!pendingLabel} checked={deleteAck} onChange={(e) => setDeleteAck(e.target.checked)} />모든 연결 대상에서 이 문서를 삭제하는 것을 확인했어요</label><button className="danger-button" disabled={!deleteAck || !reason.trim() || reason.trim().length > 500 || command.busy || !!pendingLabel} onClick={remove}>문서 삭제</button></>}{pendingLabel && <div className="review-panel"><p>{pendingLabel} 결과를 확인해야 해요. 작성한 사유와 요청을 유지했어요.</p><button disabled={command.busy || command.error?.status === 409 || !!comparison} onClick={() => void execute()}>같은 문서 작업 재시도</button><button disabled={command.busy} onClick={() => void compare()}>현재 문서·연결 이력 비교</button>{comparison && <><DocumentMetadata row={comparison.row} /><p>현재 연결: {comparison.links.filter((entry) => entry.active).length}개 · 전체 연결 이력 {comparison.links.length}개</p><ul>{comparison.links.map((entry) => <li key={entry.id}><TargetLabel target={entry.target} current={target} /> · {entry.active ? "연결 중" : "종료"} · 버전 {entry.version}</li>)}</ul><button disabled={command.busy} onClick={() => { operation.current = null; setPendingLabel(""); setComparison(null); setDeleteAck(false); command.setError(null); void reload(); }}>현재 내용을 확인하고 새 작업 준비</button></>}</div>}</>}</section>;
}
