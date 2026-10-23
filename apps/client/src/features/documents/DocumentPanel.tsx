import { useCallback, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { isNativeAuth } from "../../platform/nativeAuth";
import { usePagedList } from "../finance/queries";
import { useDocumentsApi } from "./api";
import { MAX_PDF_PAGES, stateLabel, targetLabels } from "./model";
import type { Target } from "./model";
import { CommandFeedback, DocumentError, useDocumentCommand } from "./DocumentSupport";
import { DocumentDetail } from "./DocumentDetail";
import { WebUpload } from "./WebUpload";
function Documents({ target }: { target: Target }) {
  const api = useDocumentsApi();
  const command = useDocumentCommand();
  const [all, setAll] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.list({
          query: {
            ...(all ? {} : { target_kind: target.kind, target_id: target.id }),
            cursor,
            limit: 50,
          },
        }),
      [api, all, target.kind, target.id],
    ),
  );
  async function upload() {
    const result = await command.run((signal) => api.nativeUpload({ target }, signal));
    if (result) {
      setNotice(
        result.status === "uploaded" ? "문서 업로드를 완료했어요." : "파일 선택을 취소했어요.",
      );
      if (result.status === "uploaded") void list.reload();
    }
  }
  return (
    <>
      <p>
        PDF·JPEG·PNG 파일을 최대 20MiB까지(PDF는 최대 {MAX_PDF_PAGES}쪽) 첨부할 수 있어요. 카드
        앞뒷면 사진과 카드 비밀정보는 첨부할 수 없어요.
      </p>
      {isNativeAuth() ? (
        <>
          <button disabled={command.busy} onClick={() => void upload()}>
            Android에서 문서 선택·업로드
          </button>
          <CommandFeedback command={command} />
          {notice && <p role="status">{notice}</p>}
        </>
      ) : (
        <WebUpload
          api={api}
          target={target}
          saved={(id) => {
            setSelected(id);
            void list.reload();
          }}
          refused={() => void list.reload()}
        />
      )}
      <div className="form-actions">
        <button
          aria-pressed={!all}
          onClick={() => {
            setAll(false);
            setSelected(null);
          }}
        >
          현재 대상의 문서
        </button>
        <button
          aria-pressed={all}
          onClick={() => {
            setAll(true);
            setSelected(null);
          }}
        >
          기존 문서에서 연결·대기 기록 찾기
        </button>
        <button disabled={list.loading} onClick={() => void list.reload()}>
          문서 목록 새로 확인
        </button>
      </div>
      {all && (
        <p>
          공동 가계의 보관 문서와 업로드 대기 기록이에요. 선택한 문서를 현재{" "}
          {targetLabels[target.kind]}에 연결할 수 있어요.
        </p>
      )}
      <DocumentError error={list.error} />
      {list.loading && (
        <p className="loading-state" role="status">
          문서 목록을 불러오고 있어요.
        </p>
      )}
      {!list.loading && !list.error && !list.items.length && <p>표시할 문서가 없어요.</p>}
      <ul className="record-list">
        {list.items.map((row) => (
          <li key={row.id}>
            <button onClick={() => setSelected(row.id)}>{row.original_name}</button>
            <p>
              {stateLabel(row)} · {row.size_bytes.toLocaleString("ko-KR")}바이트 · 연결{" "}
              {row.active_link_count}개
            </p>
          </li>
        ))}
      </ul>
      {list.cursor && (
        <button disabled={list.loading} onClick={() => void list.more()}>
          문서 더 보기
        </button>
      )}
      {selected && (
        <>
          <button onClick={() => setSelected(null)}>문서 상세 닫기</button>
          <DocumentDetail
            key={selected}
            id={selected}
            api={api}
            target={target}
            changed={() => void list.reload()}
          />
        </>
      )}
    </>
  );
}
/** Mount only beneath an authorized parent record. Closing discards file bytes and requests. */
export function DocumentPanel({ kind, id }: Target) {
  const { state } = useAuth();
  const [open, setOpen] = useState(false);
  return state.status === "authenticated" ? (
    <section className="card document-panel" aria-label={`${targetLabels[kind]} 첨부 문서`}>
      <h2>첨부 문서</h2>
      <button aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "첨부 문서 접기" : "첨부 문서 열기"}
      </button>
      {open && <Documents key={`${kind}:${id}`} target={{ kind, id }} />}
    </section>
  ) : null;
}
