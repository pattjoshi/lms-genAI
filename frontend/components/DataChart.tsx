"use client";

// Phase 6: the chart under a SQL agent answer. The backend picks the form from the shape of the
// result (app/sql_agent/chart.py): number, bar (categories) or line (time). No chart library:
// horizontal bars are plain divs, the line chart is one SVG. Colours are the --series-* tokens,
// in fixed order. The table under the chart always has the exact values.

import { useMemo, useState } from "react";

export type ChartSpec = { type: "number" | "bar" | "line"; x: string | null; y: string[] };
export type Cell = string | number | boolean | null;

const SERIES = ["bg-series-1", "bg-series-2", "bg-series-3"];
const STROKE = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

export function label(column: string) {
  const s = column.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatValue(v: Cell): string {
  if (v === null) return "–";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-IN") : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}(T|$)/.test(v)) return formatDate(v);
  return String(v);
}

// The calendar date as Postgres sent it (India time), not shifted into the browser's time zone.
function dateOf(v: string) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(v);
}

function formatDate(v: string) {
  const d = dateOf(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function compact(v: number) {
  // Small values (e.g. a day's AI cost in USD) would all round to "0" with one decimal.
  if (v !== 0 && Math.abs(v) < 1) return v.toLocaleString("en-US", { maximumSignificantDigits: 2 });
  return v.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });
}

function Legend({ series }: { series: string[] }) {
  if (series.length < 2) return null;
  return (
    <div className="mb-3 flex flex-wrap gap-4 text-xs text-muted">
      {series.map((s, i) => (
        <span key={s} className="flex items-center gap-1.5">
          <span className={`h-2.5 w-2.5 rounded-sm ${SERIES[i]}`} />
          {label(s)}
        </span>
      ))}
    </div>
  );
}

function BigNumber({ value, name }: { value: Cell; name: string }) {
  return (
    <div className="py-2">
      <p className="text-sm text-muted">{label(name)}</p>
      <p className="font-display text-4xl font-bold text-fg">{formatValue(value)}</p>
    </div>
  );
}

function Bars({ spec, columns, rows }: { spec: ChartSpec; columns: string[]; rows: Cell[][] }) {
  const xi = columns.indexOf(spec.x ?? "");
  const yi = spec.y.map((y) => columns.indexOf(y));
  const values = rows.flatMap((r) => yi.map((i) => (typeof r[i] === "number" ? (r[i] as number) : 0)));
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const span = max - min || 1;
  const [hover, setHover] = useState<number | null>(null);

  return (
    <div>
      <Legend series={spec.y} />
      <div className="space-y-1" onMouseLeave={() => setHover(null)}>
        {rows.map((r, ri) => (
          <div
            key={ri}
            onMouseEnter={() => setHover(ri)}
            className={`grid grid-cols-[minmax(0,9rem)_1fr] items-center gap-3 rounded-lg px-1 py-1 sm:grid-cols-[minmax(0,14rem)_1fr] ${hover === ri ? "bg-surface-2" : ""}`}
          >
            <span className="truncate text-xs text-muted" title={formatValue(r[xi])}>
              {formatValue(r[xi])}
            </span>
            <div className="relative space-y-0.5">
              {yi.map((col, si) => {
                const v = typeof r[col] === "number" ? (r[col] as number) : 0;
                const left = ((Math.min(v, 0) - min) / span) * 100;
                const width = (Math.abs(v) / span) * 100;
                return (
                  <div key={col} className="relative h-3">
                    <div
                      className={`absolute top-0 h-3 rounded-r ${SERIES[si]}`}
                      style={{ left: `${left}%`, width: `${Math.max(width, 0.5)}%` }}
                    />
                  </div>
                );
              })}
              {hover === ri && (
                <div className="pointer-events-none absolute right-0 top-1/2 z-10 -translate-y-1/2 rounded-lg border border-line bg-surface px-2 py-1 text-xs text-fg shadow-card">
                  {yi.map((col, si) => (
                    <span key={col} className="mr-2 inline-flex items-center gap-1 last:mr-0">
                      {spec.y.length > 1 && <span className={`h-2 w-2 rounded-sm ${SERIES[si]}`} />}
                      {label(spec.y[si])}: <b>{formatValue(r[col])}</b>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// A round number at or above v (1, 1.2, 1.6, 2, 2.4 ... 8, 10 x 10^n), so the grid lines land on round values.
function niceCeil(v: number) {
  if (v <= 0) return v === 0 ? 0 : v;
  const p = 10 ** Math.floor(Math.log10(v));
  return ([1, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6, 8, 10].find((m) => m * p >= v) ?? 10) * p;
}

function Line({ spec, columns, rows }: { spec: ChartSpec; columns: string[]; rows: Cell[][] }) {
  const xi = columns.indexOf(spec.x ?? "");
  const yi = spec.y.map((y) => columns.indexOf(y));
  const points = useMemo(
    () =>
      rows
        .map((r) => ({ t: dateOf(String(r[xi])).getTime(), row: r }))
        .filter((p) => !Number.isNaN(p.t))
        .sort((a, b) => a.t - b.t),
    [rows, xi],
  );
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return null;

  const W = 640, H = 240, L = 64, R = 12, T = 12, B = 28;
  const values = points.flatMap((p) => yi.map((i) => (typeof p.row[i] === "number" ? (p.row[i] as number) : 0)));
  const yMax = niceCeil(Math.max(0, ...values));
  const yMin = -niceCeil(-Math.min(0, ...values));
  const t0 = points[0].t, t1 = points[points.length - 1].t;
  const x = (t: number) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - yMin) / (yMax - yMin || 1)) * (H - T - B);
  if (yMax === yMin) return null;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => yMin + f * (yMax - yMin));
  const xLabels = [0, Math.floor((points.length - 1) / 2), points.length - 1];

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    let best = 0;
    points.forEach((p, i) => {
      if (Math.abs(x(p.t) - px) < Math.abs(x(points[best].t) - px)) best = i;
    });
    setHover(best);
  };
  const hp = hover !== null ? points[hover] : null;

  return (
    <div>
      <Legend series={spec.y} />
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-auto w-full"
          role="img"
          aria-label={`${spec.y.map(label).join(", ")} over ${label(spec.x ?? "time")}`}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        >
          {ticks.map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" strokeWidth={1} />
              <text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize={11} fill="var(--faint)">
                {compact(v)}
              </text>
            </g>
          ))}
          {[...new Set(xLabels)].map((i) => (
            <text
              key={i}
              x={x(points[i].t)}
              y={H - 8}
              textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
              fontSize={11}
              fill="var(--faint)"
            >
              {formatDate(String(points[i].row[xi]))}
            </text>
          ))}
          {yi.map((col, si) => (
            <polyline
              key={col}
              fill="none"
              stroke={STROKE[si]}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              points={points.map((p) => `${x(p.t)},${y(typeof p.row[col] === "number" ? (p.row[col] as number) : 0)}`).join(" ")}
            />
          ))}
          {hp && (
            <g>
              <line x1={x(hp.t)} x2={x(hp.t)} y1={T} y2={H - B} stroke="var(--faint)" strokeDasharray="3 3" />
              {yi.map((col, si) => (
                <circle
                  key={col}
                  cx={x(hp.t)}
                  cy={y(typeof hp.row[col] === "number" ? (hp.row[col] as number) : 0)}
                  r={4.5}
                  fill={STROKE[si]}
                  stroke="var(--surface)"
                  strokeWidth={2}
                />
              ))}
            </g>
          )}
        </svg>
        {hp && (
          <div className="pointer-events-none absolute right-2 top-1 rounded-lg border border-line bg-surface px-2 py-1 text-xs text-fg shadow-card">
            <p className="text-muted">{formatDate(String(hp.row[xi]))}</p>
            {yi.map((col, si) => (
              <p key={col} className="flex items-center gap-1">
                {spec.y.length > 1 && <span className={`h-2 w-2 rounded-sm ${SERIES[si]}`} />}
                {label(spec.y[si])}: <b>{formatValue(hp.row[col])}</b>
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function DataChart({ spec, columns, rows }: { spec: ChartSpec; columns: string[]; rows: Cell[][] }) {
  if (spec.type === "number") return <BigNumber value={rows[0]?.[0] ?? null} name={spec.y[0]} />;
  if (spec.type === "bar") return <Bars spec={spec} columns={columns} rows={rows} />;
  return <Line spec={spec} columns={columns} rows={rows} />;
}
