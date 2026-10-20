import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, toApiError } from "../../../platform/api";
import { isNativeAuth } from "../../../platform/nativeAuth";
import { nativeFinance } from "../../../platform/nativeFinance";
import { useAuth } from "../../auth/AuthProvider";
import { useMounted } from "../../auth/AuthFeedback";
import { useAuthCeremony } from "../../auth/useAuthCeremony";
import { InsuranceError } from "../InsuranceSupport";
import type { Policy } from "../model";
import { ReturnLoginLink } from "../../auth/ReturnLoginLink";

/** Only this mounted web component can receive a full number; it never enters React state. */
function WebPolicyNumber({ policy, refresh }: { policy: Policy; refresh: () => void }) {
  const { domainApi } = useAuth();
  const mounted = useMounted();
  const ceremony = useAuthCeremony();
  const input = useRef<HTMLInputElement>(null);
  const output = useRef<HTMLOutputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generation = useRef(0);
  const [editing, setEditing] = useState(false);
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState("");
  const clear = useCallback(() => {
    generation.current++;
    ceremony.cancel();
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (input.current) input.current.value = "";
    if (output.current) output.current.textContent = "";
    if (mounted.current) {
      setVisible(false);
      setBusy(false);
    }
  }, [ceremony.cancel, mounted]);
  useEffect(() => {
    const hidden = () => {
      if (document.visibilityState !== "visible") clear();
    };
    window.addEventListener("blur", clear);
    window.addEventListener("pagehide", clear);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      clear();
      window.removeEventListener("blur", clear);
      window.removeEventListener("pagehide", clear);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [clear]);
  useEffect(() => {
    clear();
  }, [policy.version, clear]);
  async function reveal() {
    if (busy) return;
    clear();
    const current = generation.current;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      await ceremony.run(async (signal) => {
        const response = await domainApi.write((client) =>
          client.POST("/api/v1/insurance/policies/{policy_id}/reveal", {
            params: { path: { policy_id: policy.id } },
            signal,
          }),
        );
        try {
          if (
            signal.aborted ||
            current !== generation.current ||
            !mounted.current ||
            document.visibilityState !== "visible" ||
            !document.hasFocus()
          )
            return;
          if (response.id !== policy.id || response.display_for_seconds !== 30)
            throw new ApiError(0, "REQUEST_FAILED");
          if (output.current) output.current.textContent = response.policy_number;
          setVisible(true);
          timer.current = setTimeout(clear, 30_000);
        } finally {
          response.policy_number = "";
        }
      });
    } catch (failure) {
      if (mounted.current && current === generation.current) setError(toApiError(failure));
    } finally {
      if (mounted.current && current === generation.current) setBusy(false);
    }
  }
  async function save(event?: FormEvent, remove = false) {
    event?.preventDefault();
    if (busy) return;
    const body = { policy_number: remove ? null : (input.current?.value ?? "") };
    if (!remove && !body.policy_number) {
      setNotice("새 증권번호를 입력해 주세요.");
      return;
    }
    clear();
    const current = generation.current;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      await ceremony.run((signal) =>
        domainApi.write((client) =>
          client.PATCH("/api/v1/insurance/policies/{policy_id}", {
            body,
            params: {
              path: { policy_id: policy.id },
              header: { "If-Match": `"${policy.version}"` },
            },
            signal,
          }),
        ),
      );
      if (mounted.current && current === generation.current) {
        setEditing(false);
        refresh();
      }
    } catch (failure) {
      if (mounted.current && current === generation.current) {
        setError(toApiError(failure));
        setNotice("입력한 번호는 지웠어요. 최신 정보를 확인한 뒤 다시 입력해 주세요.");
      }
    } finally {
      body.policy_number = null;
      if (mounted.current && current === generation.current) setBusy(false);
    }
  }
  return (
    <>
      <p>
        전체 번호는 최대 30초 동안 보여요. 다른 창으로 이동하거나 화면을 떠나면 즉시 지워요.
        웹에서는 화면 캡처를 막을 수 없어요.
      </p>
      <output
        ref={output}
        className="revealed-number"
        aria-label="일시적으로 표시하는 전체 증권번호"
        hidden={!visible}
      />
      <div className="form-actions">
        {policy.has_number && (
          <button type="button" disabled={busy} onClick={() => void reveal()}>
            전체 증권번호 30초 보기
          </button>
        )}
        {visible && (
          <button type="button" onClick={clear}>
            전체 증권번호 숨기기
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            clear();
            setEditing((value) => !value);
            setError(null);
          }}
        >
          {editing ? "번호 입력 닫기" : "증권번호 등록·변경"}
        </button>
      </div>
      {editing && (
        <form className="finance-form" onSubmit={(event) => void save(event)} autoComplete="off">
          <div className="form-field">
            <label htmlFor="private-policy-number">새 증권번호</label>
            <input
              ref={input}
              id="private-policy-number"
              type="password"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              minLength={5}
              maxLength={64}
              required
              disabled={busy}
            />
            <p className="muted">
              기존 번호는 이 입력칸에 넣지 않아요. 저장이나 화면 이동 후 입력값을 지워요.
            </p>
          </div>
          <div className="form-actions">
            <button type="submit" disabled={busy}>
              증권번호 저장
            </button>
            {policy.has_number && (
              <button type="button" disabled={busy} onClick={() => void save(undefined, true)}>
                저장된 증권번호 삭제
              </button>
            )}
          </div>
        </form>
      )}
      {busy && <p role="status">증권번호 요청을 처리하고 있어요.</p>}
      <InsuranceError error={error} />
      {notice && <p role="status">{notice}</p>}
      {error?.code === "REAUTHENTICATION_REQUIRED" && (
        <div className="form-actions">
          <ReturnLoginLink>비밀번호로 다시 인증</ReturnLoginLink>
        </div>
      )}
      {error?.code === "VERSION_CONFLICT" && (
        <button type="button" onClick={refresh}>
          최신 보험 계약 정보 다시 확인
        </button>
      )}
    </>
  );
}

function NativePolicyNumber({ policy, refresh }: { policy: Policy; refresh: () => void }) {
  const { domainApi } = useAuth();
  const mounted = useMounted();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState("");
  async function run(kind: "edit" | "show") {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      const result =
        kind === "edit"
          ? await domainApi.write(undefined, () =>
              nativeFinance.editInsurancePolicyNumber({
                policyId: policy.id,
                ifMatch: `"${policy.version}"`,
              }),
            )
          : await domainApi.write(undefined, () =>
              nativeFinance.showInsurancePolicyNumber({ policyId: policy.id }),
            );
      if (mounted.current) {
        if (result.status === "cancelled") setNotice("증권번호 작업을 취소했어요.");
        else setNotice("증권번호 작업을 마쳤어요.");
      }
    } catch (failure) {
      if (mounted.current) setError(toApiError(failure));
    } finally {
      if (mounted.current) {
        setBusy(false);
        refresh();
      }
    }
  }
  return (
    <>
      <p>증권번호 입력과 전체 번호 확인은 Android 보호 화면에서 진행해요.</p>
      <div className="form-actions">
        <button type="button" disabled={busy} onClick={() => void run("edit")}>
          Android에서 증권번호 관리
        </button>
        {policy.has_number && (
          <button type="button" disabled={busy} onClick={() => void run("show")}>
            Android에서 전체 증권번호 보기
          </button>
        )}
      </div>
      <InsuranceError error={error} />
      {notice && <p role="status">{notice}</p>}
      {error?.code === "REAUTHENTICATION_REQUIRED" && (
        <div className="form-actions">
          <ReturnLoginLink>다시 인증</ReturnLoginLink>
        </div>
      )}
      {error?.code === "VERSION_CONFLICT" && (
        <button type="button" onClick={refresh}>
          최신 보험 계약 정보 다시 확인
        </button>
      )}
    </>
  );
}

export function PolicyNumber({ policy, refresh }: { policy: Policy; refresh: () => void }) {
  return (
    <section className="card">
      <h2>증권번호</h2>
      <p>
        {policy.has_number ? (policy.masked_number ?? "마스킹 정보 확인 필요") : "증권번호 미등록"}
      </p>
      {isNativeAuth() ? (
        <NativePolicyNumber policy={policy} refresh={refresh} />
      ) : (
        <WebPolicyNumber policy={policy} refresh={refresh} />
      )}
    </section>
  );
}
