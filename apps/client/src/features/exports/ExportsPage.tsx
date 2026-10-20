import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { supportsWebAuthn } from "../../platform/webauthn";
import { SessionStatus, useMounted } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import { useDocumentsApi } from "../documents/api";
import type { Document } from "../documents/model";
import { DocumentPicker } from "./DocumentPicker";
import { ExportError } from "./ExportFeedback";
import { useExportsApi } from "./api";
import { saveExport } from "./download";
import type { ExportFile, ExportProgress } from "./download";
import { byteLabel, exportable, EXPORT_TIMEOUT_MS, selectionProblem } from "./model";
import type { ExportFormat } from "./model";

function ExportForm() {
  const api = useExportsApi();
  const documentsApi = useDocumentsApi();
  const mounted = useMounted();
  const native = isNativeAuth();
  const controller = useRef<AbortController | null>(null);
  const [formats, setFormats] = useState<ExportFormat[]>(["json", "csv"]),
    [selected, setSelected] = useState<Document[]>([]);
  const [picker, setPicker] = useState(false),
    [ack, setAck] = useState(false),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null),
    [notice, setNotice] = useState("");
  const [progress, setProgress] = useState<ExportProgress | null>(null);
  const problem = selectionProblem(formats, selected);
  const total = selected.reduce((sum, row) => sum + row.size_bytes, 0);
  useEffect(() => {
    const cancel = () => controller.current?.abort();
    window.addEventListener("pagehide", cancel);
    return () => {
      cancel();
      window.removeEventListener("pagehide", cancel);
    };
  }, []);
  function changeFormats(format: ExportFormat, checked: boolean) {
    setFormats((old) => (checked ? [...old, format] : old.filter((value) => value !== format)));
    setAck(false);
    setNotice("");
  }
  function changeSelection(rows: Document[]) {
    setSelected(rows);
    setAck(false);
    setNotice("");
  }
  async function refreshSelection() {
    if (controller.current) return;
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError(null);
    setNotice("");
    setAck(false);
    try {
      const rows = await Promise.all(
        selected.map(async (row) => {
          try {
            const latest = await documentsApi.get(row.id, current.signal);
            return exportable(latest) ? latest : null;
          } catch (failure) {
            const next = toApiError(failure);
            if ([403, 404, 409].includes(next.status)) return null;
            throw failure;
          }
        }),
      );
      current.signal.throwIfAborted();
      if (!mounted.current) return;
      const valid = rows.filter((row): row is Document => row !== null);
      setSelected(valid);
      setNotice(
        valid.length === rows.length
          ? "선택 문서의 최신 상태를 확인했어요. 내용과 저장 주의사항을 다시 검토해 주세요."
          : "더 이상 내보낼 수 없는 문서를 선택에서 제외했어요. 남은 문서와 크기를 확인해 주세요.",
      );
    } catch (failure) {
      if (mounted.current) setError(toApiError(failure));
    } finally {
      if (controller.current === current) controller.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  async function download(passkey = false) {
    if (controller.current || problem || !ack) return;
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError(null);
    setNotice("");
    setProgress({ phase: "preparing", received: 0, total: null });
    let timedOut = false;
    let file: ExportFile | undefined;
    // Native authentication, picker, transfer and provider writes own separate
    // deadlines. A web transfer timer must not discard a valid native completion.
    const timeout = native
      ? undefined
      : setTimeout(() => {
          timedOut = true;
          current.abort();
        }, EXPORT_TIMEOUT_MS);
    try {
      const input = {
        formats: [...formats].sort() as ExportFormat[],
        document_ids: selected.map((row) => row.id),
      };
      if (native) {
        const result = await api.nativeExport(input, current.signal);
        current.signal.throwIfAborted();
        if (!mounted.current) return;
        setNotice(
          result.status === "exported"
            ? "Android 보호 화면에서 내보내기를 마쳤어요. 선택한 저장 위치에서 파일을 확인해 주세요."
            : "내보내기를 취소했어요.",
        );
        return;
      }
      file = await api.webExport(
        input,
        current.signal,
        (value) => {
          if (mounted.current && !current.signal.aborted) setProgress(value);
        },
        passkey,
      );
      current.signal.throwIfAborted();
      if (!mounted.current) return;
      saveExport(file, current.signal);
      setNotice(
        `ZIP ${byteLabel(file.size)}의 무결성을 확인하고 저장 요청을 보냈어요. 브라우저의 다운로드 목록에서 실제 저장 결과를 확인해 주세요. 다음 내보내기는 새 시점의 자료를 만들어요.`,
      );
    } catch (failure) {
      if (mounted.current)
        setError(timedOut ? new ApiError(408, "EXPORT_TIMEOUT") : toApiError(failure));
    } finally {
      clearTimeout(timeout);
      file?.bytes.fill(0);
      if (controller.current === current) controller.current = null;
      if (mounted.current) {
        setBusy(false);
        setProgress(null);
        setAck(false);
      }
    }
  }
  return (
    <>
      <section className="card">
        <h2>현재 가계의 업무 기록</h2>
        <p>
          자산·계좌·카드 일반정보, 수입·고정 지출, 보험·진료·청구·지급, 가전·소모품·재고와 문서
          목록·연결 이력을 ZIP으로 받아요. 화면에서 보고 있는 월이나 목록의 일부만 내보내는 기능은
          아니에요.
        </p>
        <p>
          월별 원본·정정 기록과 연결 ID를 유지해요. 이 파일은 사용자 자료이며 서버 전체를 복원하는
          운영 백업은 아니에요.
        </p>
        <fieldset disabled={busy}>
          <legend>ZIP에 넣을 데이터 형식</legend>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={formats.includes("json")}
              onChange={(event) => changeFormats("json", event.target.checked)}
            />
            JSON — 원래 값과 구조를 보존하는 교환용
          </label>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={formats.includes("csv")}
              onChange={(event) => changeFormats("csv", event.target.checked)}
            />
            CSV — 표로 살펴보기
          </label>
        </fieldset>
        {formats.includes("csv") && (
          <p className="muted">
            CSV는 금액을 포함한 문자열 앞에 <code>text:</code>를 붙여 수식 실행 위험을 줄여요.
            미입력은 <code>\N</code>, 빈 문자열은 <code>text:</code>로 구분해요. 원래 값을 다른
            프로그램으로 옮길 때는 JSON을 권장해요.
          </p>
        )}
      </section>
      <section className="card">
        <h2>문서 원본 포함 여부</h2>
        <p>
          기본값은 원본 제외예요. 문서 목록과 연결 이력은 업무 기록에 포함되며, 아래에서 고른
          PDF·사진 원본만 ZIP에 추가돼요.
        </p>
        <p aria-live="polite">
          선택 문서 {selected.length} / 10개 · {byteLabel(total)} / 40MiB
        </p>
        <div className="form-actions">
          <button type="button" disabled={busy} onClick={() => setPicker((value) => !value)}>
            {picker ? "문서 선택 목록 닫기" : "문서 원본 선택 열기"}
          </button>
          {selected.length > 0 && (
            <>
              <button type="button" disabled={busy} onClick={() => changeSelection([])}>
                선택 문서 모두 해제
              </button>
              <button type="button" disabled={busy} onClick={() => void refreshSelection()}>
                선택 문서 새로 확인
              </button>
            </>
          )}
        </div>
        {selected.length > 0 && (
          <ul className="record-list">
            {selected.map((row) => (
              <li key={row.id}>
                {row.original_name} · {byteLabel(row.size_bytes)}{" "}
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => changeSelection(selected.filter((item) => item.id !== row.id))}
                  aria-label={`${row.original_name} 선택 해제`}
                >
                  선택 해제
                </button>
              </li>
            ))}
          </ul>
        )}
        {picker && <DocumentPicker selected={selected} busy={busy} changed={changeSelection} />}
      </section>
      <section className="card">
        <h2>저장 전에 확인해 주세요</h2>
        <p>
          전체 카드번호·유효기간·CVC/CVV, 보관함 비밀·암호문·키, 전체 계좌번호·증권번호,
          로그인·인증·세션 비밀은 포함하지 않아요.
        </p>
        <p>
          진료 기록과 사용자 메모는 포함돼요. 선택한 문서 원본 안의 민감한 내용은 자동으로 지우지
          않아요. ZIP은 암호화된 보관함 파일이 아니므로 저장 위치와 공유 대상을 확인해 주세요.
        </p>
        <p>
          저장된 파일은 앱 잠금·로그아웃·서버 삭제 뒤에도 남고, 앱에서 회수하거나 만료시킬 수
          없어요.
        </p>
        <p>
          최근 5분 이내의 계정 로그인 또는 재인증이 필요해요. 서버가 파일 발급 직전에 현재 권한을
          다시 확인해요.
        </p>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={ack}
            disabled={busy}
            onChange={(event) => setAck(event.target.checked)}
          />
          민감한 업무 기록이 포함될 수 있고 저장한 파일을 앱에서 회수할 수 없음을 확인했어요
        </label>
        {problem && <p role="alert">{problem}</p>}
        <ExportError error={error} />
        {notice && <p role="status">{notice}</p>}
        {busy && (
          <p role="status">
            {!progress
              ? "선택 문서의 최신 상태를 확인하고 있어요."
              : native
                ? "Android 보호 화면에서 인증과 저장을 진행해 주세요."
                : progress.phase === "receiving"
                  ? `ZIP을 받고 있어요. ${byteLabel(progress.received)} / ${byteLabel(progress.total ?? 0)}`
                  : progress.phase === "verifying"
                    ? "ZIP의 크기와 체크섬을 확인하고 있어요."
                    : "선택한 자료를 확인하고 ZIP을 준비하고 있어요."}
          </p>
        )}
        <div className="form-actions">
          <button
            type="button"
            disabled={busy || !!problem || !ack}
            onClick={() => void download()}
          >
            {native ? "Android에서 ZIP 내보내기" : "ZIP 내보내기·저장"}
          </button>
          {!native && (
            <button
              type="button"
              disabled={busy || !!problem || !ack || !supportsWebAuthn()}
              onClick={() => void download(true)}
            >
              패스키로 확인하고 ZIP 내보내기
            </button>
          )}
          {busy && (
            <button
              type="button"
              className="secondary-button"
              onClick={() => controller.current?.abort()}
            >
              내보내기 대기 중단
            </button>
          )}
          <Link to="/login">계정 다시 인증</Link>
        </div>
        <p className="muted">
          최대 100,000행·업무 기록 16MiB·ZIP 64MiB까지 준비해요. 한도를 넘으면 일부 파일만 성공
          처리하지 않아요. 준비는 최대 30초, 파일 전송은 최대 120초이며 실패하거나 중단한 요청을
          자동으로 다시 보내지 않아요.
        </p>
      </section>
    </>
  );
}
export function ExportsPage() {
  const { state } = useAuth();
  return (
    <div className="export-page">
      <div className="intro">
        <p className="eyebrow">내 가계 자료 보관</p>
        <h1>자료 내보내기</h1>
        <p>공동 가계의 업무 기록과 선택한 문서 원본을 파일로 받아요.</p>
      </div>
      {state.status === "authenticated" ? (
        <ExportForm key={state.member.member_id} />
      ) : (
        <SessionStatus />
      )}
    </div>
  );
}
