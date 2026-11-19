import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Sample } from '../live'
import { mockApi, renderAt } from '../test/render'
import LivePage from './LivePage'

class FakeEventSource {
  static last: FakeEventSource
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {}
  onerror: (() => void) | null = null
  closed = false
  url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.last = this
  }
  addEventListener(name: string, fn: (e: MessageEvent) => void) {
    ;(this.listeners[name] ??= []).push(fn)
  }
  close() {
    this.closed = true
  }
  emit(name: string, data: unknown) {
    act(() => {
      for (const fn of this.listeners[name] ?? [])
        fn(new MessageEvent(name, { data: JSON.stringify(data) }))
    })
  }
}

const layout = {
  id: 'sess1',
  target_error_rate: 0.1,
  gold_per_sample: 20,
  baseline_samples: 2,
  labelers: ['avery', 'blake'],
  lines: ['L1'],
  metrics: [{ key: 'white_luminance', name: 'Center white luminance', unit: 'cd/m²' }],
}

function sample(n: number, events: Sample['events'] = []): Sample {
  const labeler = (name: string) => ({
    name,
    error_rate: 0.05,
    center: 0.1,
    ucl: 0.3,
    lcl: 0,
    signal: null,
    rule: null,
  })
  return {
    sample: n,
    labelers: [labeler('avery'), labeler('blake')],
    panel: [
      {
        line: 'L1',
        metric: 'white_luminance',
        mean: 350,
        baseline: n <= 2,
        center: 350,
        ucl: 356,
        lcl: 344,
        signal: null,
        rule: null,
      },
    ],
    events,
  }
}

describe('LivePage', () => {
  beforeEach(() => vi.stubGlobal('EventSource', FakeEventSource))
  afterEach(() => vi.unstubAllGlobals())

  it('draws the stream, sends a fault, and reports the detection', async () => {
    const fetchMock = mockApi({ 'POST /api/live/sess1/faults': () => ({ status: 204 }) })
    renderAt(<LivePage />, { route: '/' })
    const es = FakeEventSource.last
    expect(es.url).toBe('/api/live/stream')

    es.emit('session', layout)
    es.emit('history', [sample(1), sample(2), sample(3)])
    expect(screen.getByText('● Live · sample 3')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Avery control chart' })).toBeInTheDocument()

    await userEvent.click(screen.getAllByRole('button', { name: 'Make them rush' })[1])
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init?.body as string)).toEqual({ fault: 'rush', target: 'blake' })

    es.emit('sample', sample(4, [{ type: 'fault', fault: 'rush', target: 'blake' }]))
    expect(screen.getAllByRole('button', { name: 'Make them rush' })[1]).toBeDisabled()
    es.emit(
      'sample',
      sample(5, [
        {
          type: 'detected',
          fault: 'rush',
          chart: 'blake',
          samples: 1,
          description: 'One point beyond the 3-sigma limit',
        },
      ]),
    )
    expect(
      screen.getByText(/Caught on Blake after 1 sample: one point beyond the 3-sigma limit/),
    ).toBeInTheDocument()
  })

  it('ships the judge a model update and shows why the alarm fired', async () => {
    const fetchMock = mockApi({ 'POST /api/live/sess1/faults': () => ({ status: 204 }) })
    renderAt(<LivePage />, { route: '/' })
    const es = FakeEventSource.last
    es.emit('session', { ...layout, judge: 'judge', judge_version: 'judge-v1' })
    const withJudge = (n: number, events: Sample['events'] = []) => {
      const s = sample(n, events)
      return {
        ...s,
        labelers: [...s.labelers, { ...s.labelers[0], name: 'judge', version: 'judge-v1' }],
      }
    }
    es.emit('history', [withJudge(1), withJudge(2), withJudge(3)])
    expect(screen.getByRole('img', { name: 'LLM judge control chart' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Ship a model update' }))
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init?.body as string)).toEqual({ fault: 'model_update', target: 'judge' })

    es.emit('sample', withJudge(4, [{ type: 'fault', fault: 'model_update', target: 'judge' }]))
    expect(screen.getByRole('button', { name: 'Ship a model update' })).toBeDisabled()
    es.emit(
      'sample',
      withJudge(6, [
        {
          type: 'detected',
          fault: 'model_update',
          chart: 'judge',
          samples: 2,
          description: '2 of 3 points in a row beyond 2 sigma on one side',
          causes: [
            {
              kind: 'event',
              title: 'Model update: judge-v1 to judge-v2',
              explanation: 'Happened at sample 4, the sample the shift began.',
              score: 1,
            },
          ],
        },
      ]),
    )
    expect(screen.getByText(/Caught on LLM judge after 2 samples/)).toBeInTheDocument()
    expect(screen.getByText('Model update: judge-v1 to judge-v2')).toBeInTheDocument()
    expect(screen.getByText('Change at the onset')).toBeInTheDocument()
  })

  it('offers a new run when the stream ends', async () => {
    mockApi({})
    renderAt(<LivePage />, { route: '/' })
    const first = FakeEventSource.last
    first.emit('session', layout)
    first.emit('end', { reason: 'time limit' })
    expect(first.closed).toBe(true)

    await userEvent.click(screen.getByRole('button', { name: 'Start a new run' }))
    expect(FakeEventSource.last).not.toBe(first)
  })
})
