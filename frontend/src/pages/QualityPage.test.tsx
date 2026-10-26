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

  it('shows agreement between labelers', async () => {
    renderQualityPage()
    expect(await screen.findByText(/over 12 items with 2 labelers each/)).toBeInTheDocument()
    expect(screen.getByText('labeler1@x.dev and labeler2@x.dev')).toBeInTheDocument()
  })
})
