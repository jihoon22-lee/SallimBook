import { useCallback } from "react";
import { Link } from "react-router";
import type { components } from "@sallimbook/api-client";
import { isNativeAuth } from "../../platform/nativeAuth";
import { AuthError, SessionStatus } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import { useCardsApi } from "../cards/api";
import { MemberLoadError, useHouseholdMembers } from "../finance/FinanceSupport";
import { usePagedList, useResource } from "../finance/queries";
import { VaultActionLauncher } from "./CardVaultActions";
import type { WebVaultRequest } from "./actions";
import { useVaultOverviewApi } from "./overviewApi";

const membershipLabels = { active: "접근 가능", not_enrolled: "공유 전", revoked: "접근 철회" };
const shareLabels = {
  pending: "수락 대기",
  accepted: "수락 완료",
  cancelled: "취소됨",
  expired: "만료됨",
};
type Status = components["schemas"]["VaultStatusResponse"];
function RotationProgress({
  id,
  open,
  busy,
}: {
  id: string;
  open: (request: WebVaultRequest) => void;
  busy: boolean;
}) {
  const api = useVaultOverviewApi();
  const rotation = useResource(useCallback(() => api.rotation(id), [api, id]));
  const row = rotation.data;
  return (
    <section className="card">
      <h2>진행 중인 키 회전</h2>
      <p>
        모든 카드와 구성원 키가 준비되어야 새 키로 전환돼요. 중단된 작업은 현재 상태를 확인한 뒤
        이어서 진행해 주세요.
      </p>
      <AuthError error={rotation.error} />
      {rotation.loading && <p role="status">키 회전 상태 확인 중…</p>}
      {row && !rotation.error && !rotation.loading && (
        <>
          <dl className="metadata-grid">
            <div>
              <dt>카드 준비</dt>
              <dd>
                {row.cards.filter((card) => card.prepared).length} / {row.cards.length}
              </dd>
            </div>
            <div>
              <dt>구성원 준비</dt>
              <dd>
                {row.members.filter((member) => member.prepared).length} / {row.members.length}
              </dd>
            </div>
            <div>
              <dt>키 확인</dt>
              <dd>{row.key_check_prepared ? "준비됨" : "준비 필요"}</dd>
            </div>
            <div>
              <dt>복구 수단</dt>
              <dd>{row.recovery_prepared ? "준비됨" : "준비 필요"}</dd>
            </div>
          </dl>
          {row.state === "staging" ? (
            <div className="form-actions">
              <button
                disabled={busy}
                onClick={() => open({ action: "resume-rotation", rotationId: id })}
              >
                키 회전 계속하기
              </button>
              <button
                className="secondary-button"
                disabled={busy}
                onClick={() => open({ action: "abort-rotation", rotationId: id })}
              >
                키 회전 중단 검토
              </button>
            </div>
          ) : (
            <p>이 키 회전은 종료됐어요. 보관함 상태를 다시 확인해 주세요.</p>
          )}
        </>
      )}
      <button
        className="secondary-button"
        disabled={busy || rotation.loading}
        onClick={() => void rotation.reload()}
      >
        키 회전 상태 다시 확인
      </button>
    </section>
  );
}
function VaultOverview({ memberId }: { memberId: string }) {
  const api = useVaultOverviewApi();
  const cardsApi = useCardsApi();
  const members = useHouseholdMembers();
  const status = useResource(useCallback(() => api.status(), [api]));
  const shares = usePagedList(useCallback((cursor?: string) => api.shares(cursor), [api]));
  const cards = usePagedList(
    useCallback(
      (cursor?: string) =>
        cardsApi.list({ status: "all", limit: 50, ...(cursor ? { cursor } : {}) }),
      [cardsApi],
    ),
  );
  const native = isNativeAuth();
  const row = status.data;
  const memberName = (id: string) =>
    members.members.find((member) => member.member_id === id)?.display_name ?? "구성원 확인 필요";
  const reload = () => {
    void status.reload();
    void shares.reload();
    void cards.reload();
  };
  const active = row?.own_membership === "active";
  const ready = active && !row?.pending_rotation_id && !row?.rotation_required;
  return (
    <VaultActionLauncher onCompleted={reload}>
      {(open, busy) => (
        <>
          <section className="card">
            <h2>보관함 상태</h2>
            <AuthError error={status.error} />
            {status.loading && <p role="status">보관함 상태를 확인하고 있어요.</p>}
            {row && !status.loading && !status.error && (
              <>
                <p className="status-chip">
                  {row.initialized ? membershipLabels[row.own_membership] : "아직 설정하지 않음"}
                </p>
                {row.initialized ? (
                  <>
                    <p>
                      현재 키 버전 {row.current_key_version} · 내 보관함 권한:{" "}
                      {membershipLabels[row.own_membership]}
                    </p>
                    {row.rotation_required && (
                      <p role="alert">
                        접근 철회 후 키 회전이 필요해요. 새 키로 전환하기 전에는 카드 비밀
                        등록·수정과 새 공유를 할 수 없어요.
                      </p>
                    )}
                    {row.own_membership === "revoked" && (
                      <p>
                        보관함 접근이 철회됐어요. 현재 접근 권한이 있는 구성원에게 새 공유를 요청해
                        주세요.
                      </p>
                    )}
                    {row.own_membership === "not_enrolled" && (
                      <p>
                        가계에 가입해도 카드 비밀은 자동 공유되지 않아요. 다른 구성원의 공유를 받아
                        수락해 주세요.
                      </p>
                    )}
                    <div className="form-actions">
                      {active && (
                        <>
                          <button
                            disabled={busy || !!row.pending_rotation_id}
                            onClick={() => open({ action: "change-password" })}
                          >
                            보관함 암호 변경
                          </button>
                          {native && (
                            <button
                              disabled={busy || !!row.pending_rotation_id}
                              onClick={() => open({ action: "register-device" })}
                            >
                              이 Android 기기 등록·재등록
                            </button>
                          )}
                          <button
                            disabled={busy || !!row.pending_rotation_id}
                            onClick={() => open({ action: "rotate" })}
                          >
                            보관함 키 회전 시작
                          </button>
                        </>
                      )}
                      {active && (
                        <button
                          disabled={busy || !!row.pending_rotation_id}
                          onClick={() => open({ action: "recover" })}
                        >
                          복구코드로 보관함 복구
                        </button>
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    <p>별도의 보관함 암호와 복구 수단을 설정해 카드번호와 유효기간을 보호해요.</p>
                    <button disabled={busy} onClick={() => open({ action: "setup" })}>
                      보관함 처음 설정
                    </button>
                  </>
                )}
              </>
            )}
            <button className="secondary-button" disabled={busy || status.loading} onClick={reload}>
              보관함 상태 다시 확인
            </button>
            <p className="muted">
              보관함 암호는 로그인 암호와 달라요. 계정 로그인이나 지문 인증만으로 PC 웹 보관함
              암호를 대신할 수 없어요.
            </p>
          </section>
          {row && !status.loading && !status.error && (
            <>
              {active && row.pending_rotation_id && (
                <RotationProgress
                  key={`${row.pending_rotation_id}:${row.version}`}
                  id={row.pending_rotation_id}
                  open={open}
                  busy={busy}
                />
              )}
              <section className="card">
                <h2>부부 공유</h2>
                <p>
                  가계 초대와 카드 비밀 공유는 별개예요. 공유할 때는 신뢰하는 기기에서 상대 구성원과
                  대상을 함께 확인해 주세요.
                </p>
                <MemberLoadError error={members.error} retry={members.retry} />
                <ul className="finance-list">
                  {row.members.map((member: Status["members"][number]) => (
                    <li key={member.member_id}>
                      <p>
                        {memberName(member.member_id)}
                        {member.member_id === memberId ? " (나)" : ""} ·{" "}
                        {membershipLabels[member.status]}
                      </p>
                      {active && member.member_id !== memberId && (
                        <div className="form-actions">
                          {member.status !== "active" ? (
                            <button
                              disabled={busy || !ready || members.loading || !!members.error}
                              onClick={() => open({ action: "share", memberId: member.member_id })}
                            >
                              이 구성원에게 공유
                            </button>
                          ) : (
                            <button
                              disabled={
                                busy ||
                                !!row.pending_rotation_id ||
                                members.loading ||
                                !!members.error
                              }
                              onClick={() =>
                                open({ action: "revoke-member", memberId: member.member_id })
                              }
                            >
                              이 구성원 접근 철회 검토
                            </button>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
                <p className="muted">
                  접근을 철회해도 이미 본 번호나 오프라인 사본을 회수할 수는 없어요. 철회 후에는 새
                  키로 회전해야 해요.
                </p>
                <AuthError error={shares.error} />
                {shares.loading && <p role="status">공유 요청 확인 중…</p>}
                {!shares.error && (
                  <ul className="finance-list">
                    {shares.items.map((offer) => {
                      const expired = new Date(offer.expires_at).getTime() <= Date.now();
                      const pending = offer.state === "pending" && !expired;
                      return (
                        <li key={offer.id}>
                          <p>
                            {memberName(offer.source_member_id)} →{" "}
                            {memberName(offer.target_member_id)} ·{" "}
                            {offer.state === "pending" && expired
                              ? "만료됨"
                              : shareLabels[offer.state]}
                          </p>
                          <p>
                            만료 시각:{" "}
                            {new Date(offer.expires_at).toLocaleString("ko-KR", {
                              timeZone: "Asia/Seoul",
                            })}{" "}
                            (서울)
                          </p>
                          {pending && (
                            <div className="form-actions">
                              {offer.target_member_id === memberId && (
                                <button
                                  disabled={
                                    busy || !!row.pending_rotation_id || row.rotation_required
                                  }
                                  onClick={() =>
                                    open({ action: "accept-share", offerId: offer.id })
                                  }
                                >
                                  공유 수락
                                </button>
                              )}
                              {(offer.source_member_id === memberId ||
                                offer.target_member_id === memberId) && (
                                <button
                                  disabled={busy || !!row.pending_rotation_id}
                                  onClick={() =>
                                    open({ action: "cancel-share", offerId: offer.id })
                                  }
                                >
                                  {offer.source_member_id === memberId
                                    ? "공유 요청 취소"
                                    : "공유 요청 거절"}
                                </button>
                              )}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
                {!shares.loading && !shares.error && !shares.items.length && (
                  <p>공유 요청이 없어요.</p>
                )}
                <div className="form-actions">
                  <button disabled={busy || shares.loading} onClick={() => void shares.reload()}>
                    공유 요청 다시 확인
                  </button>
                  {shares.cursor && (
                    <button disabled={busy || shares.loading} onClick={() => void shares.more()}>
                      공유 요청 더 보기
                    </button>
                  )}
                </div>
              </section>
              <section className="card">
                <h2>카드 비밀</h2>
                <p>목록에는 마지막 네 자리만 표시해요. 유효기간 **/** · CVC/CVV ***</p>
                <AuthError error={cards.error} />
                {cards.loading && <p role="status">카드 목록 확인 중…</p>}
                {!cards.error && (
                  <ul className="finance-list">
                    {cards.items.map((card) => (
                      <li key={card.id}>
                        <h3>
                          <Link to={`/cards/${card.id}`}>{card.alias || card.product_name}</Link>
                        </h3>
                        <p>
                          {card.masked_number || "마지막 네 자리 미입력"} ·{" "}
                          {card.status === "closed" ? "사용 종료" : "사용 중"}
                        </p>
                        <div className="form-actions">
                          <button
                            disabled={busy || !active}
                            onClick={() => open({ action: "view", cardId: card.id })}
                          >
                            전체 번호·유효기간 열람
                          </button>
                          <button
                            disabled={busy || !ready}
                            onClick={() => open({ action: "edit", cardId: card.id })}
                          >
                            카드 비밀 등록·수정
                          </button>
                          <button
                            className="secondary-button"
                            disabled={busy || !active || !!row.pending_rotation_id}
                            onClick={() => open({ action: "purge", cardId: card.id })}
                          >
                            카드 비밀 제거
                          </button>
                          {native && (
                            <button
                              className="secondary-button"
                              disabled={busy || !active}
                              onClick={() => open({ action: "cvc-delete", cardId: card.id })}
                            >
                              이 기기의 CVC/CVV 삭제 검토
                            </button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                {!cards.loading && !cards.error && !cards.items.length && (
                  <p>등록된 카드가 없어요. 카드 일반정보를 먼저 등록해 주세요.</p>
                )}
                <div className="form-actions">
                  <Link to="/cards/new">카드 일반정보 등록</Link>
                  <button disabled={busy || cards.loading} onClick={() => void cards.reload()}>
                    카드 목록 다시 확인
                  </button>
                  {cards.cursor && (
                    <button disabled={busy || cards.loading} onClick={() => void cards.more()}>
                      카드 더 보기
                    </button>
                  )}
                </div>
              </section>
            </>
          )}
          <section className="card">
            <h2>기기와 복구 안내</h2>
            <p>
              {native
                ? "이 Android 기기에서 비밀 입력·열람은 네이티브 보호 화면으로 열려요. 새 기기에서는 보관함을 등록하고 CVC/CVV를 다시 입력해야 해요. CVC/CVV 입력·열람은 보안 검증 전이라 현재 비활성 상태예요. 이 기기에 남은 CVC/CVV 삭제는 보호된 화면에서 할 수 있어요."
                : "PC 웹은 카드번호와 유효기간을 별도 보관함 화면에서 다뤄요. CVC/CVV 입력·열람·저장은 지원하지 않아요. 웹에서는 화면 캡처를 막을 수 없어요."}
            </p>
            <p>
              보관함 암호·복구코드·잠금 해제 가능한 신뢰 기기를 모두 잃으면 기존 카드 비밀을 복원할
              수 없어요. 복구코드는 오프라인의 안전한 곳에 보관해 주세요.
            </p>
            <Link to="/settings/auth">계정과 등록 기기 관리</Link>
          </section>
        </>
      )}
    </VaultActionLauncher>
  );
}
export function VaultPage() {
  const { state } = useAuth();
  return (
    <>
      <div className="intro">
        <p className="eyebrow">보호된 카드 정보</p>
        <h1>보관함</h1>
        <p>부부 공유와 복구, 카드 비밀을 관리해요.</p>
      </div>
      {state.status === "authenticated" ? (
        <VaultOverview key={state.member.member_id} memberId={state.member.member_id} />
      ) : (
        <SessionStatus />
      )}
    </>
  );
}
