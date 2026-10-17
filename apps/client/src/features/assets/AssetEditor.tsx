import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { useMounted } from "../auth/AuthFeedback";
import { FinanceError, MemberLoadError, useHouseholdMembers } from "../finance/FinanceSupport";
import { ClosureReview, useAssetClosure } from "../finance/PaymentLinks";
import { AssetFields, assetFieldLabels } from "./AssetFields";
import { useAssetsApi } from "./api";
import { amountBases, assetDraft, assetInput, assetKinds, categories, changedAssetFields, mergeAssetDraft, newAssetDraft } from "./model";
import type { Asset, AssetDraft, AssetPatch } from "./model";

export function AssetEditor({ initial }: { initial?: Asset }) {
  const api = useAssetsApi();
  const navigate = useNavigate();
  const mounted = useMounted();
  const members = useHouseholdMembers();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => initial ? assetDraft(initial) : newAssetDraft());
  const [error, setError] = useState<ApiError | null>(null);
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const flight = useRef(false);
  const [latest, setLatest] = useState<Asset | null>(null);
  const [conflict, setConflict] = useState(false);
  const closing = !!base && !!draft.ended_on && draft.ended_on !== (base.ended_on ?? "");
  const closure = useAssetClosure(base, draft.ended_on, closing);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (flight.current || conflict || !closure.ready) return;
    const input = assetInput(draft);
    if (!input) { setFormError("필수 항목과 0~100 사이의 가계 지분, 시작일·종료일을 확인해 주세요."); return; }
    const before = base ? assetInput(assetDraft(base))! : null;
    const changes = before ? Object.fromEntries(Object.entries(input).filter(([key, value]) => value !== before[key as keyof typeof before])) as Omit<AssetPatch, "closure_ack"> : null;
    const patch: AssetPatch | null = changes ? { ...changes, ...(closing ? closure.proof : { closure_ack: false }) } : null;
    if (changes && Object.keys(changes).length === 0) { setFormError("변경한 내용이 없어요."); return; }
    flight.current = true; setBusy(true); setError(null); setFormError("");
    try {
      const saved = base && patch ? await api.update(base.id, patch, base.version) : await api.create(input);
      if (mounted.current) navigate(`/assets/${saved.id}`, { replace: true, state: { saved: true } });
    } catch (failure) {
      if (mounted.current) { const value = toApiError(failure); setError(value); if (value.code === "VERSION_CONFLICT") setConflict(true); if (value.code === "PAYMENT_LINKS_CHANGED" || value.code === "PAYMENT_LINK_CONFIRMATION_REQUIRED") closure.refresh(); }
    } finally { flight.current = false; if (mounted.current) setBusy(false); }
  }

  async function loadLatest() {
    if (!base || flight.current) return;
    flight.current = true; setBusy(true); setError(null);
    try { const value = await api.get(base.id); if (mounted.current) setLatest(value); }
    catch (failure) { if (mounted.current) setError(toApiError(failure)); }
    finally { flight.current = false; if (mounted.current) setBusy(false); }
  }

  const changed = base ? changedAssetFields(base, draft) : [];
  function label(field: keyof AssetDraft, value: AssetDraft[keyof AssetDraft]) {
    if (field === "kind") return assetKinds[value as keyof typeof assetKinds] ?? value;
    if (field === "category") return categories[value as keyof typeof categories] ?? value;
    if (field === "amount_basis") return amountBases[value as keyof typeof amountBases] ?? value;
    if (field === "owner_member_id") return members.members.find((member) => member.member_id === value)?.display_name ?? "선택 안 됨";
    if (field === "ownership_kind") return value === "joint" ? "공동 소유" : "한 사람 소유";
    if (field === "inclusion_status") return value === "included" ? "합계에 포함" : "합계에서 제외";
    return value || "미입력";
  }
  function resolve(keepDraft: boolean) {
    if (!latest || !base) return;
    setDraft(keepDraft ? mergeAssetDraft(latest, draft, changed) : assetDraft(latest));
    setBase(latest); setLatest(null); setConflict(false); setError(null); setFormError("");
  }

  return <section className="card">
    <MemberLoadError error={members.error} retry={members.retry} />
    {members.loading && <p role="status">가계 구성원을 확인하고 있어요.</p>}
    <form className="finance-form" onSubmit={(event) => void submit(event)}>
      <AssetFields value={draft} onChange={setDraft} members={members.members} disabled={busy || members.loading || Boolean(members.error)} />
      {closing && base?.category === "financial" && <ClosureReview review={closure} disabled={busy} />}
      {formError && <p role="alert">{formError}</p>}
      <FinanceError error={error} />
      {conflict && <section className="conflict-panel" aria-labelledby="asset-conflict-title">
        <h2 id="asset-conflict-title">서버 변경과 내 수정 확인</h2>
        <p>작성 중인 내용은 보존했어요. 최신 정보를 확인한 뒤 어떤 값을 사용할지 선택해 주세요.</p>
        <button type="button" disabled={busy} onClick={() => void loadLatest()}>서버의 최신 정보 확인</button>
        {latest && <>
          <div className="table-scroll" tabIndex={0} role="region" aria-label="자산 수정 비교 표"><table><caption>내가 바꾼 항목의 비교</caption><thead><tr><th scope="col">항목</th><th scope="col">내 수정</th><th scope="col">서버 최신 값</th></tr></thead><tbody>{changed.map((field) => <tr key={field}><th scope="row">{assetFieldLabels[field]}</th><td>{label(field, draft[field])}</td><td>{label(field, assetDraft(latest)[field])}</td></tr>)}</tbody></table></div>
          <p>내 수정 유지는 위 항목만 유지하고, 바꾸지 않은 항목은 서버의 최신 값으로 가져와요. 저장 전 다시 확인할 수 있어요.</p>
          <div className="form-actions"><button type="button" onClick={() => resolve(true)}>비교한 내 수정 유지</button><button type="button" className="secondary-button" onClick={() => resolve(false)}>내 수정 버리고 서버 값 사용</button></div>
        </>}
      </section>}
      <div className="form-actions"><button type="submit" disabled={busy || conflict || members.loading || Boolean(members.error) || !closure.ready}>{busy ? "저장 중…" : base ? "자산 수정 저장" : "자산 등록"}</button><Link className="button-link secondary-button" aria-disabled={busy} onClick={(event) => { if (busy) event.preventDefault(); }} to={base ? `/assets/${base.id}` : "/assets"}>취소하고 돌아가기</Link></div>
    </form>
  </section>;
}
