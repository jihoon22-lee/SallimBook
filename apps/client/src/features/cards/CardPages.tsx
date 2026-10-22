import { FilterPanel } from "../../shared/TaskLayout";
import { useCallback, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { useMounted } from "../auth/AuthFeedback";
import { AuthenticatedFinance, CashflowError } from "../finance/FinancialFeedback";
import {
  MemberLoadError,
  dateLabel,
  isDateOnly,
  isUuid,
  todaySeoul,
  useHouseholdMembers,
} from "../finance/FinanceSupport";
import type { HouseholdMember } from "../finance/FinanceSupport";
import { useAccountChoices } from "../finance/AccountChoices";
import { usePagedList, useResource } from "../finance/queries";
import { useUrlFilters } from "../finance/useUrlFilters";
import { ClosureReview, useClosureReview } from "../finance/PaymentLinks";
import { useCardsApi } from "./api";
import { cardEndDateError, cardTypes } from "./model";
import type { Card, CardQuery } from "./model";
import { CardEditor } from "./CardEditor";
import { CardVaultActions } from "../vault/CardVaultActions";
export function CardSummary({
  card,
  members,
  showMask = true,
}: {
  card: Card;
  members: HouseholdMember[];
  showMask?: boolean;
}) {
  return (
    <>
      <dl className="metadata-grid">
        <div>
          <dt>소유자</dt>
          <dd>
            {members.find((m) => m.member_id === card.owner_member_id)?.display_name ??
              "구성원 확인 필요"}
          </dd>
        </div>
        <div>
          <dt>카드사·상품명</dt>
          <dd>
            {card.issuer_name} · {card.product_name}
          </dd>
        </div>
        <div>
          <dt>카드 유형</dt>
          <dd>{cardTypes[card.card_type]}</dd>
        </div>
        {showMask && (
          <div>
            <dt>마스킹 번호</dt>
            <dd>{card.masked_number || "마지막 네 자리 미입력"}</dd>
          </div>
        )}
        <div>
          <dt>결제일</dt>
          <dd>{card.settlement_day ? `매월 ${card.settlement_day}일` : "미입력"}</dd>
        </div>
        <div>
          <dt>결제계좌</dt>
          <dd>
            {card.settlement_account_id ? (
              <Link to={`/accounts/${card.settlement_account_id}`}>
                연결 계좌 확인{card.settlement_account_status === "closed" ? " · 사용 종료" : ""}
              </Link>
            ) : (
              "연결 안 함"
            )}
          </dd>
        </div>
        <div>
          <dt>사용 시작 / 종료</dt>
          <dd>
            {dateLabel(card.started_on)} / {dateLabel(card.ended_on)}
          </dd>
        </div>
        <div>
          <dt>상태</dt>
          <dd>{card.status === "active" ? "사용 중" : "사용 종료"}</dd>
        </div>
      </dl>
      {card.settlement_account_status === "closed" && (
        <p className="month-warning">
          연결된 결제계좌가 종료됐어요. 카드 정보를 수정해 사용 중인 계좌로 바꾸거나 연결을 해제해
          주세요.
        </p>
      )}
    </>
  );
}
function CardList() {
  const api = useCardsApi();
  const members = useHouseholdMembers();
  const accounts = useAccountChoices();
  const { params, filter, reset } = useUrlFilters();
  const owner = isUuid(params.get("owner") ?? "") ? params.get("owner")! : "";
  const type = ["credit", "debit"].includes(params.get("type") ?? "")
    ? (params.get("type") as CardQuery["card_type"])
    : undefined;
  const account = isUuid(params.get("account") ?? "") ? params.get("account")! : "";
  const status = ["active", "closed", "all"].includes(params.get("status") ?? "")
    ? (params.get("status") as CardQuery["status"])
    : "active";
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.list({
          status,
          limit: 50,
          ...(owner ? { owner_member_id: owner } : {}),
          ...(type ? { card_type: type } : {}),
          ...(account ? { settlement_account_id: account } : {}),
          ...(cursor ? { cursor } : {}),
        }),
      [api, owner, type, account, status],
    ),
    undefined,
    "cards",
  );
  return (
    <>
      <div className="form-actions">
        <Link className="button-link" to="/cards/new">
          카드 등록
        </Link>
        <Link to="/fixed-payments">고정 납부 확인</Link>
      </div>
      <FilterPanel
        title="카드 찾기"
        defaultLabel="사용 중"
        activeCount={
          [owner, type, account, status !== "active" ? status : ""].filter(Boolean).length
        }
      >
        <div className="filter-grid">
          <div className="form-field">
            <label>
              카드 소유자 필터
              <select value={owner} onChange={(event) => filter("owner", event.target.value)}>
                <option value="">전체 소유자</option>
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
              카드 유형 필터
              <select value={type ?? ""} onChange={(event) => filter("type", event.target.value)}>
                <option value="">신용·체크 모두</option>
                {Object.entries(cardTypes).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-field">
            <label>
              결제계좌 필터
              <select value={account} onChange={(event) => filter("account", event.target.value)}>
                <option value="">모든 계좌</option>
                {accounts.data?.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.asset.name}
                    {row.status === "closed" ? " · 사용 종료" : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-field">
            <label>
              카드 상태 필터
              <select value={status} onChange={(event) => filter("status", event.target.value)}>
                <option value="active">사용 중</option>
                <option value="closed">사용 종료</option>
                <option value="all">모든 상태</option>
              </select>
            </label>
          </div>
        </div>
        <div className="form-actions">
          <button disabled={list.loading} onClick={() => void list.reload()}>
            카드 목록 다시 확인
          </button>
          <button className="secondary-button" onClick={reset}>
            카드 필터 초기화
          </button>
        </div>
      </FilterPanel>
      <MemberLoadError error={members.error} retry={members.retry} />
      <CashflowError error={list.error} />
      {list.error && (
        <button type="button" onClick={() => void list.reload()}>
          카드 다시 확인
        </button>
      )}
      {list.loading && (
        <p className="loading-state" role="status">
          카드 목록을 불러오고 있어요.
        </p>
      )}
      {!list.loading && !list.error && !list.items.length && <p>조건에 맞는 카드가 없어요.</p>}
      <ul className="finance-list task-records card-records">
        {list.items.map((card) => (
          <li className="card" key={card.id}>
            <div className="item-heading">
              <h2>
                <Link to={`/cards/${card.id}`}>{card.alias || card.product_name}</Link>
              </h2>
              <span className="status-chip">
                {card.status === "active" ? "사용 중" : "사용 종료"}
              </span>
            </div>
            <p className="record-subline">
              {card.issuer_name} ·{" "}
              {members.members.find((member) => member.member_id === card.owner_member_id)
                ?.display_name ?? "구성원 확인 필요"}
            </p>
            <p className="card-masked-number">{card.masked_number || "마지막 네 자리 미입력"}</p>
            <p className="record-facts">
              <span>
                결제일{" "}
                <strong>{card.settlement_day ? `매월 ${card.settlement_day}일` : "미입력"}</strong>
              </span>
              {card.settlement_account_status === "closed" && (
                <strong className="warning-text">결제계좌 사용 종료 · 변경 필요</strong>
              )}
            </p>
            <details className="record-details">
              <summary>카드 상품·계좌·사용기간</summary>
              <CardSummary card={card} members={members.members} showMask={false} />
            </details>
          </li>
        ))}
      </ul>
      {list.cursor && (
        <button disabled={list.loading} onClick={() => void list.more()}>
          카드 더 보기
        </button>
      )}
    </>
  );
}
function CardDetail({ id, edit }: { id: string; edit: boolean }) {
  const api = useCardsApi();
  const mounted = useMounted();
  const navigate = useNavigate();
  const resource = useResource(
    useCallback(
      () => (isUuid(id) ? api.get(id) : Promise.reject(new ApiError(404, "NOT_FOUND"))),
      [api, id],
    ),
  );
  const members = useHouseholdMembers();
  const flight = useRef(false);
  const [action, setAction] = useState<"close" | "delete" | "">("");
  const [ended, setEnded] = useState(todaySeoul);
  const [deleteAck, setDeleteAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const card = resource.data;
  const endError = ended
    ? cardEndDateError(ended, card?.started_on)
    : "카드 종료일을 입력해 주세요.";
  const closure = useClosureReview("card", id, ended, action === "close" && !endError);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (
      !card ||
      flight.current ||
      resource.loading ||
      (action === "close" &&
        (!closure.ready || !isDateOnly(ended) || !!cardEndDateError(ended, card.started_on))) ||
      (action === "delete" && !deleteAck)
    )
      return;
    flight.current = true;
    setBusy(true);
    setError(null);
    try {
      if (action === "delete") {
        await api.delete(id, card.version);
        if (mounted.current) navigate("/cards", { replace: true });
      } else {
        await api.archive(id, { ended_on: ended, ...closure.proof }, card.version);
        if (mounted.current) {
          setAction("");
          void resource.reload();
        }
      }
    } catch (failure) {
      if (mounted.current) {
        const failureError = toApiError(failure);
        setError(failureError);
        if (
          failureError.code === "PAYMENT_LINKS_CHANGED" ||
          failureError.code === "PAYMENT_LINK_CONFIRMATION_REQUIRED"
        )
          closure.refresh();
      }
    } finally {
      flight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  // A reload keeps the card on screen: only a first read, with nothing to show yet, is a spinner.
  return (
    <div aria-busy={resource.loading}>
      <CashflowError error={resource.error} />
      {resource.error && <button onClick={() => void resource.reload()}>카드 다시 확인</button>}
      {resource.loading && !card && (
        <p className="loading-state" role="status">
          현재 카드 정보를 불러오고 있어요.
        </p>
      )}
      {card &&
        !resource.error &&
        (edit ? (
          <CardEditor initial={card} />
        ) : (
          <>
            <section className="card">
              <h2>{card.alias || card.product_name}</h2>
              <CardSummary card={card} members={members.members} />
              {card.note && <p>메모: {card.note}</p>}
              <MemberLoadError error={members.error} retry={members.retry} />
              <p className="muted">
                결제일은 카드 전체 명세나 실제 출금액을 뜻하지 않아요. 등록한 정기 결제는 고정
                납부에서 확인해요.
              </p>
              <div className="form-actions">
                <Link className="button-link" to={`/cards/${id}/edit`}>
                  카드 정보 수정
                </Link>
                {card.status === "active" && (
                  <button
                    onClick={() => {
                      setAction("close");
                      setError(null);
                    }}
                  >
                    카드 사용 종료
                  </button>
                )}
                <button
                  className="danger-button"
                  onClick={() => {
                    setAction("delete");
                    setDeleteAck(false);
                    setError(null);
                  }}
                >
                  오등록 삭제 검토
                </button>
              </div>
            </section>
            <CardVaultActions cardId={id} onCompleted={() => void resource.reload()} />
            {action && (
              <section className="card">
                <h2>{action === "close" ? "사용 종료 확인" : "오등록 삭제 확인"}</h2>
                <form onSubmit={(event) => void submit(event)}>
                  {action === "close" ? (
                    <>
                      <p>
                        일반정보와 과거 납부 기록은 보존돼요. 보관함 비밀 제거와는 별도 작업이에요.
                      </p>
                      <div className="form-field">
                        <label>
                          카드 종료일
                          <input
                            type="date"
                            min={card.started_on ?? undefined}
                            max={todaySeoul()}
                            aria-invalid={!!endError}
                            aria-describedby={endError ? "card-closure-date-error" : undefined}
                            value={ended}
                            onChange={(event) => setEnded(event.target.value)}
                            disabled={busy}
                            required
                          />
                        </label>
                        {endError && (
                          <p id="card-closure-date-error" role="alert">
                            {endError}
                          </p>
                        )}
                      </div>
                      {!endError && <ClosureReview review={closure} disabled={busy} />}
                    </>
                  ) : (
                    <>
                      <p>
                        참조 없는 오등록만 실제 삭제할 수 있어요. 사용 이력이 있으면 사용 종료를
                        이용해 주세요.
                      </p>
                      <label className="checkbox-field">
                        <input
                          type="checkbox"
                          checked={deleteAck}
                          onChange={(event) => setDeleteAck(event.target.checked)}
                          disabled={busy}
                        />
                        잘못 등록한 카드이며 실제 삭제할 것을 확인했어요.
                      </label>
                    </>
                  )}
                  <CashflowError error={error} />
                  {error?.code === "VERSION_CONFLICT" && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setError(null);
                        setDeleteAck(false);
                        closure.refresh();
                        void resource.reload();
                      }}
                    >
                      현재 카드 다시 확인
                    </button>
                  )}
                  <div className="form-actions">
                    <button
                      type="submit"
                      className={action === "delete" ? "danger-button" : undefined}
                      disabled={
                        busy ||
                        error?.code === "VERSION_CONFLICT" ||
                        (action === "close" ? !!endError || !closure.ready : !deleteAck)
                      }
                    >
                      {busy
                        ? "처리 결과 확인 중…"
                        : action === "close"
                          ? "카드 사용 종료 저장"
                          : "오등록 카드 삭제"}
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={busy}
                      onClick={() => setAction("")}
                    >
                      카드 작업 취소
                    </button>
                  </div>
                </form>
              </section>
            )}
          </>
        ))}
    </div>
  );
}
export function CardListPage() {
  return (
    <AuthenticatedFinance title="카드 관리" description="카드 일반정보와 결제계좌를 함께 관리해요.">
      <CardList />
    </AuthenticatedFinance>
  );
}
export function CardNewPage() {
  return (
    <AuthenticatedFinance title="카드 등록" description="소유자와 카드 식별 정보를 기록해요.">
      <CardEditor />
    </AuthenticatedFinance>
  );
}
export function CardDetailPage({ edit = false }: { edit?: boolean }) {
  const { id = "" } = useParams();
  return (
    <AuthenticatedFinance
      title={edit ? "카드 정보 수정" : "카드 상세"}
      description="일반정보와 연결된 납부 계획을 확인해요."
    >
      <CardDetail key={`${id}:${edit}`} id={id} edit={edit} />
    </AuthenticatedFinance>
  );
}
