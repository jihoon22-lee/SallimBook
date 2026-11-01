import { useCallback, useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../../../platform/api";
import { MonthPicker, formatMonth, useMonth } from "../../../shared/MonthContext";
import { useResource } from "../../finance/queries";
import { FinanceError, dateLabel, type HouseholdMember } from "../../finance/FinanceSupport";
import { formatKrw, maxAsOfDate, valueDraft } from "../months/model";
import { useAssetComparisonApi } from "./api";
import { useAssetMonthsApi } from "../months/api";
import { useIdempotencyKey, useMonthCommand } from "../months/useMonthCommand";
import { MonthRowEditor, type EditingValue } from "../months/MonthRowEditor";
import { useHouseholdOverview } from "../../dashboard/overviewApi";

/** One editor per page, independent of the refreshed list and pinned to its opening month. */
export function useSavedAmounts() {
  const api = useAssetComparisonApi();
  const months = useAssetMonthsApi();
  const { month, currentMonth } = useMonth();
  const resource = useResource(useCallback(() => api.all({ to: month }), [api, month]));
  // Each item's latest entered amount, shown when the selected month has none of its own.
  const latest = useHouseholdOverview(month);
  const command = useMonthCommand();
  const draftKey = useIdempotencyKey(month);
  const [editor, setEditor] = useState<{ month: string; value: EditingValue } | null>(null);
  const [notice, setNotice] = useState<{ text: string; to: string } | null>(null);
  async function open(assetId: string) {
    if (editor || command.busy || month > currentMonth) return;
    setNotice(null);
    const result = await command.run(async (signal) => {
      try {
        return await months.all(month, signal);
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== "MONTH_NOT_FOUND") throw error;
        await months.draft(month, { copy_previous: false }, draftKey, signal);
        return months.all(month, signal);
      }
    });
    if (!result.ok || !command.mounted.current) return;
    const record = result.value;
    const to = `/assets/months/${month}?asset_id=${assetId}`;
    if (record.state === "confirmed") {
      setNotice({
        text: "이미 마감한 달이에요. 월 기록에서 정정을 시작하면 이전 금액도 이력으로 남아요.",
        to,
      });
      return;
    }
    const row = record.values.find((value) => value.asset_id === assetId);
    if (!row) {
      setNotice({
        text: "이 달의 자산 목록에 아직 포함되지 않았어요. 월 기록에서 보유 목록을 갱신할 수 있어요.",
        to,
      });
      return;
    }
    setEditor({
      month,
      value: {
        revisionId: record.revision_id,
        row,
        draft: {
          ...valueDraft(row),
          asOf: row.as_of_date ?? (month === currentMonth ? maxAsOfDate(month) : ""),
        },
      },
    });
  }
  return {
    ...resource,
    latest,
    editor,
    notice,
    command,
    open,
    months,
    locked: command.busy || editor !== null,
    close: () => setEditor(null),
    saved: () => {
      setEditor(null);
      void resource.reload();
      void latest.reload();
    },
  };
}
type Amounts = ReturnType<typeof useSavedAmounts>;
export function SavedAmountsStatus({
  result,
  members,
}: {
  result: Amounts;
  members: HouseholdMember[];
}) {
  return (
    <div>
      <fieldset className="month-picker-lock" disabled={result.locked}>
        <MonthPicker />
      </fieldset>
      {result.loading && <p role="status">저장된 금액 불러오는 중</p>}
      <FinanceError error={result.error} />
      <FinanceError error={result.command.error} />
      {result.error && (
        <button onClick={() => void result.reload()}>저장 금액 다시 불러오기</button>
      )}
      {result.notice && (
        <p role="status">
          {result.notice.text} <Link to={result.notice.to}>월 기록 열기</Link>
        </p>
      )}
      {result.editor && (
        <section aria-label="목록에서 금액 수정">
          <p>{formatMonth(result.editor.month)} 금액을 수정하고 있어요.</p>
          <MonthRowEditor
            key={`${result.editor.month}:${result.editor.value.row.asset_id}`}
            month={result.editor.month}
            initial={result.editor.value}
            members={members}
            offerNext={false}
            reload={() => result.months.all(result.editor!.month)}
            saved={result.saved}
            close={result.close}
          />
        </section>
      )}
    </div>
  );
}
export function SavedAmount({ result, assetId }: { result: Amounts; assetId: string }) {
  const { month, currentMonth } = useMonth();
  const data = !result.error && !result.loading ? result.data : null;
  const row = data?.items.find((item) => item.asset_id === assetId)?.after;
  // A quiet hint only: a failed status read never adds an error to the list.
  const latest =
    row?.owned_amount_krw == null && !result.latest.error
      ? result.latest.data?.holdings.items.find((item) => item.asset_id === assetId)
      : undefined;
  return (
    <div className="saved-amount">
      {data && (
        <p>
          <span>{formatMonth(month)} 가계 보유분 </span>
          <strong>{row ? formatKrw(row.owned_amount_krw) : "미입력"}</strong>
          {latest?.owned_amount_krw != null && latest.basis_month && (
            <small>
              {" "}
              · 최근 입력 {formatKrw(latest.owned_amount_krw)} ({formatMonth(latest.basis_month)}{" "}
              기준)
            </small>
          )}
          {row?.as_of_date && <small> · {dateLabel(row.as_of_date)} 기준</small>}
          {row?.verification_state === "carried_unconfirmed" && (
            <small> · 전월에서 가져온 금액</small>
          )}
          {row?.inclusion_status === "excluded" && <small> · 합계 제외</small>}
        </p>
      )}
      <button
        type="button"
        className="secondary-button"
        disabled={result.locked || month > currentMonth}
        onClick={() => void result.open(assetId)}
      >
        금액 입력·수정
      </button>
    </div>
  );
}
