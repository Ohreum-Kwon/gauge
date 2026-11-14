// The drift demo in one picture: a labeler's daily gold error rate on a p-chart. The
// numbers are the simulated drifter's (95% accurate for five days, then 60%), drawn by hand so
// the landing page needs neither the API nor the charting library.
const DAYS = [0.05, 0.05, 0.02, 0.12, 0.11, 0.38, 0.37, 0.44]
const TARGET = 0.1
const UCL = 0.29

const W = 360
const H = 220
const PAD = { left: 40, right: 24, top: 16, bottom: 30 }
const MAX = 0.5

const x = (i: number) => PAD.left + (i * (W - PAD.left - PAD.right)) / (DAYS.length - 1)
const y = (rate: number) => PAD.top + (1 - rate / MAX) * (H - PAD.top - PAD.bottom)

export default function DriftIllustration() {
  const path = DAYS.map((rate, i) => `${i ? 'L' : 'M'}${x(i)},${y(rate)}`).join(' ')
  return (
    <figure className="drift card">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="A labeler's daily error rate stays near or below 12% for five days, then jumps to about 40% on day 6, above the 3-sigma control limit, and is flagged."
      >
        {[0, 0.1, 0.2, 0.3, 0.4, 0.5].map((t) => (
          <g key={t}>
            <line className="grid" x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
            <text className="tick" x={PAD.left - 6} y={y(t) + 4} textAnchor="end">
              {t * 100}%
            </text>
          </g>
        ))}
        {DAYS.map((_, i) => (
          <text key={i} className="tick" x={x(i)} y={H - 10} textAnchor="middle">
            Day {i + 1}
          </text>
        ))}
        <line className="target" x1={PAD.left} x2={W - PAD.right} y1={y(TARGET)} y2={y(TARGET)} />
        <line className="limit" x1={PAD.left} x2={W - PAD.right} y1={y(UCL)} y2={y(UCL)} />
        <text className="limit-label" x={PAD.left + 4} y={y(UCL) - 5}>
          3σ limit
        </text>
        <path className="series" d={path} pathLength={1} />
        {DAYS.map((rate, i) => (
          <circle
            key={i}
            className={rate > UCL ? 'point alarm' : 'point'}
            cx={x(i)}
            cy={y(rate)}
            r={rate > UCL ? 5 : 3.5}
            style={{ animationDelay: `${0.25 + i * 0.25}s` }}
          />
        ))}
        <g className="callout" style={{ animationDelay: '2s' }}>
          <rect x={x(5) - 128} y={y(0.38) - 12} width={118} height={24} rx={4} />
          <text x={x(5) - 69} y={y(0.38) + 4} textAnchor="middle">
            Out of control
          </text>
        </g>
      </svg>
      <figcaption className="muted">
        The drift demo: a simulated labeler's daily error on gold questions, against a 10% target.
      </figcaption>
    </figure>
  )
}
