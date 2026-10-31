import { useEffect, useRef, useState } from "react";
import type { components } from "@sallimbook/api-client";
import { toApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { nativeStoredCards } from "../../platform/nativeStoredCards";
import { useAuth } from "../auth/AuthProvider";

type Card = components["schemas"]["CardResponse"];
type Action = "view" | "edit" | "delete";

export function StoredCardDetails({ card, onCompleted }: { card: Card; onCompleted: () => void }) {
  const { domainApi } = useAuth();
  const [action, setAction] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const flight = useRef(false);
  const [message, setMessage] = useState("");
  async function open(next: Action) {
    if (flight.current) return;
    setMessage("");
    if (!isNativeAuth()) {
      setAction(next);
      return;
    }
    flight.current = true;
    setBusy(true);
    try {
      const result = await domainApi.read(undefined, () =>
        nativeStoredCards.open({ action: next, cardId: card.id }),
      );
      if (result.status === "completed") {
        setMessage("카드 상세정보 작업을 마쳤어요.");
        onCompleted();
      }
    } catch {
      setMessage("카드 상세정보를 열지 못했어요. 앱 연결 상태를 확인해 주세요.");
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="card" aria-label="저장된 카드 상세정보">
      <h2>카드 상세정보</h2>
      <p>{card.has_stored_details ? "번호·유효기간·CVC 저장됨" : "번호·유효기간·CVC 미등록"}</p>
      <p className="muted">
        로그인한 부부가 별도 암호 없이 확인해요. 정보는 서버에 암호화해 보관합니다.
      </p>
      <div className="form-actions">
        {card.has_stored_details && (
          <button disabled={busy || action !== null} onClick={() => void open("view")}>
            전체 카드정보 보기
          </button>
        )}
        <button
          disabled={busy || action !== null || card.has_secret}
          onClick={() => void open("edit")}
        >
          번호·유효기간·CVC 입력
        </button>
        {card.has_stored_details && (
          <button
            className="secondary-button"
            disabled={busy || action !== null}
            onClick={() => void open("delete")}
          >
            카드 상세정보 삭제
          </button>
        )}
      </div>
      {card.has_secret && <p>이 카드의 정보는 아래 암호 보관함에 저장되어 있어요.</p>}
      {message && <p role="status">{message}</p>}
      {action && (
        <WebStoredCardAction
          key={`${card.id}:${action}`}
          card={card}
          action={action}
          onClose={() => setAction(null)}
          onDone={() => {
            setAction(null);
            setMessage(
              action === "delete" ? "카드 상세정보를 삭제했어요." : "카드 상세정보를 저장했어요.",
            );
            onCompleted();
          }}
        />
      )}
    </section>
  );
}

function WebStoredCardAction({
  card,
  action,
  onClose,
  onDone,
}: {
  card: Card;
  action: Action;
  onClose: () => void;
  onDone: () => void;
}) {
  const { domainApi } = useAuth();
  const root = useRef<HTMLElement>(null);
  const output = useRef<HTMLOutputElement>(null);
  const pan = useRef<HTMLInputElement>(null),
    year = useRef<HTMLInputElement>(null),
    month = useRef<HTMLInputElement>(null),
    cvc = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  const live = useRef(false),
    flight = useRef(false);
  const displayTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [locked, setLocked] = useState(false),
    [busy, setBusy] = useState(
      action === "view" || (action === "edit" && !!card.has_stored_details),
    );
  const [error, setError] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const version = useRef(card.version);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  }, [onDone]);
  useEffect(() => {
    if (isNativeAuth()) return;
    const scope = root.current!;
    const abort = new AbortController();
    controller.current = abort;
    live.current = true;
    let idle: ReturnType<typeof setTimeout>;
    const clear = () => {
      for (const input of scope.querySelectorAll<HTMLInputElement>("input[data-card-secret]"))
        input.value = "";
      if (output.current) output.current.textContent = "";
    };
    const lock = () => {
      live.current = false;
      abort.abort();
      clear();
      clearTimeout(idle);
      clearTimeout(displayTimer.current);
      setLocked(true);
      setBusy(false);
    };
    const touch = () => {
      clearTimeout(idle);
      idle = setTimeout(lock, 5 * 60_000);
    };
    const hidden = () => {
      if (document.visibilityState !== "visible") lock();
    };
    window.addEventListener("blur", lock);
    window.addEventListener("pagehide", lock);
    document.addEventListener("visibilitychange", hidden);
    scope.addEventListener("input", touch);
    touch();
    if (action === "view" || (action === "edit" && card.has_stored_details)) {
      flight.current = true;
      void domainApi
        .write(
          (c) =>
            c.POST("/api/v1/cards/{card_id}/stored-details/reveal", {
              params: { path: { card_id: card.id } },
              signal: abort.signal,
            }),
          undefined,
          undefined,
          { clearOnExpiry: true },
        )
        .then((value) => {
          if (!live.current || abort.signal.aborted) return;
          if (value.card_id !== card.id || value.household_id !== card.household_id) {
            lock();
            return;
          }
          version.current = value.version;
          if (action === "view") {
            output.current!.textContent = `${value.pan} · ${String(value.expiry_month).padStart(2, "0")}/${value.expiry_year} · CVC ${value.cvc ?? "미등록"}`;
            displayTimer.current = setTimeout(lock, 30_000);
          } else {
            pan.current!.value = value.pan;
            year.current!.value = String(value.expiry_year);
            month.current!.value = String(value.expiry_month);
            cvc.current!.value = value.cvc ?? "";
          }
        })
        .catch(() => {
          if (live.current && !abort.signal.aborted) {
            clear();
            setLoadFailed(true);
            setError("카드 상세정보를 불러오지 못했어요. 닫은 뒤 다시 열어 주세요.");
          }
        })
        .finally(() => {
          if (controller.current === abort) {
            flight.current = false;
            if (live.current && !abort.signal.aborted) setBusy(false);
          }
        });
    }
    return () => {
      live.current = false;
      abort.abort();
      clear();
      clearTimeout(idle);
      clearTimeout(displayTimer.current);
      window.removeEventListener("blur", lock);
      window.removeEventListener("pagehide", lock);
      document.removeEventListener("visibilitychange", hidden);
      scope.removeEventListener("input", touch);
    };
  }, [action, card.id, card.household_id, card.has_stored_details, domainApi]);
  async function save() {
    if (!live.current || flight.current || loadFailed || !controller.current || isNativeAuth())
      return;
    setError("");
    const number = (pan.current?.value ?? "").replace(/[\s-]/g, "");
    const y = year.current?.value ?? "",
      m = month.current?.value ?? "",
      code = cvc.current?.value ?? "";
    if (action === "edit") {
      if (!/^[0-9]{13,19}$/.test(number)) {
        setError("카드번호는 숫자 13~19자리로 입력해 주세요. 공백과 하이픈은 자동으로 빼요.");
        pan.current?.focus();
        return;
      }
      if (!/^\d{4}$/.test(y) || +y < 2000 || +y > 2199) {
        setError("유효기간 연도는 2000~2199년으로 입력해 주세요.");
        year.current?.focus();
        return;
      }
      if (!/^(?:[1-9]|0[1-9]|1[0-2])$/.test(m)) {
        setError("유효기간 월은 1~12로 입력해 주세요.");
        month.current?.focus();
        return;
      }
      if (code && !/^[0-9]{3,4}$/.test(code)) {
        setError("CVC는 숫자 3~4자리로 입력하거나 비워 두세요.");
        cvc.current?.focus();
        return;
      }
    }
    flight.current = true;
    setBusy(true);
    const params = { path: { card_id: card.id }, header: { "If-Match": `"${version.current}"` } };
    const signal = controller.current.signal;
    try {
      if (action === "delete")
        await domainApi.write(
          (c) => c.DELETE("/api/v1/cards/{card_id}/stored-details", { params, signal }),
          undefined,
          undefined,
          { clearOnExpiry: true },
        );
      else
        await domainApi.write(
          (c) =>
            c.PUT("/api/v1/cards/{card_id}/stored-details", {
              params,
              signal,
              body: { pan: number, expiry_year: +y, expiry_month: +m, cvc: code || null },
            }),
          undefined,
          undefined,
          { clearOnExpiry: true },
        );
      if (live.current && !signal.aborted) done.current();
    } catch (failure) {
      if (!live.current || signal.aborted) return;
      const problem = toApiError(failure);
      setError(
        problem.status === 409
          ? "다른 곳에서 카드가 변경됐어요. 닫고 다시 열면 최신 내용을 볼 수 있어요."
          : "저장 결과를 확인하지 못했어요. 닫고 카드의 저장 상태를 확인해 주세요.",
      );
    } finally {
      flight.current = false;
      if (live.current) setBusy(false);
    }
  }
  return (
    <section className="review-panel" ref={root} aria-label="카드 상세정보 보호 화면">
      <h3>
        {action === "view"
          ? "전체 카드정보"
          : action === "edit"
            ? "카드 상세정보 입력"
            : "저장한 상세정보 삭제"}
      </h3>
      <output
        ref={output}
        aria-label="일시적으로 표시하는 카드 상세정보"
        className="revealed-number"
      />
      {locked ? (
        <p role="status">화면을 잠갔어요.</p>
      ) : (
        <>
          {action === "view" && <p>30초 후 자동으로 가려요. 화면을 벗어나면 즉시 지워요.</p>}
          {action === "edit" && (
            <form
              autoComplete="off"
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                void save();
              }}
            >
              <fieldset disabled={busy || loadFailed}>
                <legend>카드번호·유효기간·CVC</legend>
                <label>
                  카드번호
                  <input
                    ref={pan}
                    data-card-secret
                    type="password"
                    inputMode="numeric"
                    autoComplete="off"
                    maxLength={40}
                  />
                </label>
                <label>
                  유효기간 연도
                  <input
                    ref={year}
                    data-card-secret
                    type="password"
                    inputMode="numeric"
                    autoComplete="off"
                    maxLength={4}
                  />
                </label>
                <label>
                  유효기간 월
                  <input
                    ref={month}
                    data-card-secret
                    type="password"
                    inputMode="numeric"
                    autoComplete="off"
                    maxLength={2}
                  />
                </label>
                <label>
                  CVC (선택)
                  <input
                    ref={cvc}
                    data-card-secret
                    type="password"
                    inputMode="numeric"
                    autoComplete="off"
                    maxLength={4}
                  />
                </label>
                <p className="muted">
                  CVC를 비우고 저장하면 기존 CVC도 삭제돼요. 입력한 번호는 그대로 보관하며 결제 가능
                  여부를 확인하는 기능은 아니에요.
                </p>
                <button type="submit">카드 상세정보 저장</button>
              </fieldset>
            </form>
          )}
          {action === "delete" && (
            <>
              <p>저장한 번호·유효기간·CVC를 삭제해요. 카드 기본정보는 남아요.</p>
              <button disabled={busy} onClick={() => void save()}>
                저장한 상세정보 삭제
              </button>
            </>
          )}
          {error && <p role="alert">{error}</p>}
        </>
      )}
      <button type="button" className="secondary-button" onClick={onClose}>
        카드 상세정보 닫기
      </button>
    </section>
  );
}
