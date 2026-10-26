import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockApi, renderAt } from '../test/render'
import type { ReviewItem } from '../types'
import ReviewPage from './ReviewPage'

const item: ReviewItem = {
  id: 41,
  payload: { image_url: '/41.png' },
  reasons: ['disagreement', 'flagged_labeler'],
  labels: [
    { user_id: 1, email: 'a@x.dev', value: 'cat', flagged: false },
    { user_id: 2, email: 'b@x.dev', value: 'dog', flagged: true },
  ],
}

function renderReviewPage() {
  localStorage.setItem('gauge.token', 'test-token')
  let queue = [item]
  const resolved: unknown[] = []
  mockApi({
    'GET /api/auth/me': () => ({ body: { id: 9, email: 'r@x.dev', role: 'reviewer' } }),
    'GET /api/projects/7': () => ({
      body: {
        id: 7,
        name: 'Demo',
        task_type: 'image_classification',
        label_options: ['cat', 'dog'],
      },
    }),
    'GET /api/projects/7/review': () => ({ body: { total: queue.length, items: queue } }),
    'PUT /api/projects/7/items/41/resolution': (init) => {
      resolved.push(JSON.parse(String(init?.body)))
      queue = []
      return { body: {} }
    },
  })
  renderAt(<ReviewPage />, { path: '/projects/7/review', route: '/projects/:projectId/review' })
  return resolved
}

describe('ReviewPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows why an item needs review and who said what', async () => {
    renderReviewPage()
    expect(await screen.findByText('Labelers disagree')).toBeInTheDocument()
    expect(screen.getByText('Labeled while out of control')).toBeInTheDocument()
    expect(screen.getByText(/from b@x\.dev/).parentElement).toHaveTextContent(
      'out of control that day',
    )
  })

  it('resolves an item and drops it from the queue', async () => {
    const resolved = renderReviewPage()
    await userEvent.click(await screen.findByRole('button', { name: 'dog' }))
    await waitFor(() => expect(screen.getByText(/Nothing to review/)).toBeInTheDocument())
    expect(resolved).toEqual([{ value: 'dog' }])
  })
})
