import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { useMounted } from "../auth/AuthFeedback";
import { CashflowError } from "../finance/FinancialFeedback";
import {
  useHouseholdMembers,
  MemberLoadError,
  dateLabel,
  todaySeoul,
} from "../finance/FinanceSupport";
import { AccountSelect } from "../finance/AccountChoices";
import { ClosureReview, useClosureReview } from "../finance/PaymentLinks";
import { useCardsApi } from "./api";
import { cardDraft, cardInput, cardEndDateError, cardTypes, preserveCardChanges } from "./model";
import type { Card, CardDraft, CardPatch } from "./model";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
export function CardEditor({ initial }: { initial?: Card }) {
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const api = useCardsApi();
  const navigate = useNavigate();
  const members = useHouseholdMembers();
  const mounted = useMounted();
  const flight = useRef(false);
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => cardDraft(initial));
  const [error, setError] = useState<ApiError | null>(null);
  const [validation, setValidation] = useState("");
  const [busy, setBusy] = useState(false);
  const [latest, setLatest] = useState<Card | null>(null);
  const [conflict, setConflict] = useState(false);
  const endError = cardEndDateError(draft.ended, draft.started);
  const closing = !!base && !!draft.ended && draft.ended !== (base.ended_on ?? "");
  const closure = useClosureReview("card", base?.id ?? "", draft.ended, closing && !endError);
  function change(field: keyof CardDraft, value: string) {
    setDraft((old) => ({ ...old, [field]: value }));
    setValidation("");
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (flight.current || conflict || !closure.ready) return;
    const input = cardInput(
      base?.has_secret ? { ...draft, lastFour: base.last_four ?? "" } : draft,
    );
    if (!input) {
      setValidation(
        cardEndDateError(draft.ended, draft.started) ||
          "소유자·카드사·카드명과 마지막 네 자리, 결제일, 날짜를 확인해 주세요.",
      );
      return;
    }
    const before = base ? cardInput(cardDraft(base))! : null;
    const changes = before
      ? (Object.fromEntries(
          Object.entries(input).filter(
            ([key, value]) => before[key as keyof typeof before] !== value,
          ),
        ) as Omit<CardPatch, "closure_ack">)
      : null;
    if (changes && !Object.keys(changes).length) {
      setValidation("변경한 내용이 없어요.");
      return;
    }
    flight.current = true;
    setBusy(true);
    setError(null);
    try {
      const row =
        base && changes
          ? await api.update(
              base.id,
              { ...changes, ...(closing ? closure.proof : { closure_ack: false }) },
              base.version,
            )
          : await api.create(input);
      if (mounted.current) {
        guard.release();
        navigate(`/cards/${row.id}`, { replace: true });
      }
    } catch (failure) {
      if (mounted.current) {
        const value = toApiError(failure);
        setError(value);
        if (value.code === "VERSION_CONFLICT") setConflict(true);
        if (
          value.code === "PAYMENT_LINKS_CHANGED" ||
          value.code === "PAYMENT_LINK_CONFIRMATION_REQUIRED"
        )
          closure.refresh();
      }
    } finally {
      flight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function compare() {
    if (!base || flight.current) return;
    flight.current = true;
    setBusy(true);
    try {
      const row = await api.get(base.id);
      if (mounted.current) setLatest(row);
    } catch (error) {
      if (mounted.current) setError(toApiError(error));
    } finally {
      flight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <section className="card">
      <h2>{base ? "카드 일반정보 수정" : "카드 일반정보 등록"}</h2>
      <p>카드 식별에는 별칭과 마지막 네 자리만 사용해요. 보호된 정보는 별도 보관함에서 다뤄요.</p>
      <form onInput={() => setDirty(true)} onSubmit={(event) => void submit(event)}>
        <fieldset disabled={busy || members.loading}>
          <legend>카드 기본정보</legend>
          <div className="form-grid">
            <div className="form-field">
              <label>
                카드 소유자
                <select
                  value={draft.owner}
                  onChange={(event) => change("owner", event.target.value)}
                  required
                >
                  <option value="">소유자 선택</option>
                  {members.members.map((m) => (
                    <option key={m.member_id} value={m.member_id}>
                      {m.display_name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-field">
              <label>
                카드사
                <input
                  value={draft.issuer}
                  maxLength={120}
                  onChange={(event) => change("issuer", event.target.value)}
                  required
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                카드명
                <input
                  value={draft.product}
                  maxLength={120}
                  onChange={(event) => change("product", event.target.value)}
                  required
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                카드 별칭
                <input
                  value={draft.alias}
                  maxLength={80}
                  onChange={(event) => change("alias", event.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                카드 유형
                <select value={draft.type} onChange={(event) => change("type", event.target.value)}>
                  {Object.entries(cardTypes).map(([key, name]) => (
                    <option key={key} value={key}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-field">
              <label>
                마지막 네 자리 (선택)
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{4}"
                  maxLength={4}
                  autoComplete="off"
                  disabled={base?.has_secret}
                  aria-describedby={base?.has_secret ? "card-last-four-vault" : undefined}
                  value={draft.lastFour}
                  onChange={(event) => change("lastFour", event.target.value)}
                />
              </label>
              {base?.has_secret && (
                <p id="card-last-four-vault">
                  보관함에 카드 비밀이 있어 마지막 네 자리는 여기서 수정할 수 없어요.{" "}
                  <Link to={`/cards/${base.id}`}>카드 보관함에서 번호 수정</Link>을 이용해 주세요.
                  별칭 등 일반정보는 계속 수정할 수 있어요.
                </p>
              )}
            </div>
            <div className="form-field">
              <label>
                카드 결제일 (매월)
                <input
                  type="number"
                  min={1}
                  max={31}
                  value={draft.settlementDay}
                  onChange={(event) => change("settlementDay", event.target.value)}
                />
              </label>
            </div>
            <AccountSelect
              label="카드 결제계좌"
              value={draft.account}
              onChange={(value) => change("account", value)}
            />
            <div className="form-field">
              <label>
                카드 사용 시작일
                <input
                  type="date"
                  value={draft.started}
                  onChange={(event) => change("started", event.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                카드 사용 종료일
                <input
                  type="date"
                  value={draft.ended}
                  min={draft.started || undefined}
                  max={todaySeoul()}
                  aria-invalid={!!endError}
                  aria-describedby={endError ? "card-ended-error" : undefined}
                  onChange={(event) => change("ended", event.target.value)}
                />
              </label>
              {endError && (
                <p id="card-ended-error" role="alert">
                  {endError}
                </p>
              )}
            </div>
            <div className="form-field">
              <label>
                카드 메모
                <textarea
                  value={draft.note}
                  maxLength={500}
                  onChange={(event) => change("note", event.target.value)}
                />
              </label>
            </div>
          </div>
        </fieldset>
        <MemberLoadError error={members.error} retry={members.retry} />
        {closing && !endError && <ClosureReview review={closure} disabled={busy} />}
        {validation && !endError && <p role="alert">{validation}</p>}
        <CashflowError error={error} />
        {conflict && (
          <section className="review-panel">
            <h3>카드 수정 충돌 확인</h3>
            <p>작성 중인 내용을 유지했어요. 현재 카드와 비교한 뒤 다시 저장해 주세요.</p>
            <button type="button" disabled={busy} onClick={() => void compare()}>
              현재 카드와 비교
            </button>
            {latest && (
              <>
                <dl className="metadata-grid">
                  <div>
                    <dt>현재 카드사·카드명</dt>
                    <dd>
                      {latest.issuer_name} · {latest.product_name}
                    </dd>
                  </div>
                  <div>
                    <dt>현재 별칭</dt>
                    <dd>{latest.alias || "없음"}</dd>
                  </div>
                  <div>
                    <dt>현재 마지막 네 자리</dt>
                    <dd>{latest.masked_number || "미입력"}</dd>
                  </div>
                  <div>
                    <dt>현재 소유자·유형</dt>
                    <dd>
                      {members.members.find((member) => member.member_id === latest.owner_member_id)
                        ?.display_name ?? "구성원 확인 필요"}{" "}
                      · {cardTypes[latest.card_type]}
                    </dd>
                  </div>
                  <div>
                    <dt>현재 결제일·계좌</dt>
                    <dd>
                      {latest.settlement_day ? `매월 ${latest.settlement_day}일` : "결제일 미입력"}{" "}
                      ·{" "}
                      {latest.settlement_account_id ? (
                        <Link to={`/accounts/${latest.settlement_account_id}`}>
                          현재 연결 계좌 확인
                        </Link>
                      ) : (
                        "계좌 연결 안 함"
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>현재 시작일 / 종료일</dt>
                    <dd>
                      {dateLabel(latest.started_on)} / {dateLabel(latest.ended_on)}
                    </dd>
                  </div>
                  <div>
                    <dt>현재 메모</dt>
                    <dd>{latest.note || "없음"}</dd>
                  </div>
                  <div>
                    <dt>현재 상태·버전</dt>
                    <dd>
                      {latest.status === "active" ? "사용 중" : "사용 종료"} · {latest.version}
                    </dd>
                  </div>
                </dl>
                <p>내가 바꾼 항목만 유지하고 나머지는 현재 카드 정보를 사용해요.</p>
                <button
                  type="button"
                  onClick={() => {
                    setDraft({
                      ...preserveCardChanges(cardDraft(base), draft, cardDraft(latest)),
                      ...(latest.has_secret ? { lastFour: latest.last_four ?? "" } : {}),
                    });
                    setBase(latest);
                    setLatest(null);
                    setConflict(false);
                    setError(null);
                    closure.refresh();
                  }}
                >
                  비교한 카드 변경 유지
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setDraft(cardDraft(latest));
                    setBase(latest);
                    setLatest(null);
                    setConflict(false);
                    setError(null);
                    closure.refresh();
                  }}
                >
                  현재 카드 내용으로 교체
                </button>
              </>
            )}
          </section>
        )}
        {error && !base && error.status === 0 && (
          <p>
            등록됐을 수 있으니 <Link to="/cards">카드 목록</Link>에서 먼저 확인해 주세요. 자동으로
            다시 등록하지 않아요.
          </p>
        )}
        <div className="form-actions">
          <button
            type="submit"
            disabled={
              busy || conflict || !!endError || !closure.ready || members.loading || !!members.error
            }
          >
            {busy ? "저장 결과 확인 중…" : base ? "카드 변경 저장" : "카드 등록 저장"}
          </button>
        </div>
      </form>
    </section>
  );
}
