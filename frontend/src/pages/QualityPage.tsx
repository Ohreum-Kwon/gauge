import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import CauseList from '../components/CauseList'
import ControlChartView, { type ChartWording } from '../components/ControlChartView'
import StatusBadge from '../components/StatusBadge'
import { kappa, percent, seconds } from '../format'
import type { Alert, ChartKind, LabelerQuality, ProjectQuality } from '../types'

export default function QualityPage() {
  const projectId = Number(useParams().projectId)
  const { user } = useAuth()
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.project(projectId),
  })
  const quality = useQuery({
    queryKey: ['quality', projectId],
    queryFn: () => api.quality(projectId),
  })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  // The landing page links here with ?labeler=<email> to open on one labeler's chart.
  const focusEmail = useSearchParams()[0].get('labeler')

  if (quality.isPending) return <p className="muted">Loading…</p>
  if (quality.error) return <p className="error">{quality.error.message}</p>

  const { labelers } = quality.data
  // Until someone picks a row, show the labeler most in need of attention.
  const selected =
    labelers.find((l) => l.user_id === selectedId) ??
    labelers.find((l) => l.email === focusEmail) ??
    labelers.find((l) => l.status === 'out_of_control') ??
    labelers[0]

  return (
    <>
      <Link to={user?.role === 'admin' ? `/projects/${projectId}` : '/projects'} className="muted">
        ← {project.data?.name ?? 'Project'}
      </Link>
      <h1>Labeler quality</h1>
      <p className="muted">
        Gold error rate against a target of {percent(quality.data.target_error_rate)}. Select a
        labeler to see their control chart, and open an alert to see its likely causes.
      </p>
      {labelers.length === 0 ? (
        <p className="muted">No labels yet.</p>
      ) : (
        <LabelerTable labelers={labelers} selectedId={selected?.user_id} onSelect={setSelectedId} />
      )}
      {selected && <LabelerChart projectId={projectId} labeler={selected} />}
      <AgreementCard quality={quality.data} />
    </>
  )
}

function LabelerTable({
  labelers,
  selectedId,
  onSelect,
}: {
  labelers: LabelerQuality[]
  selectedId?: number
  onSelect: (id: number) => void
}) {
  return (
    <div className="card table-wrap">
      <table>
        <thead>
          <tr>
            <th>Labeler</th>
            <th>Status</th>
            <th className="num">Labels</th>
            <th className="num">Gold accuracy</th>
            <th className="num">Median time</th>
            <th className="num">Under 1 s</th>
            <th>Latest alert</th>
          </tr>
        </thead>
        <tbody>
          {labelers.map((l) => (
            <tr
              key={l.user_id}
              className={`selectable${l.user_id === selectedId ? ' selected' : ''}`}
              aria-selected={l.user_id === selectedId}
              onClick={() => onSelect(l.user_id)}
            >
              <td className="nowrap">
                <button type="button" className="link" onClick={() => onSelect(l.user_id)}>
                  {l.email}
                </button>
                {l.is_model && <ModelTag version={l.model_version} />}
              </td>
              <td className="nowrap">
                <StatusBadge status={l.status} />
              </td>
              <td className="num">{l.labels}</td>
              <td className="num">
                {percent(l.accuracy)}{' '}
                <span className="muted">
                  ({l.gold_correct}/{l.gold_answered})
                </span>
              </td>
              <td className="num">{seconds(l.median_time_ms)}</td>
              <td className="num">{percent(l.fast_share)}</td>
              <td>
                {l.latest_alert ? (
                  <>
                    {l.latest_alert.day}: {l.latest_alert.description}
                  </>
                ) : (
                  <span className="muted">None</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LabelerChart({ projectId, labeler }: { projectId: number; labeler: LabelerQuality }) {
  const chart = useQuery({
    queryKey: ['chart', projectId, labeler.user_id],
    queryFn: () => api.controlChart(projectId, labeler.user_id),
  })

  return (
    <section className="card">
      <h2>
        {labeler.email}
        {labeler.is_model && <ModelTag version={labeler.model_version} />}
      </h2>
      {labeler.is_model && (
        <p className="muted">
          An LLM judge labeling in shadow mode: it labels the items people label, after them. Its
          labels are monitored here but never replace a person's or decide a final label.
        </p>
      )}
      {chart.isPending && <p className="muted">Loading chart…</p>}
      {chart.error && <p className="error">{chart.error.message}</p>}
      {chart.data && chart.data.points.length === 0 && (
        <p className="muted">No gold answers yet, so there is nothing to chart.</p>
      )}
      {chart.data && chart.data.points.length > 0 && (
        <>
          {labeler.is_model && <h3>Gold error rate</h3>}
          <ControlChartView chart={chart.data} />
          <h3>Alerts</h3>
          <AlertList
            key={`gold-${labeler.user_id}`}
            projectId={projectId}
            userId={labeler.user_id}
            alerts={chart.data.alerts}
            chart="gold"
          />
        </>
      )}
      {labeler.is_model && <JudgeAgreement projectId={projectId} labeler={labeler} />}
    </section>
  )
}

function ModelTag({ version }: { version: string | null }) {
  return (
    <span className="tag model-tag" title="A model labeler (LLM judge)">
      Model{version ? ` · ${version}` : ''}
    </span>
  )
}

const AGREEMENT_WORDING: ChartWording = {
  series: 'Daily disagreement with people',
  center: 'Its baseline',
  defects: 'disagreed',
  noun: 'compared',
}

/** The judge's second chart: disagreement with in-control people, against its own start. */
function JudgeAgreement({ projectId, labeler }: { projectId: number; labeler: LabelerQuality }) {
  const quality = useQuery({
    queryKey: ['quality', projectId],
    queryFn: () => api.quality(projectId),
  })
  const agreement = useQuery({
    queryKey: ['agreement-chart', projectId, labeler.user_id],
    queryFn: () => api.agreementChart(projectId, labeler.user_id),
  })
  if (agreement.isPending) return <p className="muted">Loading agreement chart…</p>
  if (agreement.error) return <p className="error">{agreement.error.message}</p>
  const data = agreement.data
  const email = (id: number) =>
    quality.data?.labelers.find((l) => l.user_id === id)?.email ?? `#${id}`

  return (
    <>
      <h3>Disagreement with people</h3>
      {data === null ? (
        <p className="muted">
          Not enough labels shared with in-control people yet to set the judge's baseline.
        </p>
      ) : (
        <>
          <p className="muted">
            How often the judge disagrees with {data.reference_user_ids.map(email).join(', ')}{' '}
            (people currently in control), on every item they labeled, gold or not. The center line
            is the judge's own rate over its first {data.baseline_days} days, so this asks "did the
            judge change?" and works where gold is scarce.
          </p>
          <ControlChartView
            wording={AGREEMENT_WORDING}
            chart={{
              user_id: data.user_id,
              center: data.center,
              alerts: data.alerts,
              points: data.points.map((p) => ({
                day: p.day,
                gold_answered: p.compared,
                errors: p.disagreements,
                error_rate: p.disagreement_rate,
                ucl: p.ucl,
                lcl: p.lcl,
                model_version: p.model_version,
              })),
            }}
          />
          <h3>Alerts</h3>
          <AlertList
            key={`agreement-${labeler.user_id}`}
            projectId={projectId}
            userId={labeler.user_id}
            alerts={data.alerts}
            chart="agreement"
          />
        </>
      )}
    </>
  )
}

/** A chart's alerts. Each worse-than-target alert can open a ranked list of likely
 * causes; the latest one starts open. */
function AlertList({
  projectId,
  userId,
  alerts,
  chart,
}: {
  projectId: number
  userId: number
  alerts: Alert[]
  chart: ChartKind
}) {
  const latestUp = alerts.filter((a) => a.above).at(-1)?.day
  const [open, setOpen] = useState<Set<string>>(() => new Set(latestUp ? [latestUp] : []))
  const toggle = (day: string) =>
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(day)) next.delete(day)
      else next.add(day)
      return next
    })

  if (alerts.length === 0)
    return <p className="muted">None. Every day is within the control limits.</p>
  return (
    <ul className="alerts">
      {alerts.map((a) => (
        <li key={`${a.day}-${a.rule}`}>
          <strong>{a.day}</strong>: {a.description}
          {!a.above && <span className="muted"> (better than target)</span>}
          {a.above && (
            <button
              type="button"
              className="link"
              aria-expanded={open.has(a.day)}
              onClick={() => toggle(a.day)}
            >
              {open.has(a.day) ? 'Hide causes' : 'Why?'}
            </button>
          )}
          {a.above && open.has(a.day) && (
            <WhyPanel projectId={projectId} userId={userId} day={a.day} chart={chart} />
          )}
        </li>
      ))}
    </ul>
  )
}

function WhyPanel(props: { projectId: number; userId: number; day: string; chart: ChartKind }) {
  const { projectId, userId, day, chart } = props
  const result = useQuery({
    queryKey: ['root-cause', projectId, userId, day, chart],
    queryFn: () => api.rootCause(projectId, userId, day, chart),
  })
  return (
    <div className="why">
      <h4>Likely causes</h4>
      {result.isPending && <p className="muted">Ranking causes…</p>}
      {result.error && <p className="error">{result.error.message}</p>}
      {result.data && (
        <>
          <p className="muted">
            The shift since {result.data.run_start}: {percent(result.data.run_rate)} over{' '}
            {result.data.run_answers} answers, against {percent(result.data.expected_rate)}{' '}
            {result.data.compared_with === 'baseline'
              ? 'on the days before'
              : 'at the center line (no earlier baseline)'}
            .
          </p>
          <CauseList causes={result.data.causes} />
        </>
      )}
    </div>
  )
}

function AgreementCard({ quality }: { quality: ProjectQuality }) {
  const { agreement, labelers } = quality
  const email = (id: number) => labelers.find((l) => l.user_id === id)?.email ?? `#${id}`

  return (
    <section className="card">
      <h2>Agreement</h2>
      {agreement.overlap_items === 0 ? (
        <p className="muted">No overlap items have been labeled by several people yet.</p>
      ) : (
        <>
          <p>
            Fleiss' kappa <strong>{kappa(agreement.fleiss_kappa)}</strong>{' '}
            <span className="muted">
              over {agreement.overlap_items} items with {agreement.raters_per_item} labelers each. 1
              is perfect agreement; 0 is no better than chance.
            </span>
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Pair</th>
                  <th className="num">Shared items</th>
                  <th className="num">Cohen's kappa</th>
                </tr>
              </thead>
              <tbody>
                {agreement.pairs.map((p) => (
                  <tr key={`${p.user_a}-${p.user_b}`}>
                    <td>
                      {email(p.user_a)} and {email(p.user_b)}
                    </td>
                    <td className="num">{p.shared_items}</td>
                    <td className="num">{kappa(p.kappa)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
