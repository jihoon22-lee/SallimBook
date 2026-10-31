"""Curated, escaped offline reading views over the same safe export snapshot."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, select

from sallimbook.core.database import Base
from sallimbook.exports.annual import annual_summary
from sallimbook.exports.catalog import PUBLIC_COLUMNS
from sallimbook.identity.auth_models import HouseholdMember, User

DOMAINS = {
    "assets": "자산",
    "accounts": "계좌",
    "cards": "카드",
    "income": "수입",
    "fixed": "고정 납부",
    "insurance": "보험·의료",
    "homecare": "가전·소모품",
}


@dataclass(frozen=True)
class Section:
    domain: str
    table: str
    title: str
    fields: str
    date_field: str | None = None


# Each field is explicitly classified in PUBLIC_COLUMNS; cash_* is a scoped cash join.
SECTIONS = (
    Section(
        "income",
        "expected_incomes",
        "현재 예상 월 수입 (입금 기록 아님)",
        "member_id label amount_krw active note",
    ),
    Section(
        "income",
        "bonus_awards",
        "성과연도 상여 (주식은 수령 당시 평가액)",
        "member_id performance_year award_kind payment_month gross_krw net_cash_krw "
        "stock_grant_value_krw payout_rate_percent received active cash_record_id note",
    ),
    Section(
        "assets",
        "assets",
        "자산 기본정보",
        "name kind category owner_member_id household_share amount_basis "
        "inclusion_status started_on ended_on note",
    ),
    Section(
        "assets",
        "asset_values",
        "월별 자산값 (현재 리비전)",
        "name revision_id kind input_amount_krw owned_amount_krw "
        "household_share amount_basis inclusion_status verification_state origin as_of_date",
        "_month",
    ),
    Section(
        "accounts",
        "financial_accounts",
        "계좌 기본정보",
        "asset_id institution_name account_type last_four purpose opened_on",
    ),
    Section(
        "cards",
        "cards",
        "카드 기본정보",
        "alias product_name issuer_name owner_member_id card_type annual_fee_krw "
        "is_family_card last_four "
        "settlement_day settlement_account_id started_on ended_on note",
    ),
    Section(
        "income",
        "cash_records",
        "수입·보험금 수령·반환",
        "kind member_id amount_krw occurred_on period_month date_precision "
        "account_id state note created_by_member_id created_at",
        "_cash",
    ),
    Section(
        "fixed",
        "recurring_rule_versions",
        "납부 규칙의 저장된 적용기간",
        "title category effective_from effective_until economic_type "
        "expected_amount_krw frequency interval_count account_id card_id "
        "revoked_at",
    ),
    Section(
        "fixed",
        "scheduled_obligations",
        "예정 회차",
        "title category scheduled_date economic_type expected_amount_krw "
        "account_id card_id schedule_state skipped manually_completed",
        "scheduled_date",
    ),
    Section(
        "fixed",
        "fixed_settlements",
        "실제 고정 납부",
        "obligation_id cash_amount_krw cash_occurred_on cash_period_month "
        "cash_date_precision cash_state economic_type principal_krw "
        "consumption_krw asset_transfer_krw",
        "_cash",
    ),
    Section(
        "insurance",
        "insurance_policies",
        "보험 계약",
        "product_name insurer policyholder_member_id insured_member_id status "
        "last_four contract_start contract_end note",
    ),
    Section(
        "insurance",
        "insurance_coverages",
        "보장",
        "policy_id name benefit_type insured_amount_krw coverage_start coverage_end active note",
    ),
    Section(
        "insurance", "policy_premium_links", "보험료 규칙 연결", "policy_id rule_id active ended_at"
    ),
    Section(
        "insurance",
        "insurance_cases",
        "의료 사건",
        "title patient_member_id start_on end_on treatment_state financial_state diagnosis_note",
    ),
    Section(
        "insurance",
        "medical_nodes",
        "진료·약국 관계",
        "case_id parent_id kind label provider_name start_on end_on note",
    ),
    Section(
        "insurance",
        "medical_expenses",
        "의료비 지불",
        "case_id node_id provider_name cash_amount_krw cash_occurred_on "
        "cash_state gross_medical_krw public_coverage_krw created_by_member_id "
        "created_at",
        "_cash",
    ),
    Section(
        "insurance",
        "medical_refunds",
        "의료비 환불",
        "expense_id cash_amount_krw cash_occurred_on cash_state reason "
        "created_by_member_id created_at",
        "_cash",
    ),
    Section(
        "insurance",
        "insurance_claims",
        "청구 (실제 수령과 별개)",
        "case_id policy_id claim_reference submitted_on requested_krw "
        "decided_krw claim_state decision_note",
        "submitted_on",
    ),
    Section(
        "insurance", "claim_expenses", "청구에 연결된 비용 (합산하지 않음)", "claim_id expense_id"
    ),
    Section(
        "insurance",
        "insurance_payouts",
        "실제 보험금 수령",
        "cash_amount_krw cash_occurred_on cash_state insurer_note created_by_member_id created_at",
        "_cash",
    ),
    Section(
        "insurance",
        "payout_allocations",
        "수령 보험금의 사건 배분 (수령과 중복 합산하지 않음)",
        "payout_id case_id policy_id claim_id benefit_type amount_krw",
        "_payout",
    ),
    Section(
        "insurance",
        "insurance_returns",
        "보험금 반환",
        "payout_id original_allocation_id cash_amount_krw cash_occurred_on "
        "cash_state reason created_by_member_id created_at",
        "_cash",
    ),
    Section(
        "homecare",
        "appliances",
        "가전 기본정보",
        "name manufacturer model location purchased_on purchase_price_krw "
        "warranty_until ended_on note",
    ),
    Section(
        "homecare",
        "consumables",
        "소모품과 현재 재고",
        "name sku_or_model unit stock_quantity low_stock_threshold ended_on note",
    ),
    Section(
        "homecare",
        "appliance_consumables",
        "가전·소모품 연결",
        "appliance_id consumable_id interval_unit interval_count "
        "quantity_per_replacement next_check_override active note",
    ),
    Section(
        "homecare",
        "stock_movements",
        "재고 이력 (취소 반대 기록 포함)",
        "consumable_id kind quantity_delta occurred_on unit_cost_krw "
        "purchase_url reversal_of movement_reversed reason note created_by_member_id created_at",
        "occurred_on",
    ),
    Section(
        "homecare",
        "consumable_replacements",
        "교체 이력",
        "appliance_consumable_id consumable_id replaced_on quantity "
        "stock_movement_id movement_reversed note created_by_member_id",
        "replaced_on",
    ),
    Section(
        "homecare",
        "consumable_orders",
        "구매계획·주문·입고 현황",
        "consumable_id state quantity unit_cost_krw purchase_url ordered_on "
        "ordered_by_member_id received_on received_by_member_id "
        "stock_movement_id movement_reversed cancel_reason created_by_member_id created_at",
    ),
)

LABELS = dict(
    item.split(":", 1)
    for item in """
name:이름 kind:종류 category:분류 owner_member_id:소유자
household_share:가계지분 amount_basis:금액입력기준 inclusion_status:합계포함
started_on:시작일 ended_on:종료일 note:메모 revision_id:자산월과상태
input_amount_krw:입력금액 owned_amount_krw:가계보유금액
verification_state:확인상태 origin:출처 as_of_date:기준일 asset_id:자산
institution_name:금융기관 account_type:계좌종류 last_four:끝네자리 purpose:용도
opened_on:개설일 alias:별칭 product_name:상품명 issuer_name:카드사
card_type:카드종류 annual_fee_krw:연회비 is_family_card:가족카드여부
settlement_day:결제일 settlement_account_id:결제계좌
member_id:소득귀속 amount_krw:금액 occurred_on:실제일자 period_month:기록월
date_precision:날짜정밀도 account_id:계좌 state:상태
created_by_member_id:작성자 created_at:작성시각 title:이름
effective_from:적용시작일 effective_until:적용종료일 economic_type:경제적성격
expected_amount_krw:예정금액 frequency:주기 interval_count:주기간격
card_id:카드 revoked_at:철회시각 scheduled_date:예정일 schedule_state:회차상태
skipped:건너뜀 manually_completed:수동완료 obligation_id:납부회차
principal_krw:원금상환 consumption_krw:소비성비용 asset_transfer_krw:자산이동
insurer:보험사 policyholder_member_id:계약자 insured_member_id:피보험자
status:상태 contract_start:계약시작 contract_end:계약종료 policy_id:보험계약
benefit_type:급부종류 insured_amount_krw:보장금액 coverage_start:보장시작
coverage_end:보장종료 active:현재연결 rule_id:납부규칙 ended_at:연결종료시각
patient_member_id:환자 start_on:시작일 end_on:종료일 treatment_state:진료상태
financial_state:정산상태 diagnosis_note:진단메모 case_id:의료사건
parent_id:상위진료 kind:종류 label:이름 provider_name:의료기관 node_id:진료
gross_medical_krw:총진료비 public_coverage_krw:공적보장금액 expense_id:원지불
reason:사유 claim_reference:청구참조 submitted_on:청구일
requested_krw:청구금액 decided_krw:결정금액 claim_state:청구상태
decision_note:결정메모 claim_id:청구 payout_id:원수령 insurer_note:수령메모
original_allocation_id:원배분 manufacturer:제조사 model:모델 location:위치
purchased_on:구매일 purchase_price_krw:구매가격 warranty_until:보증기한
sku_or_model:품목코드 unit:단위 stock_quantity:현재재고
low_stock_threshold:부족기준 appliance_id:가전 consumable_id:소모품
interval_unit:주기단위 quantity_per_replacement:교체수량
next_check_override:다음확인일 quantity_delta:재고증감 unit_cost_krw:개당가격
purchase_url:구매주소 reversal_of:취소대상 appliance_consumable_id:교체연결
replaced_on:교체일 quantity:수량 stock_movement_id:재고기록 ordered_on:주문일
ordered_by_member_id:주문자 received_on:입고일
received_by_member_id:입고자 cancel_reason:취소사유
""".split()
)

LABELS.update(
    {
        "label": "수입항목",
        "active": "유효여부",
        "performance_year": "성과연도",
        "award_kind": "상여구분",
        "payment_month": "지급월",
        "gross_krw": "세전금액",
        "net_cash_krw": "세후현금",
        "stock_grant_value_krw": "수령당시주식평가액",
        "payout_rate_percent": "지급률",
        "received": "수령확인",
        "cash_record_id": "연결현금기록",
    }
)
LABELS["movement_reversed"] = "원입고·교체취소여부"

ENUMS = dict(
    item.split(":", 1)
    for item in """
active:유효 void:무효 planned:구매예정 ordered:주문완료 received:입고완료
cancelled:취소 in:수입 out:지출 salary:급여 bonus:상여 other_income:기타수입
income_return:수입반환 insurance_receipt:보험금수령 insurance_return:보험금반환
medical_payment:의료비지불 medical_refund:의료비환불 fixed_payment:고정납부
expense:소비비용 loan:대출원리금 asset_transfer:자산이동 month:월단위 day:일단위
monthly:매월 annual:매년 days:일간격 receipt:입고 replacement:교체
adjustment:재고조정 reversal:취소반대기록 asset:자산 liability:부채
whole_asset:전체평가액 owned_share:내지분금액 included:포함 excluded:제외
reimbursement:실손 fixed:정액 other:기타 draft:작성중 confirmed:확정
superseded:이전리비전 verified:확인함 unverified:미확인 not_entered:미입력
carried:이월 manual:직접입력 submitted:청구접수 documents_required:서류보완
reviewing:심사중 decided:결정 closed:종료 withdrawn:철회 bank:은행
brokerage:증권 pension_savings:연금저축 irp:IRP dc_pension:DC isa:ISA
credit:신용 debit:체크 planned:구매예정 open:진행중 completed:완료 pending:대기
treatment:진료 pharmacy:약국 visit:방문
""".split()
)
ENUMS.update(
    {
        "whole": "전체 평가액",
        "owned": "가계 지분 금액",
        "missing": "미입력",
        "carried_unconfirmed": "전월값 미확인",
        "reopened": "재개방",
        "months": "개월",
        "ended": "종료",
        "lapsed": "실효",
        "ongoing": "진료 중",
        "settled": "정산 완료",
        "outpatient": "외래",
        "inpatient": "입원",
        "surgery": "수술",
        "prescription": "처방",
        "follow_up": "추적 진료",
        "group": "묶음",
        "return_in": "반납 입고",
        "return_out": "반품 출고",
    }
)
ENUM_FIELDS = {
    "kind",
    "state",
    "status",
    "account_type",
    "card_type",
    "amount_basis",
    "inclusion_status",
    "verification_state",
    "origin",
    "date_precision",
    "economic_type",
    "frequency",
    "interval_unit",
    "benefit_type",
    "claim_state",
    "treatment_state",
    "financial_state",
    "schedule_state",
}

REFS = {
    "owner_member_id": "members",
    "member_id": "members",
    "created_by_member_id": "members",
    "ordered_by_member_id": "members",
    "received_by_member_id": "members",
    "patient_member_id": "people",
    "insured_member_id": "people",
    "policyholder_member_id": "people",
    "asset_id": "assets",
    "account_id": "financial_accounts",
    "settlement_account_id": "financial_accounts",
    "card_id": "cards",
    "revision_id": "asset_month_revisions",
    "obligation_id": "scheduled_obligations",
    "policy_id": "insurance_policies",
    "rule_id": "recurring_rules",
    "case_id": "insurance_cases",
    "parent_id": "medical_nodes",
    "node_id": "medical_nodes",
    "expense_id": "medical_expenses",
    "claim_id": "insurance_claims",
    "payout_id": "insurance_payouts",
    "original_allocation_id": "payout_allocations",
    "appliance_id": "appliances",
    "consumable_id": "consumables",
    "reversal_of": "stock_movements",
    "appliance_consumable_id": "appliance_consumables",
    "stock_movement_id": "stock_movements",
}
NAME_FIELDS = {
    "assets": "name",
    "financial_accounts": "institution_name asset_id last_four",
    "cards": "alias product_name last_four",
    "insurance_policies": "product_name insurer",
    "insurance_cases": "title patient_member_id",
    "medical_nodes": "label provider_name",
    "scheduled_obligations": "title scheduled_date",
    "medical_expenses": "case_id provider_name cash_record_id",
    "insurance_claims": "case_id policy_id submitted_on claim_reference",
    "insurance_payouts": "cash_record_id",
    "payout_allocations": "case_id benefit_type amount_krw",
    "appliances": "name model",
    "consumables": "name sku_or_model",
    "stock_movements": "consumable_id kind occurred_on quantity_delta",
    "appliance_consumables": "appliance_id consumable_id",
    "cash_records": "occurred_on period_month amount_krw state",
    "asset_months": "period_month",
    "asset_month_revisions": "month_id revision_no state",
}
REFS.update({"cash_record_id": "cash_records", "month_id": "asset_months"})


def display(value, field=""):
    if value is None:
        return "미입력"
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Timestamp must have timezone")
        return value.astimezone(ZoneInfo("Asia/Seoul")).isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return (
            f"{value.year:04d}-{value.month:02d}" if field == "period_month" else value.isoformat()
        )
    if field.endswith("_krw"):
        return f"{int(value):,}원"
    if field == "household_share":
        return f"{Decimal(value) * 100:f}%"
    if field in ENUM_FIELDS:
        return ENUMS.get(str(value), str(value))
    return str(value)


class Names:
    def __init__(self, session, household_id, budget):
        self.session, self.household_id, self.budget = session, household_id, budget
        self.cache = {}

    def resolve(self, table, identifier):
        if identifier is None:
            return "미입력"
        if table not in self.cache:
            self.load(table)
        row = self.cache[table].get(identifier)
        if row is None:
            return "연결 대상 없음"
        if table in {"members", "people", "recurring_rules"}:
            return row
        return (
            " · ".join(
                self.resolve(REFS[key], value) if key in REFS else display(value, key)
                for key, value in row.items()
                if value is not None
            )
            or "이름 미입력"
        )

    def load(self, name):
        tables = Base.metadata.tables
        if name == "members":
            query = (
                select(HouseholdMember.id, User.display_name)
                .join(User, User.id == HouseholdMember.user_id)
                .where(HouseholdMember.household_id == self.household_id)
            )
            items = ((identifier, label) for identifier, label in self.session.execute(query))
        elif name == "people":
            t = tables["household_people"]
            query = select(
                t.c.id, t.c.display_name, t.c.member_id, t.c.relation, t.c.archived_at
            ).where(t.c.household_id == self.household_id)
            relations = {
                "member": "로그인 구성원",
                "child": "자녀",
                "parent": "부모",
                "other": "기타 가족",
            }
            items = (
                (
                    identifier,
                    f"{self.resolve('members', member) if member else label} "
                    f"({relations[relation]}{' · 종료' if archived else ''})",
                )
                for identifier, label, member, relation, archived in self.session.execute(query)
            )
        elif name == "recurring_rules":
            t = tables["recurring_rule_versions"]
            query = (
                select(t.c.rule_id, t.c.title)
                .where(t.c.household_id == self.household_id, t.c.revoked_at.is_(None))
                .order_by(t.c.effective_from, t.c.id)
            )
            items = self.session.execute(query)
        else:
            t = tables[name]
            columns = NAME_FIELDS[name].split()
            assert set(columns) <= set(PUBLIC_COLUMNS[name])
            query = select(t.c.id, *(t.c[key] for key in columns)).where(
                t.c.household_id == self.household_id
            )
            items = (
                (row["id"], {key: row[key] for key in columns})
                for row in self.session.execute(query.execution_options(yield_per=500)).mappings()
            )
        self.cache[name] = {}
        for identifier, value in items:
            self.budget.add("rows", 1)
            # Name caches share the metadata ceiling; never build an unbounded side index.
            self.budget.add(
                "metadata_bytes", len(str(identifier).encode()) + len(str(value).encode())
            )
            self.cache[name][identifier] = value


def cash_field(field):
    """Only joined value aliases use cash_; cash_record_id is a real FK."""
    return field.startswith("cash_") and field != "cash_record_id"


def base_field(field):
    return field.removeprefix("cash_") if cash_field(field) else field


def query_for(section, household_id, scope):
    tables = Base.metadata.tables
    t = tables[section.table]
    fields = section.fields.split()
    source = t
    columns = []
    cash = None
    if any(cash_field(field) for field in fields) or section.date_field in {
        "_cash",
        "_payout",
    }:
        cash = tables["cash_records"]
        if section.table == "cash_records":
            cash = t
        else:
            parent = t
            if section.date_field == "_payout":
                parent = tables["insurance_payouts"]
                source = source.join(
                    parent,
                    and_(t.c.household_id == parent.c.household_id, t.c.payout_id == parent.c.id),
                )
            source = source.join(
                cash,
                and_(
                    parent.c.household_id == cash.c.household_id,
                    parent.c.cash_record_id == cash.c.id,
                ),
            )
    for field in fields:
        if field == "movement_reversed":
            movement = tables["stock_movements"].alias("reversing_movement")
            target = t.c.id if section.table == "stock_movements" else t.c.stock_movement_id
            columns.append(
                exists(
                    select(movement.c.id).where(
                        movement.c.household_id == household_id,
                        movement.c.reversal_of == target,
                    )
                ).label(field)
            )
        elif cash_field(field):
            column = field.removeprefix("cash_")
            assert column in PUBLIC_COLUMNS["cash_records"]
            columns.append(cash.c[column].label(field))
        else:
            assert field in PUBLIC_COLUMNS[section.table]
            columns.append(t.c[field])
    conditions = [t.c.household_id == household_id]
    if section.table == "cash_records":
        conditions.append(
            t.c.kind.in_(
                (
                    "salary",
                    "bonus",
                    "other_income",
                    "income_return",
                    "insurance_receipt",
                    "insurance_return",
                )
            )
        )
    field = section.date_field
    date_column = None
    monthly = False
    if field == "_month":
        revision, month = tables["asset_month_revisions"], tables["asset_months"]
        source = source.join(
            revision,
            and_(t.c.household_id == revision.c.household_id, t.c.revision_id == revision.c.id),
        ).join(
            month,
            and_(
                revision.c.household_id == month.c.household_id,
                revision.c.id == month.c.current_revision_id,
            ),
        )
        date_column, monthly = month.c.period_month, True
    elif field in {"_cash", "_payout"}:
        # For date-precision month, intersect the selected period with its whole month.
        lower = scope.from_date
        upper = scope.through_date
        if lower:
            conditions.append(
                (cash.c.occurred_on >= lower)
                | (cash.c.occurred_on.is_(None) & (cash.c.period_month >= lower.replace(day=1)))
            )
        if upper:
            conditions.append(
                (cash.c.occurred_on <= upper)
                | (cash.c.occurred_on.is_(None) & (cash.c.period_month <= upper.replace(day=1)))
            )
    elif field:
        date_column = t.c[field]
    if date_column is not None:
        if scope.from_date:
            conditions.append(
                date_column >= (scope.from_date.replace(day=1) if monthly else scope.from_date)
            )
        if scope.through_date:
            conditions.append(
                date_column
                <= (scope.through_date.replace(day=1) if monthly else scope.through_date)
            )
    return select(*columns).select_from(source).where(*conditions).order_by(*t.primary_key.columns)


def document_start(title):
    return (
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        f"<title>{escape(title)}</title><style>"
        "body{font:16px/1.6 sans-serif;max-width:1200px;margin:2rem auto;"
        "padding:0 1rem;color:#182d29;background:white}"
        "table{border-collapse:collapse;width:100%;font-size:.9rem}"
        "th,td{border:1px solid #b7c7c2;padding:.5rem;text-align:left;"
        "vertical-align:top;overflow-wrap:anywhere}.scroll{overflow:auto}"
        "td.money{text-align:right;white-space:nowrap}h2{margin-top:2rem}"
        "a{color:#22675f}@media print{.scroll{overflow:visible}table{font-"
        "size:8pt}}"
        f"</style><body><h1>{escape(title)}</h1>"
    ).encode()


def paragraph(value):
    return f"<p>{escape(value)}</p>".encode()


def html_table(headers, rows, money_columns=()):
    yield (
        '<div class="scroll"><table><thead><tr>'
        + "".join(f'<th scope="col">{escape(label)}</th>' for label in headers)
        + "</tr></thead><tbody>"
    ).encode()
    count = 0
    for row in rows:
        count += 1
        yield (
            "<tr>"
            + "".join(
                f'<td class="money">{escape(str(value))}</td>'
                if index in money_columns
                else f"<td>{escape(str(value))}</td>"
                for index, value in enumerate(row)
            )
            + "</tr>"
        ).encode()
    yield b"</tbody></table></div>"
    if not count:
        yield paragraph("해당 범위에 등록된 기록이 없습니다.")


def write_readable(session, builder, scope):
    names = Names(session, builder.manifest["household_id"], builder.budget)
    household_id = builder.manifest["household_id"]
    builder.manifest["readable"] = {
        "format": "sallimbook-readable-v1",
        **scope.model_dump(mode="json"),
        "names": "current references; asset value names from revision",
        "original_scope": "all domains and all dates when json/csv selected",
    }

    def index():
        yield document_start("SallimBook 읽기용 가계 자료")
        yield paragraph(
            "자료 시점 (서울): "
            + display(
                datetime.fromisoformat(builder.manifest["snapshot_at"].replace("Z", "+00:00"))
            )
        )
        yield paragraph("선택 영역: " + ", ".join(DOMAINS[domain] for domain in scope.domains))
        yield paragraph(
            "사실·예정 회차 기간: "
            f"{display(scope.from_date) if scope.from_date else '시작 제한 없음'} ~ "
            f"{display(scope.through_date) if scope.through_date else '종료 제한 없음'} "
            "(양끝 포함). "
            "월 단위 기록은 겹치는 월을 포함합니다."
        )
        yield paragraph(
            "기본정보·연결 관계는 기간과 무관한 현재 자료입니다. 날짜를 입력하지"
            " 않은 청구는 기간 지정 시 제외됩니다. 기록된 사실만 "
            "포함하며 누락된 금융 거래를 추정하지 않습니다. 연결 대상은 현재 이름,"
            " 월 자산값은 당시 명칭입니다. 시각은 서울 기준입니다. "
            "미입력과 0원을 구분합니다."
        )
        yield paragraph(
            "취소·무효 상태를 확인해 주세요. 자산값은 각 월의 현재 리비전이며 "
            "과거 정정 이력은 전체 JSON/CSV에서 확인합니다. "
            "연결 목록은 중복 합산하지 않습니다. JSON/CSV와 별도 선택 "
            "문서는 이 읽기용 범위로 제한되지 않습니다."
        )
        if scope.annual_year:
            yield (
                f'<p><a href="annual.html">{scope.annual_year}년 가족별 참고 요약 열기</a></p>'
            ).encode()
        for section in SECTIONS:
            if section.domain not in scope.domains:
                continue
            builder.budget.check()
            yield f"<h2>{escape(section.title)}</h2>".encode()
            yield paragraph(
                "선택 기간 적용" if section.date_field else "기간과 무관한 기본정보·연결·현재 상태"
            )
            fields = section.fields.split()
            headers = [LABELS[base_field(field)] for field in fields]

            def rows(section=section, fields=fields):
                for row in session.execute(
                    query_for(section, household_id, scope).execution_options(yield_per=500)
                ).mappings():
                    builder.budget.add("rows", 1)
                    yield [
                        names.resolve(REFS[field], row[field])
                        if field in REFS
                        else display(row[field], base_field(field))
                        for field in fields
                    ]

            yield from html_table(
                headers,
                rows(),
                tuple(index for index, field in enumerate(fields) if field.endswith("_krw")),
            )
        yield b"</body></html>"

    builder._entry("readable/index.html", index())
    if scope.annual_year:
        summary = annual_summary(session, household_id, scope.annual_year, builder.budget)

        def annual():
            yield document_start(f"{scope.annual_year}년 가족별 참고 요약")
            yield paragraph(
                "자료 시점 (서울): "
                + display(
                    datetime.fromisoformat(builder.manifest["snapshot_at"].replace("Z", "+00:00"))
                )
            )
            yield paragraph(
                f"실제 기록 날짜 {scope.annual_year:04d}-01-01 ~ {scope.annual_year:04d}-12-31. "
                "상세 자료에서 선택한 기간과 별개인 연간 집계입니다."
            )
            yield paragraph(
                "순의료비 = 지불 − 환불, 순보험금 = 실제 배분 − 반환, 순부담"
                " = 순의료비 − 순보험금. 청구·결정금액은 포함하지 "
                "않습니다. 이전 연도 지불의 올해 환불·반환은 올해에 반영하며 음수도"
                " 그대로 표시합니다. 무효 기록은 제외합니다."
            )
            yield paragraph(
                "현재 저장된 수동 기록만으로 계산합니다. 전체 금융 거래나 세금 신고"
                " 자료가 아니며 세액 공제를 추정하지 않습니다. 가족은 "
                "환자 기준이고 소득 귀속·기록 작성자와 다릅니다. 가족 미지정 "
                "보험금은 추측 배분하지 않습니다."
            )
            metrics = (
                "medical_paid",
                "medical_refunded",
                "net_medical",
                "insurance_received",
                "insurance_returned",
                "net_insurance",
                "net_burden",
            )

            def people_rows():
                for person, values in sorted(
                    summary["people"].items(), key=lambda item: str(item[0] or "")
                ):
                    yield [
                        names.resolve("people", person) if person else "가족 미지정 보험금",
                        *(display(values[key], "amount_krw") for key in metrics),
                    ]
                yield [
                    "가계 전체 (미지정 포함)",
                    *(display(summary["total"][key], "amount_krw") for key in metrics),
                ]

            yield from html_table(
                [
                    "환자·가족",
                    "의료비 지불",
                    "의료비 환불",
                    "순의료비",
                    "보험금 수령 배분",
                    "보험금 반환",
                    "순보험금",
                    "순부담",
                ],
                people_rows(),
                range(1, 8),
            )
            yield "<h2>보험료와 연금 등 실제 고정 납부</h2>".encode()
            yield paragraph(
                "보험료: 소비성 납부 중 분류가 ‘보험료’이거나 보험료 규칙 연결 "
                "이력이 있는 것. 연금: 분류가 ‘연금’인 자산 이동. "
                "이름으로 용도를 추측하지 않습니다. 환자별 순부담에는 더하지 "
                "않습니다. 분류나 연결이 없는 납부는 다른 항목에 포함됩니다."
            )
            labels = {
                "premium": "보험료",
                "pension": "연금 납입",
                "other_consumption": "나머지 소비성 납부",
                "other_transfer": "나머지 자산 이동",
                "principal": "원금 상환",
            }
            yield from html_table(
                ["항목", "실제 납부액"],
                (
                    [label, display(summary["fixed"][key], "amount_krw")]
                    for key, label in labels.items()
                ),
                (1,),
            )
            yield paragraph(
                f"집계한 사실·배분 행 {summary['fact_count']}개 "
                f"(월만 기록된 행 {summary['month_only_count']}개). "
                "0원은 이 범위에 집계한 금액이 없다는 뜻이며 실제 금융 거래가 "
                "없음을 보증하지 않습니다."
            )
            yield '<p><a href="index.html">상세 자료로 돌아가기</a></p></body></html>'.encode()

        builder._entry("readable/annual.html", annual())
