import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Alert, ChartPoint, ControlChart } from '../types'
import { percent } from '../format'

type Row = ChartPoint & { alerts: Alert[] }

/** How a chart's numbers read: the gold p-chart by default; the judge's agreement chart
 * passes its own words. */
export interface ChartWording {
  series: string // legend for the plotted line
  center: string // legend for the center line, before its value
  defects: string // tooltip: "{rate} {defects} ({n} of {m} {noun})"
  noun: string
}

const GOLD_WORDING: ChartWording = {
  series: 'Daily error rate',
  center: 'Target',
  defects: 'wrong',
  noun: 'gold',
}

/** A labeler's p-chart: daily gold error rate against the target and its 3-sigma limits.
 * For a model labeler, a dotted line marks each day its model version changed. */
export default function ControlChartView({
  chart,
  wording = GOLD_WORDING,
}: {
  chart: ControlChart
  wording?: ChartWording
}) {
  const rows: Row[] = chart.points.map((point) => ({
    ...point,
    alerts: chart.alerts.filter((a) => a.day === point.day),
  }))
  const versionChanges = rows.filter(
    (r, i) => i > 0 && r.model_version && r.model_version !== rows[i - 1].model_version,
  )
  // Round the top up to the next 10% so ticks land on whole tens.
  const peak = Math.max(...rows.map((r) => Math.max(r.ucl, r.error_rate)))
  const top = Math.min(1, Math.ceil((peak + 0.02) * 10) / 10)
  const ticks = Array.from({ length: Math.round(top * 10) + 1 }, (_, i) => i / 10)

  return (
    <>
      <div className="legend" aria-hidden>
        <span>{wording.series}</span>
        <span className="target">
          {wording.center} {percent(chart.center)}
        </span>
        <span className="limit">3σ control limits</span>
        <span className="alert">Alert</span>
        {versionChanges.length > 0 && <span className="version">Model update</span>}
      </div>
      <div className="chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={shortDay}
              stroke="var(--muted)"
              tick={{ fill: 'var(--muted)', fontSize: 12 }}
              tickLine={false}
            />
            <YAxis
              domain={[0, top]}
              ticks={ticks}
              tickFormatter={(v: number) => percent(v)}
              stroke="var(--muted)"
              tick={{ fill: 'var(--muted)', fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={48}
            />
            <ReferenceLine y={chart.center} stroke="var(--chart-limit)" strokeWidth={1.5} />
            {versionChanges.map((r) => (
              <ReferenceLine
                key={r.day}
                x={r.day}
                stroke="var(--gold)"
                strokeDasharray="2 3"
                strokeWidth={2}
                label={{
                  value: r.model_version ?? '',
                  position: 'insideTopLeft',
                  fill: 'var(--gold)',
                  fontSize: 12,
                }}
              />
            ))}
            <Line
              dataKey="ucl"
              type="stepAfter"
              stroke="var(--chart-limit)"
              strokeDasharray="5 4"
              strokeWidth={1.5}
              dot={false}
              activeDot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="lcl"
              type="stepAfter"
              stroke="var(--chart-limit)"
              strokeDasharray="5 4"
              strokeWidth={1.5}
              dot={false}
              activeDot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="error_rate"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={<PointDot />}
              activeDot={{ r: 6, stroke: 'var(--surface)', strokeWidth: 2 }}
              isAnimationActive={false}
            />
            <Tooltip
              content={<ChartTooltip wording={wording} />}
              cursor={{ stroke: 'var(--chart-grid)' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <table className="sr-only">
        <caption>{wording.series}</caption>
        <thead>
          <tr>
            <th>Day</th>
            <th>{wording.defects}</th>
            <th>Rate</th>
            <th>Upper limit</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.day}>
              <td>{r.day}</td>
              <td>
                {r.errors} of {r.gold_answered}
              </td>
              <td>{percent(r.error_rate)}</td>
              <td>{percent(r.ucl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function PointDot(props: { cx?: number; cy?: number; payload?: Row }) {
  const { cx, cy, payload } = props
  if (cx === undefined || cy === undefined || !payload) return null
  const alert = payload.alerts.length > 0
  return (
    <circle
      cx={cx}
      cy={cy}
      r={alert ? 5 : 4}
      fill={alert ? 'var(--status-critical)' : 'var(--series-1)'}
      stroke="var(--surface)"
      strokeWidth={2}
    />
  )
}

function ChartTooltip({
  active,
  payload,
  wording,
}: {
  active?: boolean
  payload?: { payload: Row }[]
  wording: ChartWording
}) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  return (
    <div className="chart-tooltip">
      <p>
        <strong>{row.day}</strong>
      </p>
      <p>
        {percent(row.error_rate)} {wording.defects} ({row.errors} of {row.gold_answered}{' '}
        {wording.noun})
      </p>
      {row.model_version && <p className="muted">Model {row.model_version}</p>}
      <p className="muted">Upper limit {percent(row.ucl)}</p>
      {row.alerts.map((a) => (
        <p key={a.rule} className="error">
          {a.description}
        </p>
      ))}
    </div>
  )
}

function shortDay(day: string) {
  const [, month, date] = day.split('-')
  return `${Number(month)}/${Number(date)}`
}
