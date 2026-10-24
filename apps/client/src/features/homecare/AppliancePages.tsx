import { LastModified } from "../../shared/RecordActor";
import { NameSearch } from "../../shared/NameSearch";
import { DocumentPanel } from "../documents/DocumentPanel";
import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { formatKrw } from "../assets/months/model";
import { dateLabel, isUuid, todaySeoul } from "../finance/dates";
import { usePagedList, useResource } from "../finance/queries";
import { useHomecareApi } from "./api";
import {
  applianceDraft,
  applianceInput,
  changedFields,
  etag,
  preserveDraft,
  statuses,
  warrantyLabels,
} from "./model";
import type { Appliance, ApplianceDraft } from "./model";
import {
  ConflictReview,
  HomecarePage,
  ListFeedback,
  MetadataFeedback,
  ResourceFeedback,
  useMetadataCommand,
} from "./HomecareSupport";
import { DeleteHomecare } from "./DeleteHomecare";
import { completeToday } from "./TodayConsumables";
import { DeviceLinks } from "./DeviceLinks";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { AmountField } from "../../shared/AmountField";
import { FormError, useSubmitAttempt } from "../../shared/formValidation";
import { krwFieldError } from "../../shared/krw";
export function ApplianceSummary({ row }: { row: Appliance }) {
  return (
    <>
      <dl className="metadata-grid">
        <div>
          <dt>가전 이름</dt>
          <dd>{row.name}</dd>
        </div>
        <div>
          <dt>제조사 · 모델</dt>
          <dd>
            {row.manufacturer || "미입력"} · {row.model || "미입력"}
          </dd>
        </div>
        <div>
          <dt>설치 장소</dt>
          <dd>{row.location || "미입력"}</dd>
        </div>
        <div>
          <dt>구매일 · 판매처</dt>
          <dd>
            {dateLabel(row.purchased_on ?? null)} · {row.seller || "미입력"}
          </dd>
        </div>
        <div>
          <dt>구매 금액</dt>
          <dd>{formatKrw(row.purchase_price_krw ?? null)}</dd>
        </div>
        <div>
          <dt>보증기한</dt>
          <dd>
            {dateLabel(row.warranty_until ?? null)} · {warrantyLabels[row.warranty_status]}
          </dd>
        </div>
        <div>
          <dt>사용 상태</dt>
          <dd>
            {statuses[row.status]}
            {row.ended_on && ` · ${dateLabel(row.ended_on)}`}
          </dd>
        </div>
        <div>
          <dt>관리·수리 메모</dt>
          <dd>{row.note || "미입력"}</dd>
        </div>
        <LastModified record={row} />
      </dl>
      <p className="muted">
        보증 표시는 {dateLabel(row.as_of)} 기준 기록한 기한과 비교한 결과예요. 실제 보증 조건은 구매
        문서에서 확인해 주세요.
      </p>
    </>
  );
}
export function ApplianceEditor({ initial }: { initial?: Appliance }) {
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  const api = useHomecareApi();
  const navigate = useNavigate();
  const command = useMetadataCommand();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(() => applianceDraft(initial));
  const [latest, setLatest] = useState<Appliance | null>(null);
  const [ack, setAck] = useState(false);
  const [message, setMessage] = useState("");
  const attempt = useSubmitAttempt();
  const input = applianceInput(draft);
  const changed =
    base && input ? changedFields(applianceInput(applianceDraft(base))!, input) : null;
  const ending = !!draft.ended && draft.ended !== base?.ended_on;
  const change = <K extends keyof ApplianceDraft>(key: K, value: ApplianceDraft[K]) => {
    setDraft((old) => ({ ...old, [key]: value }));
    if (key === "ended") setAck(false);
    if (!base && !command.uncertain) command.setError(null);
  };
  async function submit(e: FormEvent<HTMLFormElement>) {
    const form = e.currentTarget;
    e.preventDefault();
    if (command.error?.status === 409) return;
    const problem = !input
      ? "가전 이름·날짜·구매 금액을 확인해 주세요. 날짜는 오늘을 넘을 수 없고 사용 종료일은 구매일 이후여야 해요."
      : ending && !ack
        ? "사용 종료 확인란을 선택해 주세요."
        : base && !Object.keys(changed ?? {}).length
          ? "바꾼 가전 정보가 없어요."
          : "";
    if (problem || !input) {
      setMessage(problem);
      attempt.reject(form);
      return;
    }
    const row = await command.run(
      () =>
        base
          ? api.updateAppliance({
              applianceId: base.id,
              input: changed!,
              ifMatch: etag(base.version),
            })
          : api.createAppliance({ input }),
      !base,
    );
    if (row && command.mounted.current) {
      guard.release();
      navigate(`/appliances/${row.id}${base ? "" : "#device-consumables"}`, {
        replace: true,
        state: !base ? { applianceCreated: true } : null,
      });
    }
  }
  async function compare() {
    if (!base) return;
    try {
      const row = await api.getAppliance({ applianceId: base.id });
      if (command.mounted.current) setLatest(row);
    } catch (e) {
      if (command.mounted.current) command.setError(toApiError(e));
    }
  }
  function adopt(keep: boolean) {
    if (!latest) return;
    setDraft(
      keep
        ? preserveDraft(applianceDraft(base), draft, applianceDraft(latest))
        : applianceDraft(latest),
    );
    setBase(latest);
    setLatest(null);
    command.setError(null);
    setAck(false);
  }
  return (
    <section className="card">
      <h2>제품·구매·보증 정보</h2>
      <p>구매 금액은 자산과 수입·지출 기록에 자동 합산하지 않아요.</p>
      <form
        onInput={() => {
          setDirty(true);
          setMessage("");
        }}
        onSubmit={(e) => void submit(e)}
      >
        <fieldset disabled={command.busy}>
          <legend>가전 정보</legend>
          <div className="form-grid">
            {(
              [
                ["name", "가전 이름"],
                ["manufacturer", "제조사"],
                ["model", "모델명"],
                ["location", "설치 장소"],
                ["seller", "판매처"],
              ] as const
            ).map(([key, label]) => (
              <div className="form-field" key={key}>
                <label>
                  {label}
                  <input
                    required={key === "name"}
                    maxLength={120}
                    value={draft[key]}
                    onChange={(e) => change(key, e.target.value)}
                  />
                </label>
              </div>
            ))}
            <div className="form-field">
              <label>
                구매일
                <input
                  type="date"
                  max={todaySeoul()}
                  value={draft.purchased}
                  onChange={(e) => change("purchased", e.target.value)}
                />
              </label>
            </div>
            <AmountField
              label="구매 금액 (원)"
              value={draft.price}
              hint="미입력과 0원을 구분해요."
              error={
                attempt.attempted
                  ? krwFieldError(draft.price, { required: false, positive: false })
                  : null
              }
              onChange={(value) => change("price", value)}
            />
            <div className="form-field">
              <label>
                보증기한
                <input
                  type="date"
                  value={draft.warranty}
                  onChange={(e) => change("warranty", e.target.value)}
                />
              </label>
            </div>
            <div className="form-field">
              <label>
                가전 사용 종료일
                <input
                  type="date"
                  max={todaySeoul()}
                  min={draft.purchased || undefined}
                  value={draft.ended}
                  onChange={(e) => change("ended", e.target.value)}
                />
              </label>
              <p className="muted">비우면 사용 중이에요. 종료해도 교체·구매 이력은 보존돼요.</p>
            </div>
            <div className="form-field">
              <label>
                관리·수리 메모
                <textarea
                  maxLength={2000}
                  value={draft.note}
                  onChange={(e) => change("note", e.target.value)}
                />
              </label>
            </div>
          </div>
          {ending && (
            <label className="checkbox-field">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              종료 후 새 교체 기록이 제한되고 오늘 관리 목록에서 제외됨을 확인했어요
            </label>
          )}
        </fieldset>
        <FormError message={message} />
        <MetadataFeedback command={command} listPath="/appliances?status=all" />
        <ConflictReview
          error={base ? command.error : null}
          compare={() => void compare()}
          latest={!!latest}
          adopt={() => adopt(true)}
          replace={() => adopt(false)}
        >
          {latest && <ApplianceSummary row={latest} />}
        </ConflictReview>
        <button
          type="submit"
          disabled={command.busy || command.uncertain || command.error?.status === 409}
        >
          {base ? "가전 수정 저장" : "가전 등록"}
        </button>
      </form>
    </section>
  );
}
function ApplianceList() {
  const api = useHomecareApi();
  const [params, setParams] = useSearchParams();
  const status =
    params.get("status") === "all" ? "all" : params.get("status") === "ended" ? "ended" : "active";
  const q = params.get("q") ?? "";
  const list = usePagedList(
    useCallback(
      (cursor?: string) =>
        api.listAppliances({ query: { status, cursor, limit: 50, ...(q ? { q } : {}) } }),
      [api, status, q],
    ),
    undefined,
    "appliances",
  );
  const today = useResource(
    useCallback(
      () => completeToday((cursor) => api.getHomecareStatus({ query: { cursor, limit: 200 } })),
      [api],
    ),
  );
  return (
    <>
      <NameSearch label="가전 이름·모델·장소 검색" />
      <ResourceFeedback resource={today} />
      <div className="form-field">
        <label>
          가전 사용 상태
          <select
            value={status}
            onChange={(e) =>
              setParams((previous) => {
                const next = new URLSearchParams(previous);
                next.set("status", e.target.value);
                return next;
              })
            }
          >
            {Object.entries(statuses).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="record-list">
        {list.items.map((row) => (
          <article className="card" key={row.id}>
            <h2>
              <Link to={`/appliances/${row.id}`}>{row.name}</Link>
            </h2>
            <p>
              {row.location || "장소 미입력"} · {row.model || "모델 미입력"} ·{" "}
              {statuses[row.status]}
            </p>
            <p>
              {warrantyLabels[row.warranty_status]} · {dateLabel(row.warranty_until ?? null)} (
              {dateLabel(row.as_of)} 기준)
            </p>
            {today.data && !today.error && !today.loading && row.status === "active" && (
              <p>
                오늘 소모품:{" "}
                {today.data.items.some((link) => link.appliance_id === row.id) ? (
                  <>
                    교체 확인{" "}
                    {
                      today.data.items.filter(
                        (link) => link.appliance_id === row.id && link.replacement_due === true,
                      ).length
                    }
                    개 · 구매 필요{" "}
                    {
                      today.data.items.filter(
                        (link) => link.appliance_id === row.id && link.purchase_needed,
                      ).length
                    }
                    개 · 기준일 미확인{" "}
                    {
                      today.data.items.filter(
                        (link) => link.appliance_id === row.id && link.replacement_due === null,
                      ).length
                    }
                    개
                  </>
                ) : (
                  "사용 중인 연결 없음"
                )}
              </p>
            )}
            <Link to={`/appliances/${row.id}#device-consumables`}>연결 소모품·교체 확인</Link>
          </article>
        ))}
      </div>
      <ListFeedback
        list={list}
        empty="해당 상태의 가전이 없어요. 제품을 등록해 구매·보증과 소모품을 관리해 보세요."
      />
    </>
  );
}
export function ApplianceListPage() {
  return (
    <HomecarePage
      title="가전 관리"
      description="제품 정보와 설치 장소, 구매·보증과 연결 소모품을 관리해요."
      navigation={
        <div className="form-actions">
          <Link className="button-link" to="/appliances/new">
            가전 등록하기
          </Link>
          <Link to="/consumables">공용 소모품 관리</Link>
        </div>
      }
    >
      <ApplianceList />
    </HomecarePage>
  );
}
export function ApplianceNewPage() {
  return (
    <HomecarePage title="가전 등록" description="구매일과 교체일은 각각 기록해요.">
      <ApplianceEditor />
    </HomecarePage>
  );
}
function ApplianceDetail({ id, edit }: { id: string; edit: boolean }) {
  const api = useHomecareApi();
  const navigate = useNavigate();
  const resource = useResource(
    useCallback(
      () =>
        isUuid(id)
          ? api.getAppliance({ applianceId: id })
          : Promise.reject(new ApiError(404, "NOT_FOUND")),
      [api, id],
    ),
  );
  const row = resource.data;
  return (
    <>
      <ResourceFeedback resource={resource} />
      {row &&
        !resource.error &&
        !resource.loading &&
        (edit ? (
          <ApplianceEditor key={`${row.id}:${row.version}`} initial={row} />
        ) : (
          <>
            <section className="card">
              <h2>{row.name}</h2>
              <ApplianceSummary row={row} />
              <Link to={`/appliances/${id}/edit`}>가전 정보 수정·사용 종료</Link>
              <DeleteHomecare
                initial={row}
                label="가전"
                name={row.name}
                read={() => api.getAppliance({ applianceId: id })}
                remove={(current, signal) =>
                  api.deleteAppliance({ applianceId: id, ifMatch: etag(current.version) }, signal)
                }
                render={(current) => <ApplianceSummary row={current} />}
                deleted={() => navigate("/appliances", { replace: true })}
                listPath="/appliances?status=all"
              />
            </section>
            <DocumentPanel kind="appliance" id={id} />
            <DeviceLinks appliance={row} />
          </>
        ))}
    </>
  );
}
export function ApplianceDetailPage({ edit = false }: { edit?: boolean }) {
  const { id = "" } = useParams();
  return (
    <HomecarePage
      title={edit ? "가전 정보 수정" : "가전 상세"}
      description="구매·보증·수리 메모와 기기별 교체 기준을 확인해요."
    >
      <ApplianceDetail key={`${id}:${edit}`} id={id} edit={edit} />
    </HomecarePage>
  );
}
