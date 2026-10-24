import { useCallback, useMemo } from "react";
import type { components } from "@sallimbook/api-client";
import { Link } from "react-router";
import { nativeFinance } from "../../platform/nativeFinance";
import { useAuth } from "../auth/AuthProvider";
import { allPages, useResource } from "../finance/queries";
import { FinanceError } from "../finance/FinanceSupport";

export type HouseholdPerson = components["schemas"]["PersonResponse"];
export const relations = {
  member: "로그인 구성원",
  child: "자녀",
  parent: "부모",
  other: "기타 가족",
};
export function usePeopleApi() {
  const { domainApi } = useAuth();
  return useMemo(
    () => ({
      list: (cursor?: string) =>
        domainApi.read(
          (c) => c.GET("/api/v1/household/people", { params: { query: { cursor, limit: 200 } } }),
          () => nativeFinance.listHouseholdPeople({ query: { cursor, limit: 200 } }),
        ),
      create: (input: components["schemas"]["PersonCreate"], key: string) =>
        domainApi.write(
          (c) =>
            c.POST("/api/v1/household/people", {
              body: input,
              params: { header: { "Idempotency-Key": key } },
            }),
          () => nativeFinance.createHouseholdPerson({ input, idempotencyKey: key }),
        ),
      update: (id: string, input: components["schemas"]["PersonPatch"], version: number) =>
        domainApi.write(
          (c) =>
            c.PATCH("/api/v1/household/people/{person_id}", {
              body: input,
              params: { path: { person_id: id }, header: { "If-Match": `"${version}"` } },
            }),
          () =>
            nativeFinance.updateHouseholdPerson({ personId: id, input, ifMatch: `"${version}"` }),
        ),
    }),
    [domainApi],
  );
}
export function useHouseholdPeople() {
  const api = usePeopleApi();
  const resource = useResource(useCallback(() => allPages((cursor) => api.list(cursor)), [api]));
  return { ...resource, people: resource.data ?? [] };
}
export function PersonSelect({
  value,
  onChange,
  label,
  required = false,
  includeArchived = false,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  required?: boolean;
  includeArchived?: boolean;
}) {
  const result = useHouseholdPeople();
  return (
    <div className="form-field">
      <label>
        {label}
        <select
          required={required}
          value={value}
          disabled={result.loading}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">
            {includeArchived ? "모든 가족" : required ? "가족 선택" : "미지정"}
          </option>
          {result.people
            .filter((p) => includeArchived || p.active || p.id === value)
            .map((p) => (
              <option
                key={p.id}
                value={p.id}
                disabled={!includeArchived && !p.active && p.id !== value}
              >
                {p.display_name}
                {!p.active ? (p.member_id ? " · 계정 사용 종료" : " · 보관됨") : ""}
              </option>
            ))}
          {value && !result.people.some((p) => p.id === value) && (
            <option value={value}>현재 가족 · 확인 필요</option>
          )}
        </select>
      </label>
      <FinanceError error={result.error} />
      {result.error && (
        <button type="button" onClick={() => void result.reload()}>
          가족 목록 다시 확인
        </button>
      )}
      <Link to="/settings/people">가족 관리</Link>
    </div>
  );
}
