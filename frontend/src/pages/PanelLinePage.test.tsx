import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockApi, renderAt } from '../test/render'
import type { PanelChart, PanelLineSummary, PanelMetric, PanelSeriesSummary } from '../types'
import PanelLinePage from './PanelLinePage'

const luminance: PanelMetric = {
  key: 'white_luminance',
  name: 'Center white luminance',
  unit: 'cd/m²',
  group: 'optical',
  target: 350,
  lsl: 320,
  usl: 380,
}
const vth: PanelMetric = {
  key: 'tft_vth',
  name: 'TFT threshold voltage',
  unit: 'V',
  group: 'electrical',
  target: 1,
  lsl: 0.7,
  usl: 1.3,
}

const alarm = (subgroup: number) => ({
  subgroup,
  measured_at: '2026-10-31T00:00:00Z',
  rule: 'beyond_3_sigma',
  description: 'One point beyond the 3-sigma limit',
  severity: 'alarm' as const,
  above: false,
})

const cell = (line: string, metric: string, overrides: Partial<PanelSeriesSummary> = {}) => ({
  line,
  metric,
  status: 'in_control' as const,
  first_warning: null,
  first_alarm: null,
  signals: 0,
  latest_mean: 1,
  baseline_cpk: 2,
  recent_cpk: 2,
  ...overrides,
})

const summary: PanelLineSummary = {
  baseline_subgroups: 2,
  lines: ['L1', 'L2'],
  metrics: [luminance, vth],
  series: [
    cell('L1', 'white_luminance'),
    cell('L1', 'tft_vth', { status: 'warning' }),
    cell('L2', 'white_luminance', {
      status: 'out_of_control',
      first_alarm: alarm(3),
      baseline_cpk: 1.92,
      recent_cpk: 0.97,
    }),
    cell('L2', 'tft_vth'),
  ],
}

function chartFor(line: string, metric: PanelMetric, alarmed: boolean): PanelChart {
  const point = (subgroup: number, mean: number) => ({
    subgroup,
    measured_at: `2026-10-${28 + subgroup}T00:00:00Z`,
    lot: 'T-2504',
    mean,
    range: 4,
    z: 0,
    ewma: mean,
    ewma_ucl: 355,
    ewma_lcl: 345,
  })
  const capability = {
    mean: 350,
    sigma_within: 4,
    sigma_overall: 4,
    cp: 2.5,
    cpk: 2.4,
    pp: 2.5,
    ppk: 2.4,
  }
  return {
    line,
    metric,
    status: alarmed ? 'out_of_control' : 'in_control',
    baseline_subgroups: 2,
    subgroup_size: 5,
    center: 350,
    xbar_ucl: 356,
    xbar_lcl: 344,
    r_center: 4,
    r_ucl: 8,
    r_lcl: 0,
    points: [point(0, 350), point(1, 351), point(2, 348), point(3, 340)],
    signals: alarmed ? [alarm(3)] : [],
    baseline_capability: capability,
    recent_capability: { ...capability, cpk: 0.97 },
  }
}

function renderPage(body: PanelLineSummary = summary) {
  localStorage.setItem('gauge.token', 'test-token')
  const requested: string[] = []
  const chart = (line: string, metric: PanelMetric) => () => {
    requested.push(`${line}/${metric.key}`)
    return { body: chartFor(line, metric, line === 'L2' && metric.key === 'white_luminance') }
  }
  mockApi({
    'GET /api/auth/me': () => ({ body: { id: 9, email: 'r@x.dev', role: 'reviewer' } }),
    'GET /api/panel-line': () => ({ body }),
    'GET /api/panel-line/lines/L1/metrics/white_luminance': chart('L1', luminance),
    'GET /api/panel-line/lines/L2/metrics/white_luminance': chart('L2', luminance),
    'GET /api/panel-line/lines/L1/metrics/tft_vth': chart('L1', vth),
  })
  renderAt(<PanelLinePage />, { path: '/panel-line', route: '/panel-line' })
  return requested
}

describe('PanelLinePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows every line and metric with a status in words and the Cpk trend', async () => {
    renderPage()
    const cellButton = await screen.findByRole('button', {
      name: 'Center white luminance, line L2',
    })
    expect(within(cellButton).getByText('Out of control')).toBeInTheDocument()
    expect(within(cellButton).getByText('Cpk 1.92 → 0.97')).toBeInTheDocument()
    const warned = screen.getByRole('button', { name: 'TFT threshold voltage, line L1' })
    expect(within(warned).getByText('Warning')).toBeInTheDocument()
    expect(screen.getByText('320 to 380 cd/m²', { selector: 'td' })).toBeInTheDocument()
  })

  it('opens on the earliest alarm and switches when another cell is picked', async () => {
    const requested = renderPage()
    expect(
      await screen.findByRole('heading', { name: 'Center white luminance, line L2' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByText(/One point beyond the 3-sigma limit/, { selector: 'li' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/low, lot T-2504/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'TFT threshold voltage, line L1' }))
    expect(
      await screen.findByRole('heading', { name: 'TFT threshold voltage, line L1' }),
    ).toBeInTheDocument()
    expect(await screen.findByText(/None\. Every subgroup is within/)).toBeInTheDocument()
    expect(requested).toEqual(['L2/white_luminance', 'L1/tft_vth'])
  })

  it('explains how to get data when there is none', async () => {
    renderPage({ ...summary, lines: [], series: [] })
    expect(await screen.findByText(/python -m app.panel_sim/)).toBeInTheDocument()
  })
})
