// The live demo's stream (backend/app/live.py and routers/live.py), as a React hook.
import { useCallback, useEffect, useReducer, useRef } from 'react'
import { api } from './api'

export type Signal = 'alarm' | 'warning' | null
export type FaultKind = 'drift' | 'rush' | 'backlight' | 'tft_lot' | 'model_update'

/** A likely cause of an alarm, ranked by the server (app/rootcause.py). */
export interface LiveCause {
  kind: 'event' | 'labeler' | 'concentration'
  title: string
  explanation: string
  score: number
}

export interface LabelerSample {
  name: string
  error_rate: number
  center: number
  ucl: number
  lcl: number
  signal: Signal
  rule: string | null
  /** The judge's model version; null for people. */
  version?: string | null
}

export interface PanelSample {
  line: string
  metric: string
  mean: number
  baseline: boolean
  center?: number
  ucl?: number
  lcl?: number
  signal: Signal
  rule: string | null
}

export type LiveEvent =
  | { type: 'fault'; fault: FaultKind; target: string }
  | { type: 'cleared'; fault: FaultKind; target: string }
  | { type: 'reset' }
  | {
      type: 'detected'
      fault: FaultKind
      chart: string
      samples: number
      description: string
      causes?: LiveCause[]
    }
  | { type: 'false_alarm'; chart: string; description: string; causes?: LiveCause[] }

export interface Sample {
  sample: number
  labelers: LabelerSample[]
  panel: PanelSample[]
  events: LiveEvent[]
}

export interface Layout {
  id: string
  target_error_rate: number
  baseline_samples: number
  labelers: string[]
  /** The simulated LLM judge's chart name, and the version it starts on. */
  judge?: string
  judge_version?: string
  lines: string[]
  metrics: { key: string; name: string; unit: string }[]
}

export interface LogEntry {
  sample: number
  event: LiveEvent
}

export type Status = 'connecting' | 'live' | 'ended' | 'error'

const WINDOW = 60 // samples kept on screen

/** The chart a fault shows up on: a labeler's p-chart, or one metric of a line. */
export function faultChart(fault: FaultKind, target: string): string {
  if (fault === 'backlight') return `${target}:white_luminance`
  if (fault === 'tft_lot') return `${target}:tft_vth`
  return target
}

interface State {
  status: Status
  layout: Layout | null
  samples: Sample[]
  log: LogEntry[]
  /** Chart id → sample its fault started, for shading. */
  activeFaults: Record<string, number>
}

type Action =
  | { type: 'connect' }
  | { type: 'session'; layout: Layout }
  | { type: 'samples'; samples: Sample[] }
  | { type: 'status'; status: Status }

const initial: State = {
  status: 'connecting',
  layout: null,
  samples: [],
  log: [],
  activeFaults: {},
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'connect':
      return initial
    case 'session':
      return { ...state, layout: action.layout }
    case 'status':
      return { ...state, status: action.status }
    case 'samples': {
      let { log, activeFaults } = state
      for (const s of action.samples) {
        for (const event of s.events) {
          log = [{ sample: s.sample, event }, ...log].slice(0, 50)
          if (event.type === 'fault')
            activeFaults = { ...activeFaults, [faultChart(event.fault, event.target)]: s.sample }
          if (event.type === 'cleared') {
            const { [faultChart(event.fault, event.target)]: _, ...rest } = activeFaults
            activeFaults = rest
          }
          if (event.type === 'reset') activeFaults = {}
        }
      }
      return {
        ...state,
        status: 'live',
        samples: [...state.samples, ...action.samples].slice(-WINDOW),
        log,
        activeFaults,
      }
    }
  }
}

export function useLiveDemo() {
  const [state, dispatch] = useReducer(reducer, initial)
  const source = useRef<EventSource | null>(null)

  const connect = useCallback(() => {
    source.current?.close()
    dispatch({ type: 'connect' })
    const es = new EventSource(`${api.baseUrl}/api/live/stream`)
    source.current = es
    const data = (e: Event) => JSON.parse((e as MessageEvent).data)
    es.addEventListener('session', (e) => dispatch({ type: 'session', layout: data(e) }))
    es.addEventListener('history', (e) => dispatch({ type: 'samples', samples: data(e) }))
    es.addEventListener('sample', (e) => dispatch({ type: 'samples', samples: [data(e)] }))
    es.addEventListener('end', () => {
      es.close()
      dispatch({ type: 'status', status: 'ended' })
    })
    // EventSource would reconnect on its own, into a new session; start over explicitly.
    es.onerror = () => {
      es.close()
      dispatch({ type: 'status', status: 'error' })
    }
  }, [])

  useEffect(() => {
    connect()
    return () => source.current?.close()
  }, [connect])

  const sessionId = state.layout?.id
  const send = useCallback(
    async (body: { fault: FaultKind; target: string } | { fault: 'reset' }) => {
      if (sessionId) await api.liveFault(sessionId, body)
    },
    [sessionId],
  )

  return { ...state, restart: connect, send }
}
