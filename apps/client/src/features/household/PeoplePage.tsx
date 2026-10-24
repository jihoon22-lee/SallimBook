import { useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@sallimbook/api-client";
import { Link } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { SessionStatus } from "../auth/AuthFeedback";
import { FinanceError } from "../finance/FinanceSupport";
import { useIdempotencyKey, useMonthCommand } from "../assets/months/useMonthCommand";
import { useUnsavedChangesGuard } from "../../shared/UnsavedChanges";
import { relations, useHouseholdPeople, usePeopleApi } from "./people";
import type { HouseholdPerson } from "./people";

type Relation = components["schemas"]["PersonCreate"]["relation"];
function RelationSelect({ value, change }: { value: Relation; change: (v: Relation) => void }) {
  return (
    <label>
      가족 관계
      <select value={value} onChange={(e) => change(e.target.value as Relation)}>
        {(["child", "parent", "other"] as const).map((r) => (
          <option key={r} value={r}>
            {relations[r]}
          </option>
        ))}
      </select>
    </label>
  );
}
function PersonRow({ row, reload }: { row: HouseholdPerson; reload: () => Promise<void> }) {
  const api = usePeopleApi(),
    command = useMonthCommand();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(row.display_name),
    [relation, setRelation] = useState<Relation>(
      row.relation === "member" ? "other" : row.relation,
    );
  const [version, setVersion] = useState(row.version);
  const guard = useUnsavedChangesGuard(
    editing && (name !== row.display_name || relation !== row.relation),
  );
  async function update(input: components["schemas"]["PersonPatch"]) {
    const result = await command.run(() =>
      api.update(row.id, input, editing ? version : row.version),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      setEditing(false);
      await reload();
    }
  }
  return (
    <li className="card">
      <h2>
        {row.display_name}{" "}
        <small>
          · {relations[row.relation]}
          {row.active ? "" : " · 보관됨"}
        </small>
      </h2>
      {row.member_id ? (
        <p>
          이름과 계정 상태는 <Link to="/settings/auth">계정과 기기</Link>에서 관리해요.
        </p>
      ) : (
        <>
          {editing ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void update({ display_name: name.trim(), relation });
              }}
            >
              <fieldset disabled={command.busy}>
                <legend>가족 정보 수정</legend>
                <label>
                  가족 이름
                  <input
                    required
                    maxLength={120}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <RelationSelect value={relation} change={setRelation} />
              </fieldset>
              <button disabled={command.busy || command.error?.status === 409}>
                가족 정보 저장
              </button>
              <button
                type="button"
                disabled={command.busy}
                onClick={() => {
                  guard.release();
                  setEditing(false);
                }}
              >
                수정 취소
              </button>
            </form>
          ) : (
            <div className="form-actions">
              <button
                onClick={() => {
                  setName(row.display_name);
                  setRelation(row.relation as Relation);
                  setVersion(row.version);
                  command.setError(null);
                  setEditing(true);
                }}
              >
                이름·관계 수정
              </button>
              <button disabled={command.busy} onClick={() => void update({ active: !row.active })}>
                {row.active ? "가족 보관" : "가족 다시 사용"}
              </button>
            </div>
          )}
          <FinanceError error={command.error} />
          {command.error?.status === 409 && (
            <button
              onClick={async () => {
                await reload();
              }}
            >
              최신 가족 정보 확인
            </button>
          )}
          {editing && version !== row.version && (
            <div className="review-panel">
              <p>
                현재 저장된 이름: {row.display_name} · {relations[row.relation]}
              </p>
              <button
                type="button"
                onClick={() => {
                  setVersion(row.version);
                  command.setError(null);
                }}
              >
                입력 유지하고 최신 버전으로 저장 준비
              </button>
            </div>
          )}
        </>
      )}
    </li>
  );
}
function PeopleWorkspace() {
  const list = useHouseholdPeople(),
    api = usePeopleApi(),
    command = useMonthCommand();
  const [name, setName] = useState(""),
    [relation, setRelation] = useState<Relation>("child");
  const [notice, setNotice] = useState("");
  const guard = useUnsavedChangesGuard(Boolean(name));
  const key = useIdempotencyKey(JSON.stringify([name.trim(), relation]));
  async function create(event: FormEvent) {
    event.preventDefault();
    const result = await command.run(() =>
      api.create({ display_name: name.trim(), relation }, key),
    );
    if (result.ok && command.mounted.current) {
      guard.release();
      setName("");
      setNotice("가족을 등록했어요.");
      await list.reload();
    }
  }
  return (
    <>
      <section className="card">
        <h2>가족 추가</h2>
        <p>자녀·부모 등 보험의 환자·피보험자를 등록해요. 가족에게 로그인 권한은 생기지 않아요.</p>
        <form onSubmit={(e) => void create(e)}>
          <fieldset disabled={command.busy}>
            <legend>새 가족</legend>
            <label>
              가족 이름
              <input
                required
                maxLength={120}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <RelationSelect value={relation} change={setRelation} />
          </fieldset>
          {name.trim() && list.people.some((p) => p.display_name === name.trim()) && (
            <p role="status">같은 이름의 가족이 있어요. 다른 가족인지 확인해 주세요.</p>
          )}
          <FinanceError error={command.error} />
          <button disabled={command.busy}>가족 등록</button>
        </form>
        {notice && <p role="status">{notice}</p>}
      </section>
      <FinanceError error={list.error} />
      <button disabled={list.loading} onClick={() => void list.reload()}>
        가족 목록 다시 확인
      </button>
      {list.loading && <p role="status">가족을 확인하고 있어요.</p>}
      <p>가족을 보관해도 과거 보험 기록은 유지돼요. 보관된 가족은 새 기록에서 선택할 수 없어요.</p>
      <ul className="record-list">
        {list.people.map((row) => (
          <PersonRow key={row.id} row={row} reload={list.reload} />
        ))}
      </ul>
    </>
  );
}
export function PeoplePage() {
  const { state } = useAuth();
  return (
    <>
      <div className="intro">
        <p className="eyebrow">공동 가계</p>
        <h1>가족 관리</h1>
        <p>두 로그인 계정과 보험 기록에 등장하는 가족을 구분해 관리해요.</p>
      </div>
      {state.status === "authenticated" ? (
        <PeopleWorkspace key={state.member.member_id} />
      ) : (
        <SessionStatus />
      )}
    </>
  );
}
