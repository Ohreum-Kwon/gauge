import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { api } from '../api'
import PanelChartView from '../components/PanelChartView'
import StatusBadge from '../components/StatusBadge'
import { digitsFor } from '../format'
import type { Capability, PanelChart, PanelMetric, PanelSeriesSummary, PanelSignal } from '../types'

const GROUPS = { optical: 'Optical', electrical: 'TFT and electrical' } as const

type Selection = { line: string; metric: string }

export default function PanelLinePage() {
  const summary = useQuery({ queryKey: ['panel-line'], queryFn: api.panelLine })
  const [picked, setPicked] = useState<Selection | null>(null)

  if (summary.isPending) return <p className="muted">Loading…</p>
  if (summary.error) return <p className="error">{summary.error.message}</p>

  const { lines, metrics, series } = summary.data
  if (series.length === 0) {
    return (
      <>
        <h1>Panel line</h1>
        <p className="muted">
          No panel measurements yet. Run <code>python -m app.panel_sim</code> to simulate a week.
        </p>
      </>
    )
  }

  // Until someone picks a cell, open on the earliest alarm: the problem to look at first.
  const firstAlarm = [...series]
    .filter((s) => s.first_alarm)
    .sort((a, b) => a.first_alarm!.subgroup - b.first_alarm!.subgroup)[0]
  const selected = picked ?? firstAlarm ?? { line: series[0].line, metric: series[0].metric }

  return (
    <>
      <h1>Panel line</h1>
      <p className="muted">
        End-of-line test results for display panels, five panels every three hours on each line.
        Control limits come from the first {summary.data.baseline_subgroups} subgroups. A point
        beyond 3σ or a range beyond its limit is an alarm; the zone rules and the EWMA are early
        warnings. Cpk is shown for the baseline and the latest day. Select a cell to see its charts.
      </p>
      <StatusGrid
        lines={lines}
        metrics={metrics}
        series={series}
        selected={selected}
        onSelect={setPicked}
      />
      <MetricDetail line={selected.line} metric={metrics.find((m) => m.key === selected.metric)!} />
    </>
  )
}

function StatusGrid({
  lines,
  metrics,
  series,
  selected,
  onSelect,
}: {
  lines: string[]
  metrics: PanelMetric[]
  series: PanelSeriesSummary[]
  selected: Selection
  onSelect: (s: Selection) => void
}) {
  const find = (line: string, metric: string) =>
    series.find((s) => s.line === line && s.metric === metric)

  return (
    <div className="card table-wrap">
      <table className="panel-grid">
        <thead>
          <tr>
            <th>Metric</th>
            <th className="spec-col">Spec</th>
            {lines.map((line) => (
              <th key={line}>Line {line}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(Object.keys(GROUPS) as (keyof typeof GROUPS)[]).map((group) => (
            <Fragment key={group}>
              <tr className="group">
                <th colSpan={2 + lines.length}>{GROUPS[group]}</th>
              </tr>
              {metrics
                .filter((m) => m.group === group)
                .map((m) => (
                  <tr key={m.key}>
                    <td>{m.name}</td>
                    <td className="muted spec-col">{spec(m)}</td>
                    {lines.map((line) => {
                      const s = find(line, m.key)
                      const isSelected = selected.line === line && selected.metric === m.key
                      return (
                        <td key={line} className={isSelected ? 'selected' : undefined}>
                          {s ? (
                            <button
                              type="button"
                              className="cell"
                              aria-pressed={isSelected}
                              aria-label={`${m.name}, line ${line}`}
                              onClick={() => onSelect({ line, metric: m.key })}
                            >
                              <StatusBadge status={s.status} />
                              <span className="muted">
                                Cpk {s.baseline_cpk.toFixed(2)} → {s.recent_cpk.toFixed(2)}
                              </span>
                            </button>
                          ) : (
                            <span className="muted">–</span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MetricDetail({ line, metric }: { line: string; metric: PanelMetric }) {
  const chart = useQuery({
    queryKey: ['panel-chart', line, metric.key],
    queryFn: () => api.panelChart(line, metric.key),
  })

  return (
    <section className="card">
      <h2>
        {metric.name}, line {line}
      </h2>
      <p className="muted">
        Spec {spec(metric)} · target {metric.target}
        {metric.unit && ` ${metric.unit}`}
      </p>
      {chart.isPending && <p className="muted">Loading chart…</p>}
      {chart.error && <p className="error">{chart.error.message}</p>}
      {chart.data && (
        <>
          <PanelChartView chart={chart.data} />
          <CapabilityTable chart={chart.data} />
          <SignalList chart={chart.data} />
        </>
      )}
    </section>
  )
}

function CapabilityTable({ chart }: { chart: PanelChart }) {
  const digits = digitsFor(chart)
  const rows: [string, Capability][] = [
    ['Baseline', chart.baseline_capability],
    ['Latest day', chart.recent_capability],
  ]
  const index = (v: number | null) => (v === null ? '–' : v.toFixed(2))
  return (
    <>
      <h3>Capability</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Period</th>
              <th className="num">Mean</th>
              <th className="num">σ within</th>
              <th className="num">Cp</th>
              <th className="num">Cpk</th>
              <th className="num">Ppk</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, c]) => (
              <tr key={label}>
                <td>{label}</td>
                <td className="num">{c.mean.toFixed(digits)}</td>
                <td className="num">{c.sigma_within.toFixed(digits + 1)}</td>
                <td className="num">{index(c.cp)}</td>
                <td className="num">
                  <strong>{index(c.cpk)}</strong>
                </td>
                <td className="num">{index(c.ppk)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Cpk of 1.33 or more is the usual bar for a capable process. Cp is blank for a one-sided
        spec.
      </p>
    </>
  )
}

function SignalList({ chart }: { chart: PanelChart }) {
  const monitored = chart.signals.filter((s) => s.subgroup >= chart.baseline_subgroups)
  // One line per subgroup and severity keeps a long drift readable.
  const shown = monitored.slice(0, 12)
  return (
    <>
      <h3>Signals after the baseline</h3>
      {monitored.length === 0 ? (
        <p className="muted">None. Every subgroup is within the control limits.</p>
      ) : (
        <>
          <ul className="alerts">
            {shown.map((s) => (
              <li key={`${s.subgroup}-${s.rule}`}>
                <SignalText signal={s} chart={chart} />
              </li>
            ))}
          </ul>
          {monitored.length > shown.length && (
            <p className="muted">and {monitored.length - shown.length} more.</p>
          )}
        </>
      )}
    </>
  )
}

function SignalText({ signal, chart }: { signal: PanelSignal; chart: PanelChart }) {
  const lot = chart.points.find((p) => p.subgroup === signal.subgroup)?.lot
  return (
    <>
      <strong className={signal.severity === 'alarm' ? 'error' : undefined}>
        {signal.severity === 'alarm' ? 'Alarm' : 'Warning'}
      </strong>{' '}
      {new Date(signal.measured_at).toLocaleString()}: {signal.description}{' '}
      <span className="muted">
        ({signal.above ? 'high' : 'low'}, lot {lot})
      </span>
    </>
  )
}

function spec(m: PanelMetric) {
  const unit = m.unit ? ` ${m.unit}` : ''
  if (m.lsl !== null && m.usl !== null) return `${m.lsl} to ${m.usl}${unit}`
  if (m.lsl !== null) return `≥ ${m.lsl}${unit}`
  return `≤ ${m.usl}${unit}`
}
