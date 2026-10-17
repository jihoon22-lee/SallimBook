import { useCallback, useState } from "react";
import { useDocumentsApi } from "../documents/api";
import { DocumentError } from "../documents/DocumentSupport";
import { stateLabel } from "../documents/model";
import type { Document } from "../documents/model";
import { usePagedList } from "../finance/queries";
import { byteLabel, exportable, selectionProblem } from "./model";

export function DocumentPicker({ selected, busy, changed }: { selected: Document[]; busy: boolean; changed: (documents: Document[]) => void }) {
  const api = useDocumentsApi();
  const list = usePagedList(useCallback((cursor?: string) => api.list({ query: { limit: 50, ...(cursor ? { cursor } : {}) } }), [api]));
  const [search, setSearch] = useState(""); const [validation, setValidation] = useState("");
  function toggle(row: Document) {
    const next = selected.some((item) => item.id === row.id) ? selected.filter((item) => item.id !== row.id) : [...selected, row];
    const problem = selectionProblem(["json"], next); setValidation(problem ?? "");
    if (!problem) changed(next);
  }
  return <section className="review-panel export-documents" aria-label="내보낼 문서 원본 선택"><h3>문서 원본 선택</h3>
    <p>현재 연결이 있고 보관이 완료된 문서만 선택할 수 있어요. 원본 파일 이름과 내용에는 개인 정보가 포함될 수 있어요.</p>
    <label>불러온 문서에서 이름 찾기<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} disabled={busy} maxLength={255} /></label>
    <DocumentError error={list.error} />{validation && <p role="alert">{validation}</p>}
    {list.loading && <p role="status">문서 목록을 확인하고 있어요.</p>}
    {!list.error && <ul className="record-list">{list.items.filter((row) => row.original_name.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map((row) => {
      const checked = selected.some((item) => item.id === row.id);
      return <li key={row.id}><label className="checkbox-field"><input type="checkbox" checked={checked} disabled={busy || !checked && !exportable(row)} onChange={() => toggle(row)} />{row.original_name}</label><p>{byteLabel(row.size_bytes)} · {stateLabel(row)} · 현재 연결 {row.active_link_count}개</p></li>;
    })}</ul>}
    {!list.loading && !list.error && !list.items.length && <p>등록된 문서가 없어요. 업무 기록은 문서 원본 없이 내보낼 수 있어요.</p>}
    <div className="form-actions"><button type="button" disabled={busy || list.loading} onClick={() => { setValidation(""); void list.reload(); }}>문서 목록 다시 확인</button>{list.cursor && <button type="button" disabled={busy || list.loading} onClick={() => void list.more()}>문서 더 보기</button>}</div>
  </section>;
}
