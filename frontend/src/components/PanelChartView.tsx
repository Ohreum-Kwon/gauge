import type { ReactElement } from 'react'
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { digitsFor } from '../format'
import type { PanelChart, PanelChartPoint, PanelSignal } from '../types'

const RANGE_RULE = 'range_beyond_ucl'
const EWMA_RULE = 'ewma_beyond_limit'

type Row = PanelChartPoint & { signals: PanelSignal[] }
type Severity = PanelSignal['severity'] | null

/** X-bar, R and EWMA charts for one line and metric, sharing one subgroup axis. */
export default function PanelChartView({ chart }: { chart: PanelChart }) {
  const digits = digitsFor(chart)
  const fmt = (v: number) => v.toFixed(digits)
  const rows: Row[] = chart.points.map((p) => ({
    ...p,
    signals: chart.signals.filter((s) => s.subgroup === p.subgroup),
  }))
  // One tick per day, at its first subgroup.
  const ticks = rows
    .filter((r, i) => i === 0 || day(r.measured_at) !== day(rows[i - 1].measured_at))
    .map((r) => r.subgroup)
  const label = (subgroup: number) => {
    const row = rows.find((r) => r.subgroup === subgroup)
    return row ? shortDate(row.measured_at) : ''
  }
  const baselineEnd = chart.points[chart.baseline_subgroups - 1]?.subgroup ?? 0
  const { lsl, usl, unit } = chart.metric

  const xbarValues = [
    ...rows.map((r) => r.mean),
    chart.xbar_ucl,
    chart.xbar_lcl,
    ...[lsl, usl].filter((v): v is number => v !== null),
  ]
  const xbarDomain = padded(Math.min(...xbarValues), Math.max(...xbarValues))

  const xbarSeverity = (r: Row) =>
    worst(r.signals.filter((s) => s.rule !== RANGE_RULE && s.rule !== EWMA_RULE))
  const rangeSeverity = (r: Row) => worst(r.signals.filter((s) => s.rule === RANGE_RULE))
  const ewmaSeverity = (r: Row) => worst(r.signals.filter((s) => s.rule === EWMA_RULE))

  const axes = (domain: [number, number]) => [
    <CartesianGrid key="grid" stroke="var(--chart-grid)" vertical={false} />,
    <XAxis
      key="x"
      dataKey="subgroup"
      type="number"
      domain={['dataMin', 'dataMax']}
      ticks={ticks}
      tickFormatter={label}
      stroke="var(--muted)"
      tick={{ fill: 'var(--muted)', fontSize: 12 }}
      tickLine={false}
    />,
    <YAxis
      key="y"
      domain={domain}
      tickFormatter={fmt}
      stroke="var(--muted)"
      tick={{ fill: 'var(--muted)', fontSize: 12 }}
      tickLine={false}
      axisLine={false}
      width={56}
    />,
    <ReferenceArea
      key="baseline"
      x1={rows[0]?.subgroup}
      x2={baselineEnd}
      fill="var(--chart-grid)"
      fillOpacity={0.5}
      ifOverflow="hidden"
    />,
  ]

  return (
    <>
      <div className="legend" aria-hidden>
        <span>Subgroup mean</span>
        <span className="target">Center line</span>
        <span className="limit">3σ control limits</span>
        {(lsl !== null || usl !== null) && <span className="spec">Spec limits</span>}
        <span className="warn">Warning</span>
        <span className="alert">Alarm</span>
      </div>
      <p className="muted">The shaded span is the baseline the control limits come from.</p>

      <h3>
        X̄ chart{' '}
        <span className="muted">
          (mean of {chart.subgroup_size} panels{unit && `, in ${unit}`})
        </span>
      </h3>
      <div className="chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            {axes(xbarDomain)}
            <ReferenceLine y={chart.center} stroke="var(--chart-limit)" strokeWidth={1.5} />
            {limitLines(chart.xbar_ucl, chart.xbar_lcl)}
            {lsl !== null && specLine(lsl)}
            {usl !== null && specLine(usl)}
            {seriesLine('mean', xbarSeverity)}
            <Tooltip
              content={<RowTooltip fmt={fmt} unit={unit} />}
              cursor={{ stroke: 'var(--chart-grid)' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="columns">
        <div>
          <h3>
            R chart <span className="muted">(range within each subgroup)</span>
          </h3>
          <div className="chart small">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                {axes(padded(0, Math.max(chart.r_ucl, ...rows.map((r) => r.range)), true))}
                <ReferenceLine y={chart.r_center} stroke="var(--chart-limit)" strokeWidth={1.5} />
                {limitLines(chart.r_ucl, chart.r_lcl > 0 ? chart.r_lcl : null)}
                {seriesLine('range', rangeSeverity)}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div>
          <h3>
            EWMA <span className="muted">(λ = 0.2, catches slow drift)</span>
          </h3>
          <div className="chart small">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                {axes(
                  padded(
                    Math.min(...rows.map((r) => Math.min(r.ewma, r.ewma_lcl))),
                    Math.max(...rows.map((r) => Math.max(r.ewma, r.ewma_ucl))),
                  ),
                )}
                <ReferenceLine y={chart.center} stroke="var(--chart-limit)" strokeWidth={1.5} />
                {varyingLimit('ewma_ucl')}
                {varyingLimit('ewma_lcl')}
                {seriesLine('ewma', ewmaSeverity)}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* A table ignores height: 1px; the wrapper keeps its 56 rows out of the layout. */}
      <div className="sr-only">
        <table>
          <caption>Subgroup means, ranges and signals</caption>
          <thead>
            <tr>
              <th>Tested</th>
              <th>Lot</th>
              <th>Mean</th>
              <th>Range</th>
              <th>Signals</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.subgroup}>
                <td>{r.measured_at}</td>
                <td>{r.lot}</td>
                <td>{fmt(r.mean)}</td>
                <td>{fmt(r.range)}</td>
                <td>{r.signals.map((s) => s.description).join('; ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function seriesLine(dataKey: 'mean' | 'range' | 'ewma', severity: (r: Row) => Severity) {
  return (
    <Line
      dataKey={dataKey}
      stroke="var(--series-1)"
      strokeWidth={2}
      dot={<SignalDot severity={severity} />}
      activeDot={{ r: 5, stroke: 'var(--surface)', strokeWidth: 2 }}
      isAnimationActive={false}
    />
  )
}

function limitLines(ucl: number, lcl: number | null): ReactElement[] {
  return [ucl, lcl]
    .filter((v): v is number => v !== null)
    .map((v) => (
      <ReferenceLine
        key={v}
        y={v}
        stroke="var(--chart-limit)"
        strokeDasharray="5 4"
        strokeWidth={1.5}
      />
    ))
}

function varyingLimit(dataKey: 'ewma_ucl' | 'ewma_lcl') {
  return (
    <Line
      dataKey={dataKey}
      stroke="var(--chart-limit)"
      strokeDasharray="5 4"
      strokeWidth={1.5}
      dot={false}
      activeDot={false}
      isAnimationActive={false}
    />
  )
}

function specLine(y: number) {
  return (
    <ReferenceLine
      y={y}
      stroke="var(--status-critical)"
      strokeDasharray="2 3"
      strokeWidth={1.5}
      ifOverflow="extendDomain"
    />
  )
}

function SignalDot(props: {
  cx?: number
  cy?: number
  payload?: Row
  severity: (r: Row) => Severity
}) {
  const { cx, cy, payload, severity } = props
  if (cx === undefined || cy === undefined || !payload) return null
  const level = severity(payload)
  if (!level) return <circle cx={cx} cy={cy} r={2.5} fill="var(--series-1)" />
  return (
    <circle
      cx={cx}
      cy={cy}
      r={level === 'alarm' ? 5 : 4}
      fill={level === 'alarm' ? 'var(--status-critical)' : 'var(--status-warning)'}
      stroke="var(--surface)"
      strokeWidth={1.5}
    />
  )
}

function RowTooltip({
  active,
  payload,
  fmt,
  unit,
}: {
  active?: boolean
  payload?: { payload: Row }[]
  fmt: (v: number) => string
  unit: string
}) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  return (
    <div className="chart-tooltip">
      <p>
        <strong>{new Date(row.measured_at).toLocaleString()}</strong>
      </p>
      <p>
        Mean {fmt(row.mean)}
        {unitSuffix(unit)}, range {fmt(row.range)}
      </p>
      <p className="muted">
        Lot {row.lot} · {row.z >= 0 ? '+' : ''}
        {row.z.toFixed(1)}σ
      </p>
      {row.signals.map((s) => (
        <p key={s.rule} className={s.severity === 'alarm' ? 'error' : undefined}>
          {s.severity === 'alarm' ? 'Alarm' : 'Warning'}: {s.description}
        </p>
      ))}
    </div>
  )
}

function worst(signals: PanelSignal[]): Severity {
  if (signals.some((s) => s.severity === 'alarm')) return 'alarm'
  return signals.length > 0 ? 'warning' : null
}

function padded(lo: number, hi: number, fromZero = false): [number, number] {
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08
  return [fromZero ? 0 : lo - pad, hi + pad]
}

const unitSuffix = (unit: string) => (unit ? ` ${unit}` : '')
const day = (iso: string) => iso.slice(0, 10)

function shortDate(iso: string) {
  const [, month, date] = day(iso).split('-')
  return `${Number(month)}/${Number(date)}`
}
