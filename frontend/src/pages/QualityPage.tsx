import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import ControlChartView from '../components/ControlChartView'
import StatusBadge from '../components/StatusBadge'
import { kappa, percent, seconds } from '../format'
import type { LabelerQuality, ProjectQuality } from '../types'

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

  if (quality.isPending) return <p className="muted">Loading…</p>
  if (quality.error) return <p className="error">{quality.error.message}</p>

  const { labelers } = quality.data
  // Until someone picks a row, show the labeler most in need of attention.
  const selected =
    labelers.find((l) => l.user_id === selectedId) ??
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
        labeler to see their control chart.
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
      <h2>{labeler.email}</h2>
      {chart.isPending && <p className="muted">Loading chart…</p>}
      {chart.error && <p className="error">{chart.error.message}</p>}
      {chart.data && chart.data.points.length === 0 && (
        <p className="muted">No gold answers yet, so there is nothing to chart.</p>
      )}
      {chart.data && chart.data.points.length > 0 && (
        <>
          <ControlChartView chart={chart.data} />
          <h3>Alerts</h3>
          {chart.data.alerts.length === 0 ? (
            <p className="muted">None. Every day is within the control limits.</p>
          ) : (
            <ul className="alerts">
              {chart.data.alerts.map((a) => (
                <li key={`${a.day}-${a.rule}`}>
                  <strong>{a.day}</strong>: {a.description}
                  {!a.above && <span className="muted"> (better than target)</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
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
