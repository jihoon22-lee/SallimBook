import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, requireWebAuth } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { useAuth } from "../auth/AuthProvider";
import type { WebVaultActionProps } from "./actions";
import { VaultCryptoError, cardPayload, decode64, passwordBytes, wipe } from "./crypto";
import type { Bytes } from "./crypto";
import { VaultLifetime } from "./lifetime";
import { usePrivateVaultApi } from "./privateApi";
import { needsReauthentication, VaultWorkflow } from "./workflow";
import type { VaultInputs, VaultPublicContext } from "./workflow";
import { ReturnLoginLink } from "../auth/ReturnLoginLink";

const titles = {
  setup: "보관함 처음 설정",
  view: "보호된 카드 정보 보기",
  edit: "카드 번호·유효기간 입력",
  purge: "저장된 카드 비밀 삭제",
  "change-password": "보관함 암호 변경",
  recover: "복구코드로 보관함 복구",
  share: "배우자와 보관함 공유",
  "accept-share": "보관함 공유 수락",
  "cancel-share": "보관함 공유 요청 종료",
  "revoke-member": "보관함 접근 권한 철회",
  rotate: "보관함 키 전체 교체",
  "resume-rotation": "진행 중인 키 교체 이어가기",
  "abort-rotation": "진행 중인 키 교체 중단",
} as const;
function failureMessage(error: unknown): string {
  if (error instanceof VaultCryptoError)
    return "보관함 암호·복구코드와 입력 형식을 확인해 주세요. 보호된 정보는 표시하지 않았고 입력값은 지웠어요.";
  if (!(error instanceof ApiError)) return "작업 결과를 확인하지 못했어요. 보호된 입력은 지웠어요.";
  if (error.code === "REAUTHENTICATION_REQUIRED" || error.code === "STEP_UP_REQUIRED")
    return "최근 5분 이내의 계정 인증이 필요해요. 아래에서 계정 비밀번호를 다시 확인한 뒤 이어갈 수 있어요.";
  if (error.code === "REAUTHENTICATION_FAILED")
    return "계정 로그인 비밀번호를 확인해 다시 입력해 주세요.";
  if (error.status === 401) return "계정 로그인이 만료됐어요. 다시 로그인해 주세요.";
  if (error.code === "VAULT_ROTATION_IN_PROGRESS")
    return "진행 중인 키 교체를 마치거나 중단한 뒤 이 작업을 다시 시작해 주세요.";
  if (error.code === "VAULT_ROTATION_REQUIRED")
    return "접근 권한을 철회한 뒤에는 보관함 키 전체 교체를 먼저 마쳐 주세요.";
  if (error.code === "VAULT_NONCE_REUSED" || error.code === "VAULT_SALT_REUSED")
    return "안전한 새 암호화 값을 다시 준비해야 해요. 보호 작업을 닫았다가 다시 시작해 주세요.";
  if (error.status === 409)
    return "보관함 또는 카드 상태가 다른 곳에서 변경됐어요. 입력한 비밀은 지웠어요. 최신 상태를 확인한 뒤 다시 입력해 주세요.";
  if (error.status === 403) return "현재 계정의 보관함 공유 권한을 확인해 주세요.";
  if (error.status === 404)
    return "현재 보관함에서 이 항목을 찾을 수 없어요. 목록을 다시 확인해 주세요.";
  if (error.status === 422)
    return "입력한 카드 번호·유효기간·보관함 암호의 형식을 확인해 주세요. 입력한 비밀은 지웠어요.";
  return "저장 결과를 확인하지 못했어요. 저장됐을 수 있으므로 같은 요청의 결과나 현재 보관함 상태를 확인해 주세요.";
}

/** Only this mounted web component owns secret DOM fields. React state is public metadata/UI flags. */
export function WebVaultAction({ request, onClose, onCompleted }: WebVaultActionProps) {
  const { state } = useAuth();
  const api = usePrivateVaultApi();
  const me = state.status === "authenticated" ? state.member : null;
  const root = useRef<HTMLElement>(null),
    recoveryOutput = useRef<HTMLOutputElement>(null),
    cardOutput = useRef<HTMLOutputElement>(null);
  const accountPassword = useRef<HTMLInputElement>(null);
  const password = useRef<HTMLInputElement>(null),
    stagedPassword = useRef<HTMLInputElement>(null),
    code = useRef<HTMLInputElement>(null);
  const pan = useRef<HTMLInputElement>(null),
    year = useRef<HTMLInputElement>(null),
    month = useRef<HTMLInputElement>(null);
  const newPasswords = useRef(
    new Map<string, { first: HTMLInputElement | null; second: HTMLInputElement | null }>(),
  );
  const lifetime = useRef<VaultLifetime | null>(null),
    workflow = useRef<VaultWorkflow | null>(null),
    flight = useRef(false);
  const callbacks = useRef({ onClose, onCompleted });
  callbacks.current = { onClose, onCompleted };
  const [context, setContext] = useState<VaultPublicContext | null>(null),
    [busy, setBusy] = useState(false),
    [locked, setLocked] = useState(false);
  const [phase, setPhase] = useState<"form" | "confirm-recovery" | "displayed">("form"),
    [error, setError] = useState<unknown>(null);
  const [ack, setAck] = useState(false),
    [backupAck, setBackupAck] = useState(false),
    [reload, setReload] = useState(0);
  const [notice, setNotice] = useState(""),
    [reauthRequired, setReauthRequired] = useState(false);
  const [reason, setReason] = useState<VaultInputs["reason"]>("routine");
  const requestKey = JSON.stringify(request);

  useEffect(() => {
    if (!me || !root.current || isNativeAuth()) return;
    requireWebAuth();
    let active = true;
    setLocked(false);
    setBusy(true);
    setContext(null);
    setPhase("form");
    setError(null);
    setNotice("");
    setReauthRequired(false);
    setAck(false);
    setBackupAck(false);
    flight.current = true;
    const life = new VaultLifetime(root.current, () => {
      workflow.current?.dispose();
      workflow.current = null;
      if (active) {
        setLocked(true);
        setBusy(false);
        setPhase("form");
        setContext(null);
        flight.current = false;
      }
    });
    const work = new VaultWorkflow(
      api,
      me,
      request,
      life,
      (text) => {
        life.assert();
        if (recoveryOutput.current) recoveryOutput.current.textContent = text;
      },
      (text) => {
        life.assert();
        if (cardOutput.current) cardOutput.current.textContent = text;
      },
    );
    lifetime.current = life;
    workflow.current = work;
    void work
      .load()
      .then((value) => {
        if (active && !life.signal.aborted) {
          setContext(value);
          if (value.status.rotation_required) setReason("member_access_removed");
        }
      })
      .catch((failure) => {
        if (active && !life.signal.aborted)
          setError(failure instanceof ApiError ? failure : new VaultCryptoError());
      })
      .finally(() => {
        if (active && !life.signal.aborted) {
          setBusy(false);
          flight.current = false;
        }
      });
    return () => {
      active = false;
      life.close();
      work.dispose();
      if (lifetime.current === life) lifetime.current = null;
      if (workflow.current === work) workflow.current = null;
      flight.current = false;
    };
    // IDs and the authenticated identity define the operation. Parent callback identity does not.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `me` and `request` are tracked by the fields above.
  }, [api, me?.household_id, me?.member_id, me?.user_id, requestKey, reload]);

  const needsPassword = [
    "view",
    "edit",
    "change-password",
    "share",
    "accept-share",
    "rotate",
    "resume-rotation",
  ].includes(request.action);
  const needsAck = [
    "purge",
    "share",
    "cancel-share",
    "revoke-member",
    "rotate",
    "resume-rotation",
    "abort-rotation",
  ].includes(request.action);
  const preparedRotation =
    ["rotate", "resume-rotation"].includes(request.action) && context?.rotation?.key_check_prepared;
  const passwordMembers =
    !context || !me
      ? []
      : ["setup", "change-password", "recover"].includes(request.action)
        ? [me.member_id]
        : request.action === "share"
          ? [request.memberId]
          : request.action === "rotate" && !preparedRotation
            ? context.status.members
                .filter((member) => member.status === "active")
                .map((member) => member.member_id)
            : request.action === "resume-rotation" && !preparedRotation
              ? (context.rotation?.members.map((member) => member.member_id) ?? [])
              : [];
  function take(ref: HTMLInputElement | null, life: VaultLifetime, creating = false): Bytes {
    if (!ref) throw new VaultCryptoError();
    try {
      return life.ownBytes(passwordBytes(ref.value, creating));
    } finally {
      ref.value = "";
    }
  }
  function collect(life: VaultLifetime): VaultInputs {
    const input: VaultInputs = { newPasswords: new Map(), reason };
    try {
      if (needsPassword) input.password = take(password.current, life);
      if (preparedRotation) input.stagedPassword = take(stagedPassword.current, life);
      for (const memberId of passwordMembers) {
        const fields = newPasswords.current.get(memberId);
        if (!fields?.first || !fields.second || fields.first.value !== fields.second.value)
          throw new VaultCryptoError();
        input.newPasswords.set(memberId, take(fields.first, life, true));
        fields.second.value = "";
      }
      if (request.action === "recover") {
        try {
          input.recoveryCode = life.ownBytes(decode64(code.current?.value ?? "", 32));
        } finally {
          if (code.current) code.current.value = "";
        }
      }
      if (request.action === "edit") {
        const y = year.current?.value ?? "",
          m = month.current?.value ?? "";
        if (!/^\d{4}$/.test(y) || !/^(?:[1-9]|0[1-9]|1[0-2])$/.test(m))
          throw new VaultCryptoError();
        input.card = life.ownBytes(cardPayload(pan.current?.value ?? "", Number(y), Number(m)));
      }
      return input;
    } catch (failure) {
      life.clearSecrets();
      throw failure;
    } finally {
      life.clearDom();
    }
  }
  async function execute(kind: "run" | "confirm" | "retry") {
    const work = workflow.current,
      life = lifetime.current;
    if (
      !work ||
      !life ||
      flight.current ||
      !context ||
      locked ||
      (kind === "run" && needsAck && !ack) ||
      (kind === "confirm" && !backupAck)
    )
      return;
    flight.current = true;
    setBusy(true);
    setError(null);
    let input: VaultInputs | undefined;
    try {
      life.assert();
      if (kind === "retry") {
        if ((await work.retry()) === "completed") callbacks.current.onCompleted();
        else {
          setContext(work.context);
          setPhase("form");
          setAck(false);
          setNotice(
            "같은 요청의 저장 결과를 확인했어요. 보관함 암호를 다시 입력해 남은 키 교체를 계속해 주세요.",
          );
        }
        return;
      }
      if (kind === "confirm") {
        await work.confirmRecovery();
        callbacks.current.onCompleted();
        return;
      }
      input = collect(life);
      const outcome = await work.run(input);
      life.assert();
      if (outcome === "completed") {
        life.clearSecrets();
        callbacks.current.onCompleted();
      } else {
        setContext(work.context);
        setPhase(outcome);
        setBackupAck(false);
      }
    } catch (failure) {
      life.clearSecrets();
      if (!life.signal.aborted && workflow.current === work) {
        life.waitForInput();
        setContext(work.context);
        if (needsReauthentication(failure)) setReauthRequired(true);
        setError(failure instanceof ApiError ? failure : new VaultCryptoError());
        setPhase("form");
        setAck(false);
        setBackupAck(false);
      }
    } finally {
      for (const bytes of [
        input?.password,
        input?.stagedPassword,
        input?.recoveryCode,
        input?.card,
        ...(input?.newPasswords.values() ?? []),
      ]) {
        if (bytes) {
          life.forgetBytes(bytes);
          wipe(bytes);
        }
      }
      if (!life.signal.aborted && workflow.current === work) {
        setBusy(false);
        flight.current = false;
      }
    }
  }
  async function reauthenticate(event: FormEvent) {
    event.preventDefault();
    const work = workflow.current,
      life = lifetime.current;
    if (!work || !life || flight.current || !accountPassword.current) return;
    flight.current = true;
    setBusy(true);
    let value = accountPassword.current.value;
    accountPassword.current.value = "";
    try {
      await work.reauthenticate(value);
      value = "";
      life.assert();
      setContext(work.context);
      setError(null);
      setReauthRequired(false);
      setNotice(
        "계정 인증을 확인했어요. 보관함 암호를 다시 입력해 계속해 주세요. 이미 검증한 카드의 진행 위치는 이 화면에서만 유지돼요.",
      );
    } catch (failure) {
      if (!life.signal.aborted)
        setError(failure instanceof ApiError ? failure : new VaultCryptoError());
    } finally {
      value = "";
      if (!life.signal.aborted && workflow.current === work) {
        setBusy(false);
        flight.current = false;
      }
    }
  }
  function close() {
    lifetime.current?.close();
    callbacks.current.onClose();
  }
  function setPasswordRef(
    memberId: string,
    field: "first" | "second",
    node: HTMLInputElement | null,
  ) {
    const pair = newPasswords.current.get(memberId) ?? { first: null, second: null };
    pair[field] = node;
    newPasswords.current.set(memberId, pair);
  }
  if (isNativeAuth()) return <p role="alert">Android 보관함은 전용 보호 화면에서 열어 주세요.</p>;
  if (!me) return <p role="status">보관함을 사용하려면 로그인해 주세요.</p>;
  return (
    <section className="card vault-private" ref={root} aria-label="보관함 보호 작업">
      <h2>{titles[request.action]}</h2>
      <p>
        이 화면을 떠나거나 다른 창으로 이동하면 입력과 표시를 지워요. PC 웹은 화면 캡처를 막을 수
        없어요. CVC/CVV는 입력하지 마세요.
      </p>
      {notice && <p role="status">{notice}</p>}
      {context?.card && (
        <p>
          대상 카드: {context.card.alias || context.card.product_name} ·{" "}
          {context.card.masked_number ?? "번호 미등록"}
        </p>
      )}
      {locked && (
        <p role="status">
          화면 이동 또는 제한 시간으로 보관함을 잠갔어요. 보호된 정보와 입력값을 지웠어요.
        </p>
      )}
      <output
        ref={cardOutput}
        data-vault-output
        className="revealed-number"
        aria-label="일시적으로 표시하는 카드 번호와 유효기간"
        hidden={phase !== "displayed"}
      />
      {phase === "displayed" && (
        <p role="status">최대 30초 동안 보여요. 화면을 떠나거나 권한·카드 상태가 바뀌면 지워요.</p>
      )}
      <output
        ref={recoveryOutput}
        data-vault-output
        className="revealed-number"
        aria-label="새 보관함 복구코드"
        hidden={phase !== "confirm-recovery"}
      />
      {phase === "confirm-recovery" && (
        <div className="review-panel">
          <h3>새 복구코드를 보관해 주세요</h3>
          <p>
            아직 새 복구 설정을 서버에 저장하지 않았어요. 다른 기기나 종이에 기록해 안전하게
            보관하세요. 코드는 최대 30초 동안 표시하며 이 화면을 떠나도 지워요.
          </p>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={backupAck}
              disabled={busy}
              onChange={(event) => setBackupAck(event.target.checked)}
            />
            새 복구코드를 오프라인으로 보관했어요
          </label>
          <button
            type="button"
            disabled={!backupAck || busy}
            onClick={() => void execute("confirm")}
          >
            보관 확인·설정 완료
          </button>
        </div>
      )}
      {context && !locked && phase === "form" && (
        <form
          autoComplete="off"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            void execute("run");
          }}
        >
          <fieldset disabled={busy || !!error || workflow.current?.canRetry}>
            <legend>보호된 입력</legend>
            {needsPassword && (
              <div className="form-field">
                <label>
                  현재 보관함 암호
                  <input
                    ref={password}
                    data-vault-secret
                    type="password"
                    autoComplete="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    maxLength={1024}
                    required
                  />
                </label>
                <p className="muted">
                  로그인 암호와 다른 보관함 전용 암호예요. 앞뒤 공백과 문자를 입력한 그대로
                  사용해요.
                </p>
              </div>
            )}
            {request.action === "recover" && (
              <div className="form-field">
                <label>
                  보관 중인 복구코드
                  <input
                    ref={code}
                    data-vault-secret
                    type="password"
                    autoComplete="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    maxLength={43}
                    required
                  />
                </label>
              </div>
            )}
            {preparedRotation && (
              <div className="form-field">
                <label>
                  이번 키 교체에서 정한 내 새 보관함 암호
                  <input
                    ref={stagedPassword}
                    data-vault-secret
                    type="password"
                    autoComplete="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    maxLength={1024}
                    required
                  />
                </label>
              </div>
            )}
            {passwordMembers.map((memberId) => (
              <div className="form-grid" key={memberId}>
                <div className="form-field">
                  <label>
                    {context.members.find((member) => member.member_id === memberId)
                      ?.display_name ?? "구성원"}
                    의 새 보관함 암호
                    <input
                      ref={(node) => setPasswordRef(memberId, "first", node)}
                      data-vault-secret
                      type="password"
                      autoComplete="off"
                      autoCapitalize="none"
                      spellCheck={false}
                      maxLength={1024}
                      required
                    />
                  </label>
                  <p className="muted">
                    서로 다른 문자 12개 이상을 권장하며, 최소 12문자여야 해요. 로그인 암호나 짧은
                    PIN을 재사용하지 마세요.
                  </p>
                </div>
                <div className="form-field">
                  <label>
                    {context.members.find((member) => member.member_id === memberId)
                      ?.display_name ?? "구성원"}
                    의 새 보관함 암호 확인
                    <input
                      ref={(node) => setPasswordRef(memberId, "second", node)}
                      data-vault-secret
                      type="password"
                      autoComplete="off"
                      autoCapitalize="none"
                      spellCheck={false}
                      maxLength={1024}
                      required
                    />
                  </label>
                </div>
              </div>
            ))}
            {request.action === "edit" && (
              <div className="form-grid">
                <div className="form-field">
                  <label>
                    전체 카드 번호 (숫자만)
                    <input
                      ref={pan}
                      data-vault-secret
                      type="password"
                      inputMode="numeric"
                      autoComplete="off"
                      minLength={13}
                      maxLength={19}
                      required
                    />
                  </label>
                </div>
                <div className="form-field">
                  <label>
                    유효기간 연도 (4자리)
                    <input
                      ref={year}
                      data-vault-secret
                      type="password"
                      inputMode="numeric"
                      autoComplete="off"
                      maxLength={4}
                      required
                    />
                  </label>
                </div>
                <div className="form-field">
                  <label>
                    유효기간 월
                    <input
                      ref={month}
                      data-vault-secret
                      type="password"
                      inputMode="numeric"
                      autoComplete="off"
                      maxLength={2}
                      required
                    />
                  </label>
                </div>
              </div>
            )}
            {request.action === "rotate" && (
              <div className="form-field">
                <label>
                  키 전체 교체 사유
                  <select
                    value={reason}
                    onChange={(event) => setReason(event.target.value as VaultInputs["reason"])}
                  >
                    <option value="routine">정기적인 키 교체</option>
                    <option value="key_compromised">암호·키·복구코드 유출 우려</option>
                    <option value="member_access_removed">구성원 접근 권한 철회</option>
                  </select>
                </label>
              </div>
            )}
            {request.action === "purge" && (
              <p>
                이 카드의 현재와 과거 온라인 비밀을 모두 지워요. 일반 카드 정보·이력은 남으며, 이전
                백업이나 다른 기기에 저장된 사본을 회수할 수는 없어요.
              </p>
            )}
            {request.action === "share" && (
              <p>
                신뢰하는 이 화면에서 상대방이 자신의 새 보관함 암호를 직접 입력하세요. 상대방이 본인
                계정에서 수락해야 공유가 완료돼요.
              </p>
            )}
            {request.action === "revoke-member" && (
              <p>
                선택한 구성원의 보관함 접근을 막고 키 전체 교체가 필요해요. 이미 본 번호나 이전
                사본은 회수할 수 없어요.
              </p>
            )}
            {["rotate", "resume-rotation"].includes(request.action) && (
              <p>
                종료한 카드도 포함해 모든 비밀과 유지할 구성원의 설정을 준비한 뒤 한 번에 전환해요.
                화면을 닫아 중단해도 보관함에서 이어갈 수 있어요.
              </p>
            )}
            {request.action === "abort-rotation" && (
              <p>
                준비한 새 키를 사용하지 않고 현재 키를 유지해요. 이번에 발급한 새 복구코드는 사용할
                수 없어요.
              </p>
            )}
            {needsAck && (
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={ack}
                  onChange={(event) => setAck(event.target.checked)}
                />
                대상과 작업 내용을 확인했어요
              </label>
            )}
          </fieldset>
          <button
            type="submit"
            disabled={busy || !!error || workflow.current?.canRetry || (needsAck && !ack)}
          >
            {request.action === "view" ? "보관함 암호로 30초 보기" : "보호 작업 진행"}
          </button>
        </form>
      )}
      {busy && (
        <p role="status">
          보관함 작업을 처리하고 있어요. 저장 중 닫았다면 현재 상태에서 결과를 다시 확인해 주세요.
        </p>
      )}
      {error != null && (
        <div role="alert">
          <p>{failureMessage(error)}</p>
          <button type="button" disabled={busy} onClick={() => setReload((value) => value + 1)}>
            최신 보관함 상태 다시 확인
          </button>
          {error instanceof ApiError && error.status === 401 && (
            <ReturnLoginLink>계정 다시 로그인</ReturnLoginLink>
          )}
        </div>
      )}
      {!locked && reauthRequired && (
        <form autoComplete="off" onSubmit={(event) => void reauthenticate(event)}>
          <label>
            현재 계정 로그인 비밀번호
            <input
              ref={accountPassword}
              data-vault-secret
              type="password"
              autoComplete="current-password"
              maxLength={128}
              required
              disabled={busy}
            />
          </label>
          <button type="submit" disabled={busy}>
            이 화면에서 계정 다시 인증
          </button>
        </form>
      )}
      {!locked && workflow.current?.canRetry && (
        <button
          type="button"
          disabled={busy || reauthRequired}
          onClick={() => void execute("retry")}
        >
          같은 요청으로 저장 결과 확인
        </button>
      )}
      <button type="button" onClick={close}>
        보호 작업 닫기·잠금
      </button>
    </section>
  );
}
