import type { Signal } from '../live'

export interface LivePoint {
  sample: number
  value: number
  signal: Signal
  baseline?: boolean
}

interface Props {
  title: string
  subtitle: string
  points: LivePoint[]
  window: number
  center?: number
  ucl?: number
  lcl?: number
  /** Fixed y range; otherwise fitted to the points and limits. */
  domain?: [number, number]
  format: (v: number) => string
  /** Sample at which an injected fault started, shaded from there on. */
  faultSince?: number
  alarm: boolean
}

const W = 420
const H = 150
const PAD = { left: 48, right: 10, top: 10, bottom: 18 }

/** A small control chart for a streaming series: plain SVG, redrawn every sample. */
export default function LiveChart(props: Props) {
  const { points, window, center, ucl, lcl, format, faultSince } = props
  const last = points.at(-1)?.sample ?? window
  const first = last - window + 1
  const x = (sample: number) =>
    PAD.left + ((sample - first) / (window - 1)) * (W - PAD.left - PAD.right)

  let [lo, hi] = props.domain ?? [Infinity, -Infinity]
  if (!props.domain) {
    for (const v of [...points.map((p) => p.value), center, ucl, lcl])
      if (v !== undefined) [lo, hi] = [Math.min(lo, v), Math.max(hi, v)]
    const pad = (hi - lo) * 0.12 || 1
    ;[lo, hi] = [lo - pad, hi + pad]
  }
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom)
  const visible = points.filter((p) => p.sample >= first)
  const path = visible.map((p, i) => `${i ? 'L' : 'M'}${x(p.sample)},${y(p.value)}`).join(' ')
  const baselineEnd = visible.filter((p) => p.baseline).at(-1)?.sample
  const hline = (v: number, cls: string, label: string) => (
    <g>
      <line className={cls} x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} />
      <text className="live-tick" x={PAD.left - 4} y={y(v) + 3} textAnchor="end">
        {label}
      </text>
    </g>
  )

  return (
    <figure className={`live-chart card${props.alarm ? ' alarming' : ''}`}>
      <figcaption>
        <strong>{props.title}</strong> <span className="muted">{props.subtitle}</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${props.title} control chart`}>
        {baselineEnd !== undefined && (
          <rect
            className="live-baseline"
            x={PAD.left}
            y={PAD.top}
            width={Math.max(0, x(baselineEnd) - PAD.left)}
            height={H - PAD.top - PAD.bottom}
          />
        )}
        {faultSince !== undefined && (
          <rect
            className="live-fault"
            x={Math.max(PAD.left, x(faultSince - 0.5))}
            y={PAD.top}
            width={W - PAD.right - Math.max(PAD.left, x(faultSince - 0.5))}
            height={H - PAD.top - PAD.bottom}
          />
        )}
        {center !== undefined && hline(center, 'live-center', format(center))}
        {ucl !== undefined && hline(ucl, 'live-limit', format(ucl))}
        {lcl !== undefined && lcl > lo && hline(lcl, 'live-limit', format(lcl))}
        <path className="live-series" d={path} />
        {visible.map((p) => (
          <circle
            key={p.sample}
            className={`live-point ${p.signal ?? ''}`}
            cx={x(p.sample)}
            cy={y(p.value)}
            r={p.signal ? 3.5 : 2}
          />
        ))}
        <text className="live-tick" x={W - PAD.right} y={H - 4} textAnchor="end">
          sample {last}
        </text>
      </svg>
    </figure>
  )
}
