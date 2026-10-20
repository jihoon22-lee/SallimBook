import { Icon } from "./Icon";
export type ResourceStatus = "loading" | "empty" | "error" | "stale" | "forbidden" | "conflict";

const states: Record<ResourceStatus, { title: string; description: string }> = {
  loading: { title: "기록을 불러오는 중이에요", description: "잠시만 기다려 주세요." },
  empty: {
    title: "아직 기록이 없어요",
    description: "첫 기록을 추가하면 이곳에서 확인할 수 있어요.",
  },
  error: {
    title: "기록을 불러오지 못했어요",
    description: "연결 상태를 확인한 뒤 다시 시도해 주세요.",
  },
  stale: {
    title: "최신 내용인지 확인이 필요해요",
    description: "다시 불러와 현재 기록을 확인해 주세요.",
  },
  forbidden: {
    title: "이 기록에 접근할 수 없어요",
    description: "로그인한 계정과 가계 접근 권한을 확인해 주세요.",
  },
  conflict: {
    title: "다른 변경 사항이 있어요",
    description: "저장하지 않았어요. 최신 내용을 확인하고 변경 사항을 다시 적용해 주세요.",
  },
};

export function ResourceState({
  status,
  onRetry,
}: {
  status: ResourceStatus;
  onRetry?: () => void;
}) {
  const state = states[status];
  return (
    <section
      className="card resource-state"
      role={status === "error" || status === "conflict" ? "alert" : "status"}
      aria-busy={status === "loading"}
    >
      <span className="empty-state-icon">
        <Icon
          name={status === "loading" ? "refresh" : status === "empty" ? "book" : "insurance"}
          size={26}
        />
      </span>
      <h2>{state.title}</h2>
      <p>{state.description}</p>
      {onRetry && ["error", "stale", "conflict"].includes(status) && (
        <button onClick={onRetry}>다시 불러오기</button>
      )}
    </section>
  );
}
