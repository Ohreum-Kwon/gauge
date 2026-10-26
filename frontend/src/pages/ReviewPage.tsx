import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import ItemView from '../components/ItemView'
import type { ProjectSummary, ReviewItem } from '../types'

const REASONS: Record<ReviewItem['reasons'][number], string> = {
  disagreement: 'Labelers disagree',
  flagged_labeler: 'Labeled while out of control',
}

export default function ReviewPage() {
  const projectId = Number(useParams().projectId)
  const { user } = useAuth()
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.project(projectId),
  })
  const queue = useQuery({
    queryKey: ['review', projectId],
    queryFn: () => api.reviewQueue(projectId),
  })

  const error = project.error ?? queue.error
  if (error) return <p className="error">{error.message}</p>
  if (!project.data || !queue.data) return <p className="muted">Loading…</p>

  return (
    <>
      <Link to={user?.role === 'admin' ? `/projects/${projectId}` : '/projects'} className="muted">
        ← {project.data.name}
      </Link>
      <h1>Review queue</h1>
      {queue.data.total === 0 ? (
        <p className="muted">Nothing to review. Every item is agreed on or resolved.</p>
      ) : (
        <p className="muted">
          {queue.data.total} items need a decision
          {queue.data.total > queue.data.items.length &&
            `; showing the oldest ${queue.data.items.length}`}
          . Each has no clear answer from trusted labels; your choice becomes its final label.
        </p>
      )}
      <div className="review-list">
        {queue.data.items.map((item) => (
          <ReviewCard key={item.id} project={project.data} item={item} />
        ))}
      </div>
    </>
  )
}

function ReviewCard({ project, item }: { project: ProjectSummary; item: ReviewItem }) {
  const queryClient = useQueryClient()
  const resolve = useMutation({
    mutationFn: (value: string) => api.resolve(project.id, item.id, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['review', project.id] }),
  })

  return (
    <article className="card review-item" aria-label={`Item ${item.id}`}>
      <ItemView taskType={project.task_type} payload={item.payload} size="thumb" />
      <div className="stack">
        <div>
          <strong>#{item.id}</strong>{' '}
          {item.reasons.map((r) => (
            <span key={r} className="tag">
              {REASONS[r]}
            </span>
          ))}
        </div>
        <ul>
          {item.labels.map((label) => (
            <li key={label.user_id}>
              <strong>{label.value}</strong> <span className="muted">from {label.email}</span>
              {label.flagged && <span className="flagged"> · out of control that day</span>}
            </li>
          ))}
        </ul>
        <div className="links" role="group" aria-label="Final label">
          {project.label_options.map((option) => (
            <button
              key={option}
              type="button"
              className="secondary"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate(option)}
            >
              {option}
            </button>
          ))}
        </div>
        {resolve.error && <p className="error">{resolve.error.message}</p>}
      </div>
    </article>
  )
}
