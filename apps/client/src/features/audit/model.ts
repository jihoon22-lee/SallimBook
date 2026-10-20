import type { components, operations } from "@sallimbook/api-client";
import { isDateOnly, isUuid } from "../finance/dates";

export type AuditEvent = components["schemas"]["AuditEventResponse"];
export type AuditQuery = NonNullable<operations["listAuditEvents"]["parameters"]["query"]>;
export type AuditFilterDraft = {
  entityType: string;
  entityId: string;
  actor: string;
  action: string;
  since: string;
  through: string;
};
export const emptyFilters: AuditFilterDraft = {
  entityType: "",
  entityId: "",
  actor: "",
  action: "",
  since: "",
  through: "",
};

// Display labels, not a second API schema. The server validates accepted filter values.
export const entityLabels: Record<string, string> = {
  asset: "자산·부채",
  financial_account: "계좌",
  asset_month: "월별 자산",
  cash_record: "금전 기록",
  income_conversion: "수입 입력 방식",
  recurring_rule: "고정 납부 규칙",
  obligation: "납부 회차",
  fixed_settlement: "실제 납부",
  card: "카드 일반정보",
  insurance_policy: "보험 계약",
  insurance_coverage: "보험 보장",
  policy_premium_link: "보험료 연결",
  insurance_case: "보험 사건",
  medical_node: "진료·약국",
  medical_expense: "의료비",
  medical_refund: "의료비 환불",
  insurance_claim: "보험 청구",
  insurance_payout: "보험금 수령",
  payout_allocation: "보험금 배분",
  insurance_return: "보험금 반환",
  appliance: "가전",
  consumable: "소모품",
  appliance_consumable: "기기별 소모품",
  stock_movement: "재고 이동",
  consumable_replacement: "소모품 교체",
  vault: "보관함",
  vault_membership: "보관함 구성원",
  vault_member_wrapping: "구성원 키 보호",
  vault_recovery_wrapping: "복구 키 보호",
  vault_share: "보관함 공유",
  vault_rotation: "보관함 키 교체",
  card_secret_envelope: "카드 비밀 보관",
  document: "문서",
  document_link: "문서 연결",
  user_export: "자료 내보내기",
  registered_device: "기기 로그인",
  passkey: "패스키",
  invitation: "초대·연결 코드",
  user: "계정",
};
export const actionLabels: Record<string, string> = {
  create: "등록",
  update: "수정",
  archive: "사용 종료",
  delete: "삭제",
  reveal: "열람 요청",
  correct: "정정",
  void: "취소",
  convert: "방식 전환",
  confirm: "확정",
  reopen: "재개방",
  sync_scope: "대상 범위 확인",
  regenerate: "다시 생성",
  reschedule: "일정 변경",
  skip: "건너뛰기",
  unskip: "건너뛰기 해제",
  complete: "완료 처리",
  settle: "납부 처리",
  void_settlement: "납부 취소",
  export: "서버 파일 발급",
  login: "로그인",
  revoke: "폐기",
  accept: "수락",
};
export function queryFromFilters(
  draft: AuditFilterDraft,
): { query: AuditQuery; error?: never } | { error: string; query?: never } {
  const entityId = draft.entityId.trim();
  if (entityId && !isUuid(entityId)) return { error: "대상 ID는 UUID 형식으로 입력해 주세요." };
  if ((draft.since && !isDateOnly(draft.since)) || (draft.through && !isDateOnly(draft.through)))
    return { error: "조회 날짜를 확인해 주세요." };
  if (draft.since && draft.through && draft.since > draft.through)
    return { error: "마지막 날짜는 시작 날짜와 같거나 이후여야 해요." };
  // API interval is [since, until); the selected final Seoul calendar day is included.
  const since = draft.since ? new Date(`${draft.since}T00:00:00+09:00`).toISOString() : undefined;
  const until = draft.through
    ? new Date(Date.parse(`${draft.through}T00:00:00+09:00`) + 86_400_000).toISOString()
    : undefined;
  return {
    query: {
      limit: 50,
      ...(draft.entityType ? { entity_type: draft.entityType } : {}),
      ...(entityId ? { entity_id: entityId.toLowerCase() } : {}),
      ...(draft.actor ? { actor_member_id: draft.actor } : {}),
      ...(draft.action ? { action: draft.action } : {}),
      ...(since ? { since } : {}),
      ...(until ? { until } : {}),
    },
  };
}
