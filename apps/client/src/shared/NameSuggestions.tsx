import { useId } from "react";
import { useResource } from "../features/finance/queries";

/** Public institution names only; the household's own names come from its saved records. */
export const commonCardIssuers = [
  "BC카드",
  "KB국민카드",
  "NH농협카드",
  "롯데카드",
  "삼성카드",
  "신한카드",
  "우리카드",
  "하나카드",
  "현대카드",
] as const;
export const commonInsurers = [
  "DB손해보험",
  "KB손해보험",
  "NH농협생명",
  "NH농협손해보험",
  "교보생명",
  "동양생명",
  "라이나생명",
  "롯데손해보험",
  "메리츠화재",
  "미래에셋생명",
  "삼성생명",
  "삼성화재",
  "신한라이프",
  "한화생명",
  "한화손해보험",
  "현대해상",
  "흥국화재",
] as const;
export const commonInstitutions = [
  "IBK기업은행",
  "KB국민은행",
  "NH농협은행",
  "신한은행",
  "우리은행",
  "하나은행",
  "카카오뱅크",
  "케이뱅크",
  "토스뱅크",
  "KB증권",
  "NH투자증권",
  "미래에셋증권",
  "삼성증권",
  "키움증권",
  "토스증권",
  "한국투자증권",
] as const;

/**
 * Typing stays free. The list offers names this household already saved plus common
 * institutions, so one issuer is not split into two spellings across lists and subtotals.
 * A failed read leaves only the common names; suggestions never block the form.
 */
export function useNameSuggestions(
  read: () => Promise<(string | null | undefined)[]>,
  common: readonly string[],
) {
  const id = useId();
  const saved = useResource(read);
  const names = [
    ...new Set(
      [...(saved.data ?? []), ...common]
        .map((name) => name?.trim())
        .filter((name): name is string => !!name),
    ),
  ].sort((a, b) => a.localeCompare(b, "ko"));
  return {
    id,
    list: (
      <datalist id={id}>
        {names.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
    ),
  };
}
