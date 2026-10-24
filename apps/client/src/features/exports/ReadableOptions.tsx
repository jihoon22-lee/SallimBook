import { DateInput } from "../../shared/DateInput";
import { seoulMonth } from "../../shared/month";
import { exportDomains, validExportDate } from "../../platform/exportScope";
import type { ReadableExport } from "../../platform/exportScope";

export type ReadingSelection = {
  enabled: boolean;
  fromValid: boolean;
  throughValid: boolean;
  domains: ReadableExport["domains"];
  from: string;
  through: string;
  annual: boolean;
  year: string;
};
export const initialReading = (): ReadingSelection => ({
  enabled: false,
  fromValid: true,
  throughValid: true,
  domains: Object.keys(exportDomains) as ReadableExport["domains"],
  from: "",
  through: "",
  annual: false,
  year: seoulMonth().slice(0, 4),
});
export function readingProblem(value: ReadingSelection): string | null {
  if (!value.enabled) return null;
  if (!value.fromValid || !value.throughValid) return "읽기용 기간의 날짜를 확인해 주세요.";
  if (!value.domains.length) return "읽기용 영역을 하나 이상 선택해 주세요.";
  if (
    (value.from && !validExportDate(value.from)) ||
    (value.through && !validExportDate(value.through))
  )
    return "읽기용 기간의 날짜를 확인해 주세요.";
  if (value.from && value.through && value.from > value.through)
    return "읽기용 종료일은 시작일 이후여야 해요.";
  if (value.annual && (!/^\d{1,4}$/.test(value.year) || Number(value.year) < 1))
    return "요약 연도를 1~9999 사이로 입력해 주세요.";
  return null;
}
export function readingInput(value: ReadingSelection): ReadableExport | undefined {
  return value.enabled
    ? {
        domains: [...value.domains],
        ...(value.from ? { from_date: value.from } : {}),
        ...(value.through ? { through_date: value.through } : {}),
        ...(value.annual && value.domains.includes("insurance")
          ? { annual_year: Number(value.year) }
          : {}),
      }
    : undefined;
}
export function ReadableOptions({
  value,
  changed,
  busy,
}: {
  value: ReadingSelection;
  changed: (next: ReadingSelection) => void;
  busy: boolean;
}) {
  function update(patch: Partial<ReadingSelection>) {
    changed({ ...value, ...patch });
  }
  return (
    <section className="card">
      <h2>읽기용 자료와 연간 참고 요약</h2>
      <p>
        사람·연결 대상의 현재 이름과 서울 시각이 보이는 HTML 파일이에요. ZIP을 풀고 readable 폴더의
        index.html을 브라우저에서 열거나 인쇄할 수 있어요.
      </p>
      <fieldset disabled={busy}>
        <legend>읽기용 자료 선택</legend>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={value.enabled}
            onChange={(e) => update({ enabled: e.target.checked })}
          />
          읽기용 HTML 포함
        </label>
        {value.enabled && (
          <>
            <fieldset>
              <legend>읽기용 영역</legend>
              {(Object.keys(exportDomains) as ReadableExport["domains"]).map((domain) => (
                <label key={domain} className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={value.domains.includes(domain)}
                    onChange={(e) =>
                      update({
                        domains: e.target.checked
                          ? [...value.domains, domain]
                          : value.domains.filter((item) => item !== domain),
                        ...(domain === "insurance" && !e.target.checked ? { annual: false } : {}),
                      })
                    }
                  />
                  {exportDomains[domain]}
                </label>
              ))}
            </fieldset>
            <div className="form-grid">
              <label>
                읽기용 시작일 (선택)
                <DateInput
                  value={value.from}
                  min="0001-01-01"
                  max="9999-12-31"
                  onChange={(e) =>
                    update({ from: e.target.value, fromValid: e.currentTarget.validity.valid })
                  }
                />
              </label>
              <label>
                읽기용 종료일 (선택)
                <DateInput
                  value={value.through}
                  min="0001-01-01"
                  max="9999-12-31"
                  onChange={(e) =>
                    update({
                      through: e.target.value,
                      throughValid: e.currentTarget.validity.valid,
                    })
                  }
                />
              </label>
            </div>
            <p>
              기본정보·연결 관계는 기간과 무관하게 포함해요. 실제 금전 기록·예정 회차·월별
              자산값·재고 이력에 기간을 적용하며, 일자를 모르는 월 기록은 겹치는 월에 포함해요.
            </p>
            {value.domains.includes("insurance") && (
              <>
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={value.annual}
                    onChange={(e) => update({ annual: e.target.checked })}
                  />
                  연간 가족별 참고 요약 포함
                </label>
                {value.annual && (
                  <>
                    <label>
                      요약 연도
                      <input
                        type="number"
                        min="1"
                        max="9999"
                        step="1"
                        value={value.year}
                        onChange={(e) => update({ year: e.target.value })}
                      />
                    </label>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={!/^\d{1,4}$/.test(value.year) || Number(value.year) < 1}
                      onClick={() => {
                        const year = value.year.padStart(4, "0");
                        update({
                          from: `${year}-01-01`,
                          through: `${year}-12-31`,
                          fromValid: true,
                          throughValid: true,
                        });
                      }}
                    >
                      상세 자료도 같은 연도로 맞추기
                    </button>
                    <p>
                      annual.html에 해당 연도 1월 1일~12월 31일의 실제 지불·환불·수령·반환을
                      요약해요. 위 상세 자료 기간과 별개예요. 환자·가족별 순의료비·순보험금·순부담과
                      미지정 보험금을 구분해요.
                    </p>
                    <p>
                      보험료·연금 납입은 저장된 분류·연결에 따라 별도 집계해요. 청구·결정금액을
                      수령액으로 더하지 않고, 세액 공제를 추정하지 않아요. 직접 등록한 실제 기록만
                      포함하는 참고자료예요.
                    </p>
                  </>
                )}
              </>
            )}
          </>
        )}
      </fieldset>
    </section>
  );
}
