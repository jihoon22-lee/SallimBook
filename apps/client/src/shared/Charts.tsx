import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { formatKrwShort } from "./krwShort";

/** Pixel geometry only: a rounded Number is enough to place a mark; labels use the strings. */
const plot = (value: string) => Number(BigInt(value));

/** Round gridline values (1, 2 or 5 times a power of ten) covering `low` to `high`. */
function niceTicks(low: number, high: number, wanted = 4): number[] {
  const raw = (high - low || Math.abs(high) || 1) / (wanted - 1);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / magnitude;
  const step = (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * magnitude;
  const ticks = [];
  for (let value = Math.floor(low / step) * step; value < high + step; value += step)
    ticks.push(value);
  return ticks;
}

/** A short axis label such as "6.2억" or "300만"; exact amounts live in the tooltip and table. */
function axisLabel(value: number): string {
  const size = Math.abs(value);
  if (size >= 1e8) return `${parseFloat((value / 1e8).toFixed(2))}억`;
  if (size >= 1e4) return `${Math.round(value / 1e4).toLocaleString("ko-KR")}만`;
  return Math.round(value).toLocaleString("ko-KR");
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

type Tip = { x: number; y: number; lines: ReactNode } | null;
function Tooltip({ tip, width }: { tip: Tip; width: number }) {
  if (!tip) return null;
  const x = Math.max(84, Math.min(width - 84, tip.x));
  return (
    <div className="chart-tip" style={{ left: x, top: tip.y }} aria-hidden="true">
      {tip.lines}
    </div>
  );
}

export type TrendPoint = {
  key: string;
  /** Short axis label, e.g. "11". */
  tick: string;
  /** Full label for the tooltip and the table, e.g. "2026년 11월". */
  label: string;
  value: string | null;
  /** A confirmed month draws a filled dot; an unconfirmed one a ring. */
  solid: boolean;
  detail?: string;
};

/** One series over time. Months without a value break the line instead of dropping to zero. */
export function TrendLine({ points, title }: { points: TrendPoint[]; title: string }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const height = 210;
  const left = 46;
  const right = 14;
  const top = 12;
  const bottom = 26;
  const known = points.flatMap((point) => (point.value === null ? [] : [plot(point.value)]));
  if (known.length === 0) return <p className="muted">{title}를 그릴 금액이 아직 없어요.</p>;
  const low = Math.min(...known);
  const high = Math.max(...known);
  const pad = Math.max((high - low) * 0.08, Math.abs(high) * 0.005, 1);
  const ticks = niceTicks(low - pad, high + pad);
  const from = ticks[0]!;
  const to = ticks.at(-1)!;
  const step = points.length > 1 ? (width - left - right) / (points.length - 1) : 0;
  const x = (index: number) =>
    points.length > 1 ? left + step * index : (left + width - right) / 2;
  const y = (value: number) => top + (height - top - bottom) * (1 - (value - from) / (to - from));
  // Consecutive known months form one stroke; a gap starts a new one.
  const runs: number[][] = [];
  points.forEach((point, index) => {
    if (point.value === null) return;
    const last = runs.at(-1);
    if (last && last.at(-1) === index - 1) last.push(index);
    else runs.push([index]);
  });
  const sparse = width < 520 ? Math.ceil(points.length / 5) : 1;
  const shown = active === null ? null : points[active]!;
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg
          viewBox={`0 0 ${width} ${height}`}
          height={height}
          role="img"
          aria-label={title}
          onPointerMove={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            const index = step ? Math.round((event.clientX - box.left - left) / step) : 0;
            setActive(Math.max(0, Math.min(points.length - 1, index)));
          }}
          onPointerLeave={() => setActive(null)}
        >
          {ticks.map((value) => (
            <g key={value}>
              <line
                className="chart-grid"
                x1={left}
                x2={width - right}
                y1={y(value)}
                y2={y(value)}
              />
              <text className="chart-axis" x={left - 8} y={y(value) + 4} textAnchor="end">
                {axisLabel(value)}
              </text>
            </g>
          ))}
          {points.map(
            (point, index) =>
              (points.length - 1 - index) % sparse === 0 && (
                <text
                  key={point.key}
                  className="chart-axis"
                  x={x(index)}
                  y={height - 6}
                  textAnchor="middle"
                >
                  {point.tick}
                </text>
              ),
          )}
          {runs.map((run) => {
            const path = run.map((index) => `${x(index)},${y(plot(points[index]!.value!))}`);
            return (
              <g key={run[0]}>
                {run.length > 1 && (
                  <path
                    className="chart-area"
                    d={`M${path.join("L")}L${x(run.at(-1)!)},${height - bottom}L${x(run[0]!)},${height - bottom}Z`}
                  />
                )}
                <path className="chart-line" d={`M${path.join("L")}`} />
              </g>
            );
          })}
          {active !== null && shown!.value !== null && (
            <line
              className="chart-cross"
              x1={x(active)}
              x2={x(active)}
              y1={top}
              y2={height - bottom}
            />
          )}
          {points.map(
            (point, index) =>
              point.value !== null && (
                <circle
                  key={point.key}
                  className={point.solid ? "chart-dot" : "chart-dot chart-dot-open"}
                  cx={x(index)}
                  cy={y(plot(point.value))}
                  r={index === points.length - 1 ? 5 : 4}
                />
              ),
          )}
        </svg>
      )}
      <Tooltip
        width={width}
        tip={
          shown
            ? {
                x: x(active!),
                y: shown.value === null ? height / 2 : y(plot(shown.value)),
                lines: (
                  <>
                    {shown.label}
                    {shown.detail ? ` · ${shown.detail}` : ""}
                    <br />
                    <b>{shown.value === null ? "금액 없음" : formatKrwShort(shown.value)}</b>
                  </>
                ),
              }
            : null
        }
      />
    </div>
  );
}

export type Bar = {
  key: string;
  tick: string;
  label: string;
  /** Null draws no bar: the month has nothing to show, which is not zero. */
  value: string | null;
  note?: string;
};

/** One small series of bars from a zero baseline; a negative value hangs below it. */
export function BarSeries({ bars, title }: { bars: Bar[]; title: string }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const height = 104;
  const top = 18;
  const bottom = 20;
  const values = bars.map((bar) => (bar.value === null ? 0 : plot(bar.value)));
  const high = Math.max(0, ...values);
  const low = Math.min(0, ...values);
  const span = high - low || 1;
  const zero = top + (height - top - bottom) * (high / span);
  const slot = bars.length ? width / bars.length : 0;
  const thick = Math.max(4, Math.min(24, slot - 4));
  const sparse = bars.length > 6 ? 3 : 1;
  const last = bars.length - 1;
  const shown = active === null ? null : bars[active]!;
  // The bars carry no visible numbers, so the accessible name states every value.
  const spoken = `${title}: ${bars
    .map((bar) => `${bar.label} ${bar.value === null ? "없음" : formatKrwShort(bar.value)}`)
    .join(", ")}`;
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg viewBox={`0 0 ${width} ${height}`} height={height} role="img" aria-label={spoken}>
          <line className="chart-base" x1={0} x2={width} y1={zero} y2={zero} />
          {bars.map((bar, index) => {
            const center = slot * index + slot / 2;
            const size = (Math.abs(values[index]!) / span) * (height - top - bottom);
            const up = values[index]! >= 0;
            const edge = up ? zero - size : zero + size;
            const round = Math.min(4, size);
            return (
              <g key={bar.key}>
                {bar.value !== null && size > 0 && (
                  <path
                    className={index === last ? "chart-bar chart-bar-now" : "chart-bar"}
                    d={
                      up
                        ? `M${center - thick / 2},${zero}V${edge + round}q0,${-round} ${round},${-round}H${center + thick / 2 - round}q${round},0 ${round},${round}V${zero}Z`
                        : `M${center - thick / 2},${zero}V${edge - round}q0,${round} ${round},${round}H${center + thick / 2 - round}q${round},0 ${round},${-round}V${zero}Z`
                    }
                  />
                )}
                {(index % sparse === 0 || index === last) && (
                  <text className="chart-axis" x={center} y={height - 5} textAnchor="middle">
                    {bar.tick}
                  </text>
                )}
                <rect
                  x={slot * index}
                  y={0}
                  width={slot}
                  height={height}
                  fill="transparent"
                  onPointerEnter={() => setActive(index)}
                  onPointerLeave={() => setActive(null)}
                />
              </g>
            );
          })}
        </svg>
      )}
      <Tooltip
        width={width}
        tip={
          shown
            ? {
                x: slot * active! + slot / 2,
                y: top,
                lines: (
                  <>
                    {shown.label}
                    <br />
                    <b>{shown.value === null ? "계산할 기록 없음" : formatKrwShort(shown.value)}</b>
                    {shown.note && (
                      <>
                        <br />
                        {shown.note}
                      </>
                    )}
                  </>
                ),
              }
            : null
        }
      />
    </div>
  );
}

export type Segment = { name: string; value: string; tone: string };
export type Column = { key: string; tick: string; label: string; segments: Segment[] };

/** Stacked columns from zero with a 2px gap between segments; the legend names each tone. */
export function StackedColumns({ columns, title }: { columns: Column[]; title: string }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const height = 250;
  const left = 46;
  const top = 12;
  const bottom = 26;
  const totals = columns.map((column) =>
    column.segments.reduce((sum, segment) => sum + Math.max(0, plot(segment.value)), 0),
  );
  const ticks = niceTicks(0, Math.max(1, ...totals));
  const high = ticks.at(-1)!;
  const slot = columns.length ? (width - left) / columns.length : 0;
  const thick = Math.max(4, Math.min(24, slot - 6));
  const y = (value: number) => top + (height - top - bottom) * (1 - value / high);
  const sparse = width < 520 ? 3 : 1;
  const shown = active === null ? null : columns[active]!;
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg viewBox={`0 0 ${width} ${height}`} height={height} role="img" aria-label={title}>
          {ticks.map((value) => (
            <g key={value}>
              <line
                className={value ? "chart-grid" : "chart-base"}
                x1={left}
                x2={width}
                y1={y(value)}
                y2={y(value)}
              />
              <text className="chart-axis" x={left - 8} y={y(value) + 4} textAnchor="end">
                {axisLabel(value)}
              </text>
            </g>
          ))}
          {columns.map((column, index) => {
            const center = left + slot * index + slot / 2;
            let base = 0;
            const drawn = column.segments.filter((segment) => plot(segment.value) > 0);
            return (
              <g key={column.key}>
                {drawn.map((segment, order) => {
                  const start = y(base);
                  base += plot(segment.value);
                  const end = y(base) + (order < drawn.length - 1 ? 2 : 0);
                  const round = order === drawn.length - 1 ? Math.min(4, start - end) : 0;
                  return (
                    <path
                      key={segment.name}
                      className={`chart-tone-${segment.tone}`}
                      d={`M${center - thick / 2},${start}V${end + round}q0,${-round} ${round},${-round}H${center + thick / 2 - round}q${round},0 ${round},${round}V${start}Z`}
                    />
                  );
                })}
                {(width >= 520 || (columns.length - 1 - index) % sparse === 0) && (
                  <text className="chart-axis" x={center} y={height - 6} textAnchor="middle">
                    {column.tick}
                  </text>
                )}
                <rect
                  x={left + slot * index}
                  y={0}
                  width={slot}
                  height={height - bottom}
                  fill="transparent"
                  onPointerEnter={() => setActive(index)}
                  onPointerLeave={() => setActive(null)}
                />
              </g>
            );
          })}
        </svg>
      )}
      <Tooltip
        width={width}
        tip={
          shown
            ? {
                x: left + slot * active! + slot / 2,
                y: y(totals[active!]!),
                lines: (
                  <>
                    {shown.label}
                    {shown.segments
                      .slice()
                      .reverse()
                      .map((segment) => (
                        <span key={segment.name}>
                          <br />
                          {segment.name} <b>{formatKrwShort(segment.value)}</b>
                        </span>
                      ))}
                  </>
                ),
              }
            : null
        }
      />
    </div>
  );
}

/** One horizontal bar split by share, with its legend as a list of exact amounts. */
export function ShareBar({
  segments,
  label,
  amount,
}: {
  segments: Segment[];
  label: string;
  amount: (value: string) => ReactNode;
}) {
  const id = useId();
  const drawn = segments.filter((segment) => plot(segment.value) > 0);
  return (
    <>
      <div className="share-bar" role="img" aria-labelledby={id}>
        {drawn.map((segment) => (
          <span
            key={segment.name}
            className={`chart-tone-${segment.tone}`}
            style={{ flexGrow: plot(segment.value) }}
          />
        ))}
      </div>
      <dl className="share-keys" id={id} aria-label={label}>
        {segments.map((segment) => (
          <div key={segment.name}>
            <dt>
              <i className={`chart-tone-${segment.tone}`} aria-hidden="true" />
              {segment.name}
            </dt>
            <dd>{amount(segment.value)}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}
