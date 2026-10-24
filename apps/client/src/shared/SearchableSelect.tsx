import { useId, useState } from "react";

export type SearchOption = { value: string; label: string; disabled?: boolean };
/** Native select keeps keyboard/mobile behaviour; filtering never discards the selected ID. */
export function SearchableSelect({
  label,
  value,
  onChange,
  options,
  placeholder,
  disabled,
  required,
  describedBy,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SearchOption[];
  placeholder: string;
  disabled?: boolean;
  required?: boolean;
  describedBy?: string;
}) {
  const [query, setQuery] = useState("");
  const id = useId();
  const term = query.trim().normalize("NFKC").toLocaleLowerCase("ko-KR");
  const matches = options.filter(
    (option) => !term || option.label.normalize("NFKC").toLocaleLowerCase("ko-KR").includes(term),
  );
  const visible = options.filter((option) => option.value === value || matches.includes(option));
  if (value && !options.some((option) => option.value === value))
    visible.push({ value, label: "현재 선택 · 이름 확인 필요", disabled: true });
  return (
    <>
      <label htmlFor={`${id}-search`}>{label} 검색</label>
      <input
        id={`${id}-search`}
        type="search"
        onInput={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.preventDefault();
        }}
        maxLength={120}
        value={query}
        disabled={disabled}
        onChange={(event) => setQuery(event.target.value)}
      />
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        required={required}
        aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{placeholder}</option>
        {visible.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
      {term && (
        <p className="muted" role="status">
          검색 결과 {matches.length}개
          {value && !matches.some((option) => option.value === value)
            ? " · 현재 선택은 유지해요."
            : ""}
        </p>
      )}
    </>
  );
}
