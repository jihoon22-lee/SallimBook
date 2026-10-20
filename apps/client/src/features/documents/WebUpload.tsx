import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../../platform/api";
import type { DocumentsApi } from "./api";
import { checksum, etag, expired, fileProblem, sameContent, stateLabel } from "./model";
import type { CreateDocument, Document, Target } from "./model";
import { CommandFeedback, useDocumentCommand } from "./DocumentSupport";
type Attempt = {
  bytes: ArrayBuffer;
  input: CreateDocument;
  createKey: string;
  uploadKey: string;
  id?: string;
  version?: number;
};
export function WebUpload({
  api,
  target,
  pending,
  saved,
}: {
  api: DocumentsApi;
  target: Target;
  pending?: Document;
  saved: (id: string) => void;
}) {
  const command = useDocumentCommand();
  const input = useRef<HTMLInputElement>(null);
  const file = useRef<File | null>(null);
  const attempt = useRef<Attempt | null>(null);
  const [chosen, setChosen] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [ack, setAck] = useState(false);
  const [started, setStarted] = useState(false);
  const [latest, setLatest] = useState<Document | null>(null);
  function clear() {
    if (attempt.current) new Uint8Array(attempt.current.bytes).fill(0);
    attempt.current = null;
    file.current = null;
    if (input.current) input.current.value = "";
  }
  useEffect(() => {
    const discard = () => {
      clear();
      setChosen("");
      setStarted(false);
      setAck(false);
    };
    window.addEventListener("pagehide", discard);
    return () => {
      clear();
      window.removeEventListener("pagehide", discard);
    };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ack || command.error?.status === 409 || (!file.current && !attempt.current)) return;
    const result = await command.run(async (signal) => {
      if (!attempt.current) {
        const selected = file.current!;
        const validation = fileProblem(selected);
        if (validation) {
          setProblem(validation);
          return;
        }
        const bytes = await selected.arrayBuffer();
        try {
          if (signal.aborted || !command.mounted.current) throw new DOMException("", "AbortError");
          if (bytes.byteLength !== selected.size)
            throw new ApiError(422, "DOCUMENT_CONTENT_MISMATCH");
          const hash = await checksum(bytes);
          if (signal.aborted || !command.mounted.current) throw new DOMException("", "AbortError");
          const metadata: CreateDocument = {
            original_name: selected.name,
            mime_type: selected.type as CreateDocument["mime_type"],
            size_bytes: bytes.byteLength,
            checksum_sha256: hash,
            target,
            contains_no_card_data: true,
          };
          if (pending && !sameContent(pending, metadata))
            throw new ApiError(422, "DOCUMENT_CONTENT_MISMATCH");
          attempt.current = {
            bytes,
            input: metadata,
            createKey: crypto.randomUUID(),
            uploadKey: crypto.randomUUID(),
            id: pending?.id,
            version: pending?.version,
          };
          setStarted(true);
        } catch (error) {
          new Uint8Array(bytes).fill(0);
          throw error;
        }
      }
      const current = attempt.current!;
      if (!current.id) {
        const ref = await api.create(current.input, current.createKey, signal);
        current.id = ref.id;
        current.version = ref.version;
      }
      // Reconcile an unknown upload outcome before replay; never create a second document.
      const row = await api.get(current.id, signal);
      if (!sameContent(row, current.input)) throw new ApiError(422, "DOCUMENT_CONTENT_MISMATCH");
      if (row.state === "ready") return row.id;
      if (row.state === "deleted") throw new ApiError(409, "DOCUMENT_UNAVAILABLE");
      if (expired(row)) throw new ApiError(409, "DOCUMENT_UPLOAD_EXPIRED");
      await api.upload(
        current.id,
        etag(current.version!),
        current.uploadKey,
        current.bytes,
        signal,
      );
      return current.id;
    });
    if (result && command.mounted.current) {
      clear();
      setChosen("");
      setAck(false);
      setStarted(false);
      saved(result);
    }
  }
  async function compare() {
    const id = attempt.current?.id ?? pending?.id;
    if (!id) return;
    const row = await command.run((signal) => api.get(id, signal));
    if (row) {
      setLatest(row);
      command.setError(new ApiError(409, "VERSION_CONFLICT"));
    }
  }
  function adopt() {
    const current = attempt.current;
    if (
      !current ||
      !latest ||
      latest.state !== "pending" ||
      expired(latest) ||
      !sameContent(latest, current.input)
    )
      return;
    current.version = latest.version;
    current.uploadKey = crypto.randomUUID();
    setLatest(null);
    command.setError(null);
  }
  return (
    <section
      className="review-panel document-upload"
      aria-label={pending ? "대기 파일 업로드" : "새 문서 첨부"}
    >
      <h3>{pending ? "대기 파일 업로드" : "새 문서 첨부"}</h3>
      {pending && (
        <p>
          처음 선택한 {pending.original_name} 파일을 다시 선택해 주세요. 같은
          이름·형식·크기·내용이어야 해요.
        </p>
      )}
      <form onSubmit={(e) => void submit(e)}>
        <fieldset disabled={command.busy || started}>
          <legend>첨부할 파일</legend>
          <label>
            문서 파일
            <input
              ref={input}
              type="file"
              accept="application/pdf,image/jpeg,image/png"
              onChange={(e) => {
                const selected = e.target.files?.[0] ?? null;
                file.current = selected;
                setChosen(selected?.name ?? "");
                setProblem(selected ? fileProblem(selected) : null);
                setAck(false);
              }}
            />
          </label>
          <label className="checkbox-field">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            카드 사진·전체 카드번호·CVC 등 카드 비밀정보가 없는 문서임을 확인했어요
          </label>
        </fieldset>
        {problem && <p role="alert">{problem}</p>}
        <CommandFeedback command={command} />
        {command.error?.status === 409 && (
          <button type="button" disabled={command.busy} onClick={() => void compare()}>
            현재 업로드 상태 비교
          </button>
        )}
        {latest && (
          <div className="review-panel">
            <p>
              현재: {latest.original_name} · {stateLabel(latest)} · 버전 {latest.version}
            </p>
            {latest.state === "ready" ? (
              <button
                type="button"
                onClick={() => {
                  clear();
                  saved(latest.id);
                }}
              >
                완료된 문서 확인
              </button>
            ) : (
              <button
                type="button"
                disabled={latest.state !== "pending" || expired(latest)}
                onClick={adopt}
              >
                현재 버전으로 같은 파일 업로드 준비
              </button>
            )}
          </div>
        )}
        <button
          type="submit"
          disabled={!chosen || !!problem || !ack || command.busy || command.error?.status === 409}
        >
          {started ? "같은 파일로 업로드 재시도" : "문서 업로드"}
        </button>
        {started && (
          <button
            type="button"
            disabled={command.busy}
            onClick={() => {
              clear();
              setChosen("");
              setStarted(false);
              setAck(false);
              setLatest(null);
              command.setError(null);
            }}
          >
            파일 선택 초기화
          </button>
        )}
        {started && (
          <p>
            재시도는 같은 문서 요청을 확인해요. 파일 선택을 초기화해도 이미 등록된 대기 기록은
            남으므로 목록에서 확인해 주세요.
          </p>
        )}
      </form>
    </section>
  );
}
