import { useState } from "react";
import { useSearchParams } from "react-router";

export function NameSearch({ label, hint }: { label: string; hint?: string }) {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  return (
    <NameSearchForm
      key={query}
      initial={query}
      label={label}
      hint={hint}
      search={(value) => {
        const next = new URLSearchParams(params);
        if (value.trim()) next.set("q", value.trim());
        else next.delete("q");
        next.delete("cursor");
        setParams(next);
      }}
    />
  );
}
function NameSearchForm({
  initial,
  label,
  hint,
  search,
}: {
  initial: string;
  label: string;
  hint?: string;
  search: (value: string) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <form
      className="card"
      role="search"
      aria-label={label}
      onSubmit={(event) => {
        event.preventDefault();
        search(value);
      }}
    >
      <div className="form-field">
        <label>
          {label}
          <input
            type="search"
            maxLength={120}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </label>
      </div>
      {hint && <p className="muted">{hint}</p>}
      <div className="form-actions">
        <button type="submit">이름 검색</button>
        {initial && (
          <button type="button" onClick={() => search("")}>
            검색 지우기
          </button>
        )}
      </div>
    </form>
  );
}
