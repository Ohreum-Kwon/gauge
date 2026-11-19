import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockApi, renderAt } from '../test/render'
import type { LabelerQuality, ProjectQuality } from '../types'
import QualityPage from './QualityPage'

const labeler = (id: number, overrides: Partial<LabelerQuality> = {}): LabelerQuality => ({
  user_id: id,
  email: `labeler${id}@x.dev`,
  labels: 100,
  gold_answered: 20,
  gold_correct: 19,
  accuracy: 0.95,
  median_time_ms: 2400,
  fast_share: 0,
  status: 'in_control',
  latest_alert: null,
  is_model: false,
  model_version: null,
  ...overrides,
})

const quality: ProjectQuality = {
  target_error_rate: 0.1,
  labelers: [
    labeler(1),
    labeler(2, {
      status: 'out_of_control',
      accuracy: 0.6,
      latest_alert: {
        day: '2026-10-06',
        rule: 'rule_1',
        description: 'A point beyond the 3-sigma limit',
        above: true,
      },
    }),
  ],
  agreement: {
    fleiss_kappa: 0.61,
    overlap_items: 12,
    raters_per_item: 2,
    pairs: [{ user_a: 1, user_b: 2, kappa: 0.61, shared_items: 12 }],
  },
}

function renderQualityPage() {
  localStorage.setItem('gauge.token', 'test-token')
  const chartRequests: string[] = []
  const chart = (userId: number) => () => {
    chartRequests.push(String(userId))
    return {
      body: {
        user_id: userId,
        center: 0.1,
        points: [
          { day: '2026-10-06', gold_answered: 20, errors: 8, error_rate: 0.4, ucl: 0.3, lcl: 0 },
        ],
        alerts:
          userId === 2
            ? [{ day: '2026-10-06', rule: 'rule_1', description: 'Beyond the limit', above: true }]
            : [],
      },
    }
  }
  mockApi({
    'GET /api/auth/me': () => ({ body: { id: 9, email: 'r@x.dev', role: 'reviewer' } }),
    'GET /api/projects/7': () => ({ body: { id: 7, name: 'Demo' } }),
    'GET /api/projects/7/quality': () => ({ body: quality }),
    'GET /api/projects/7/quality/labelers/1/chart': chart(1),
    'GET /api/projects/7/quality/labelers/2/chart': chart(2),
    'GET /api/projects/7/quality/labelers/2/root-cause': () => ({
      body: {
        user_id: 2,
        chart: 'gold',
        alert_day: '2026-10-06',
        run_start: '2026-10-06',
        compared_with: 'baseline',
        run_answers: 20,
        run_rate: 0.4,
        expected_rate: 0.05,
        extra_errors: 7,
        causes: [
          {
            kind: 'labeler',
            title: 'Only labeler2@x.dev changed',
            explanation: 'labeler2@x.dev went from 5% to 40%.',
            score: 1,
          },
        ],
      },
    }),
  })
  renderAt(<QualityPage />, { path: '/projects/7/quality', route: '/projects/:projectId/quality' })
  return chartRequests
}

describe('QualityPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists labelers with a status in words, not color alone', async () => {
    renderQualityPage()
    const rows = await screen.findAllByRole('row')
    expect(within(rows[1]).getByText('In control')).toBeInTheDocument()
    expect(within(rows[2]).getByText('Out of control')).toBeInTheDocument()
    expect(within(rows[2]).getByText(/beyond the 3-sigma limit/)).toBeInTheDocument()
  })

  it('opens on the out-of-control labeler, and switches when another is picked', async () => {
    const chartRequests = renderQualityPage()
    expect(await screen.findByRole('heading', { name: 'labeler2@x.dev' })).toBeInTheDocument()
    expect(await screen.findByText(/Beyond the limit/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'labeler1@x.dev' }))
    expect(await screen.findByRole('heading', { name: 'labeler1@x.dev' })).toBeInTheDocument()
    expect(await screen.findByText(/None\. Every day is within/)).toBeInTheDocument()
    expect(chartRequests).toEqual(['2', '1'])
  })

  it('opens the latest alert with its likely causes, and folds it away', async () => {
    renderQualityPage()
    expect(await screen.findByText('Only labeler2@x.dev changed')).toBeInTheDocument()
    expect(screen.getByText(/went from 5% to 40%/)).toBeInTheDocument()
    expect(
      screen.getByText(/40% over 20 answers, against 5% on the days before/),
    ).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Hide causes' }))
    expect(screen.queryByText('Only labeler2@x.dev changed')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Why?' })).toBeInTheDocument()
  })

  it('shows a model labeler with its version and its agreement chart', async () => {
    localStorage.setItem('gauge.token', 'test-token')
    const judge = labeler(5, { email: 'judge@x.dev', is_model: true, model_version: 'v2' })
    const point = { day: '2026-10-06', ucl: 0.3, lcl: 0, model_version: 'v2' }
    mockApi({
      'GET /api/auth/me': () => ({ body: { id: 9, email: 'r@x.dev', role: 'reviewer' } }),
      'GET /api/projects/7': () => ({ body: { id: 7, name: 'Demo' } }),
      'GET /api/projects/7/quality': () => ({
        body: { ...quality, labelers: [labeler(1), judge] },
      }),
      'GET /api/projects/7/quality/labelers/5/chart': () => ({
        body: {
          user_id: 5,
          center: 0.1,
          points: [{ ...point, gold_answered: 40, errors: 2, error_rate: 0.05 }],
          alerts: [],
        },
      }),
      'GET /api/projects/7/quality/labelers/5/agreement-chart': () => ({
        body: {
          user_id: 5,
          center: 0.09,
          baseline_days: 3,
          reference_user_ids: [1],
          points: [{ ...point, compared: 90, disagreements: 9, disagreement_rate: 0.1 }],
          alerts: [],
        },
      }),
    })
    renderAt(<QualityPage />, {
      path: '/projects/7/quality?labeler=judge@x.dev',
      route: '/projects/:projectId/quality',
    })
    expect(await screen.findByRole('heading', { name: /judge@x\.dev/ })).toBeInTheDocument()
    expect(screen.getAllByText('Model · v2').length).toBeGreaterThan(0)
    expect(await screen.findByText('Disagreement with people')).toBeInTheDocument()
    expect(screen.getByText(/disagrees with labeler1@x\.dev/)).toBeInTheDocument()
  })

  it('shows agreement between labelers', async () => {
    renderQualityPage()
    expect(await screen.findByText(/over 12 items with 2 labelers each/)).toBeInTheDocument()
    expect(screen.getByText('labeler1@x.dev and labeler2@x.dev')).toBeInTheDocument()
  })
})
