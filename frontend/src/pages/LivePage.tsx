import { useState } from 'react'
import { Link } from 'react-router-dom'
import CauseList from '../components/CauseList'
import LiveChart, { type LivePoint } from '../components/LiveChart'
import { faultChart, useLiveDemo, type FaultKind, type LiveEvent, type Sample } from '../live'

const WINDOW = 60
const REPO = 'https://github.com/Ohreum-Kwon/gauge'

const title = (name: string) =>
  name === 'judge' ? 'LLM judge' : name[0].toUpperCase() + name.slice(1)
const percent = (v: number) => `${Math.round(v * 100)}%`

const METRIC_FORMAT: Record<string, (v: number) => string> = {
  white_luminance: (v) => v.toFixed(0),
  tft_vth: (v) => v.toFixed(2),
}
const LINE_FAULT_FOR: Record<string, { fault: FaultKind; label: string }> = {
  white_luminance: { fault: 'backlight', label: 'Age the backlight' },
  tft_vth: { fault: 'tft_lot', label: 'Use a bad TFT lot' },
}

function chartName(chart: string): string {
  const [line, metric] = chart.split(':')
  if (!metric) return title(line)
  return `${line} ${metric === 'tft_vth' ? 'TFT threshold voltage' : 'luminance'}`
}

function describe(event: LiveEvent): { text: string; tone: string } {
  switch (event.type) {
    case 'fault':
      return {
        tone: 'fault',
        text: {
          drift: `You made ${title(event.target)} start drifting.`,
          rush: `You made ${title(event.target)} start rushing.`,
          backlight: `You started ageing ${event.target}'s backlights.`,
          tft_lot: `${event.target} is now building from a bad TFT lot.`,
          model_update: 'You shipped the LLM judge a quiet model update (judge-v2).',
        }[event.fault],
      }
    case 'detected':
      return {
        tone: 'caught',
        text: `Caught on ${chartName(event.chart)} after ${plural(event.samples, 'sample')}: ${event.description.toLowerCase()}.`,
      }
    case 'false_alarm':
      return {
        tone: 'false',
        text: `False alarm on ${chartName(event.chart)}: ${event.description.toLowerCase()}, with no fault. A 3σ limit is crossed by chance about once in 370 points.`,
      }
    case 'cleared':
      return { tone: 'info', text: `${event.target}'s bad TFT lot ran out.` }
    case 'reset':
      return {
        tone: 'info',
        text: 'Everything reset: labelers retrained, the judge rolled back, backlights replaced.',
      }
  }
}

export default function LivePage() {
  const live = useLiveDemo()
  const [error, setError] = useState<string | null>(null)
  const { layout, samples, log, activeFaults } = live
  const latest = samples.at(-1)

  async function send(body: Parameters<typeof live.send>[0]) {
    setError(null)
    try {
      await live.send(body)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work')
    }
  }

  const faults = log.filter((l) => l.event.type === 'fault').length
  const caught = log.flatMap((l) => (l.event.type === 'detected' ? [l.event.samples] : []))
  const falseAlarms = log.filter((l) => l.event.type === 'false_alarm').length

  return (
    <div className="landing live">
      <header className="landing-nav">
        <Link to="/" className="brand">
          Gauge
        </Link>
        <a href={`${REPO}#live-demo`}>How it works</a>
        <a href={REPO}>GitHub</a>
      </header>

      <div className="live-head">
        <div>
          <h1>Break it yourself</h1>
          <p className="lede">
            A private copy of Gauge is running just for you: three labelers and an LLM judge
            answering gold questions, and a display line testing five panels, one sample a second.
            Inject a fault and watch the control charts catch it, and Gauge explain why.
          </p>
        </div>
        <StatusPill status={live.status} sample={latest?.sample} restart={live.restart} />
      </div>

      <div className="live-score card">
        <Stat label="Faults injected" value={faults} />
        <Stat label="Caught" value={caught.length} />
        <Stat
          label="Median delay"
          value={caught.length ? plural(median(caught), 'sample') : '–'}
          hint="from the first faulty sample to the alarm"
        />
        <Stat label="False alarms" value={falseAlarms} hint="alarms with no fault active" />
        <button
          type="button"
          className="secondary"
          disabled={!layout || live.status !== 'live'}
          onClick={() => void send({ fault: 'reset' })}
        >
          Reset everything
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {layout && (
        <div className="live-grid">
          <section>
            <h2>Labelers</h2>
            <p className="muted">
              Error rate on 20 gold answers per sample, against a{' '}
              {percent(layout.target_error_rate)} target.
            </p>
            {layout.labelers.map((name) => (
              <div key={name}>
                <LiveChart
                  title={title(name)}
                  subtitle="gold error rate"
                  points={labelerPoints(samples, name)}
                  window={WINDOW}
                  {...limitsOf(latest?.labelers.find((l) => l.name === name))}
                  domain={[0, errorRateTop(samples)]}
                  format={percent}
                  faultSince={activeFaults[name]}
                  alarm={latest?.labelers.find((l) => l.name === name)?.signal === 'alarm'}
                />
                <div className="live-actions">
                  {(['drift', 'rush'] as const).map((fault) => (
                    <button
                      key={fault}
                      type="button"
                      className="secondary"
                      disabled={live.status !== 'live' || name in activeFaults}
                      onClick={() => void send({ fault, target: name })}
                    >
                      {fault === 'drift' ? 'Make them drift' : 'Make them rush'}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {layout.judge && (
              <JudgeChart
                name={layout.judge}
                samples={samples}
                targetTop={errorRateTop(samples)}
                faultSince={activeFaults[layout.judge]}
                disabled={live.status !== 'live' || layout.judge in activeFaults}
                onShip={() => void send({ fault: 'model_update', target: layout.judge! })}
              />
            )}
          </section>

          <section>
            {layout.lines.map((line) => (
              <div key={line}>
                <h2>Panel line {line}</h2>
                <p className="muted">
                  X̄ of five panels per sample. Limits come from the first {layout.baseline_samples}{' '}
                  samples (shaded).
                </p>
                {layout.metrics.map((metric) => {
                  const chart = `${line}:${metric.key}`
                  const current = latest?.panel.find(
                    (p) => p.line === line && p.metric === metric.key,
                  )
                  const action = LINE_FAULT_FOR[metric.key]
                  return (
                    <div key={metric.key}>
                      <LiveChart
                        title={metric.name}
                        subtitle={metric.unit}
                        points={panelPoints(samples, line, metric.key)}
                        window={WINDOW}
                        {...limitsOf(current)}
                        format={METRIC_FORMAT[metric.key] ?? ((v) => v.toFixed(2))}
                        faultSince={activeFaults[chart]}
                        alarm={current?.signal === 'alarm'}
                      />
                      <div className="live-actions">
                        <button
                          type="button"
                          className="secondary"
                          disabled={
                            live.status !== 'live' || faultChart(action.fault, line) in activeFaults
                          }
                          onClick={() => void send({ fault: action.fault, target: line })}
                        >
                          {action.label}
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            ))}

            <h2>What happened</h2>
            <ol className="live-log" aria-live="polite">
              {log.length === 0 && <li className="muted">Nothing yet. Try one of the buttons.</li>}
              {log.map(({ sample, event }, i) => {
                const { text, tone } = describe(event)
                const causes =
                  event.type === 'detected' || event.type === 'false_alarm'
                    ? event.causes
                    : undefined
                return (
                  <li key={`${sample}-${i}`} className={`tone-${tone}`}>
                    <span className="muted">#{sample}</span> {text}
                    {causes && <CauseList causes={causes} compact />}
                  </li>
                )
              })}
            </ol>
          </section>
        </div>
      )}
    </div>
  )
}

function JudgeChart(props: {
  name: string
  samples: Sample[]
  targetTop: number
  faultSince?: number
  disabled: boolean
  onShip: () => void
}) {
  const current = props.samples.at(-1)?.labelers.find((l) => l.name === props.name)
  return (
    <div>
      <LiveChart
        title="LLM judge"
        subtitle={`gold error rate · ${current?.version ?? 'judge-v1'}`}
        points={labelerPoints(props.samples, props.name)}
        window={WINDOW}
        {...limitsOf(current)}
        domain={[0, props.targetTop]}
        format={percent}
        faultSince={props.faultSince}
        alarm={current?.signal === 'alarm'}
      />
      <div className="live-actions">
        <button
          type="button"
          className="secondary"
          disabled={props.disabled}
          onClick={props.onShip}
        >
          Ship a model update
        </button>
      </div>
    </div>
  )
}

function StatusPill(props: { status: string; sample?: number; restart: () => void }) {
  if (props.status === 'live')
    return <p className="server-status ready">● Live · sample {props.sample}</p>
  if (props.status === 'connecting') return <p className="server-status waking">● Connecting…</p>
  return (
    <p className="server-status down">
      ● {props.status === 'ended' ? 'This run has ended.' : 'Disconnected.'}{' '}
      <button type="button" className="link" onClick={props.restart}>
        Start a new run
      </button>
    </p>
  )
}

function Stat(props: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="stat" title={props.hint}>
      <span className="stat-value">{props.value}</span>
      <span className="muted">{props.label}</span>
    </div>
  )
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.floor(sorted.length / 2)]
}

function limitsOf(point?: { center?: number; ucl?: number; lcl?: number }) {
  return { center: point?.center, ucl: point?.ucl, lcl: point?.lcl }
}

function labelerPoints(samples: Sample[], name: string): LivePoint[] {
  return samples.flatMap((s) => {
    const l = s.labelers.find((x) => x.name === name)
    return l ? [{ sample: s.sample, value: l.error_rate, signal: l.signal }] : []
  })
}

function panelPoints(samples: Sample[], line: string, metric: string): LivePoint[] {
  return samples.flatMap((s) => {
    const p = s.panel.find((x) => x.line === line && x.metric === metric)
    return p ? [{ sample: s.sample, value: p.mean, signal: p.signal, baseline: p.baseline }] : []
  })
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** Room for a 30% limit when everyone is healthy; grows when someone starts rushing. */
function errorRateTop(samples: Sample[]): number {
  const worst = Math.max(0, ...samples.flatMap((s) => s.labelers.map((l) => l.error_rate)))
  return Math.min(1, Math.max(0.45, worst + 0.08))
}
