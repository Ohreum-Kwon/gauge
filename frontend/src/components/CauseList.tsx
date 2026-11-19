import type { Cause } from '../types'

const KIND_LABEL: Record<Cause['kind'], string> = {
  event: 'Change at the onset',
  labeler: 'Labeler',
  concentration: 'Concentration',
}

/** Ranked likely causes of an alert, strongest first, each with its reason. */
export default function CauseList({
  causes,
  compact = false,
}: {
  causes: Cause[]
  compact?: boolean
}) {
  if (causes.length === 0)
    return (
      <p className="muted causes-none">
        No single cause stands out: no change right before the shift, no labeler or class
        concentration. That is what a chance alarm looks like.
      </p>
    )
  return (
    <ol className={`causes${compact ? ' compact' : ''}`}>
      {causes.map((c, i) => (
        <li key={`${c.kind}-${i}`}>
          <div className="cause-head">
            <span className="tag">{KIND_LABEL[c.kind]}</span>
            <strong>{c.title}</strong>
            <span
              className="cause-score"
              title="How much of the shift this explains, from 0 to 1"
              aria-label={`score ${c.score.toFixed(2)}`}
            >
              <span style={{ width: `${Math.round(c.score * 100)}%` }} />
            </span>
          </div>
          {!compact && <p className="muted">{c.explanation}</p>}
          {compact && <span className="muted"> {c.explanation}</span>}
        </li>
      ))}
    </ol>
  )
}
