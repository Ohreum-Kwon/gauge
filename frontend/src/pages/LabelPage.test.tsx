import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockApi, renderAt } from '../test/render'
import type { Task } from '../types'
import LabelPage from './LabelPage'

const task = (assignmentId: number): Task => ({
  assignment_id: assignmentId,
  project_id: 7,
  task_type: 'image_classification',
  label_options: ['cat', 'dog', 'bird'],
  item: { id: 100 + assignmentId, payload: { image_url: `/img/${assignmentId}.png` } },
})

function renderLabelPage(tasks: (Task | null)[]) {
  localStorage.setItem('gauge.token', 'test-token')
  const queue = [...tasks]
  const submitted: { id: string; body: unknown }[] = []
  const fetchMock = mockApi({
    'GET /api/auth/me': () => ({ body: { id: 1, email: 'l@x.dev', role: 'labeler' } }),
    'GET /api/projects/7/queue/next': () => {
      const next = queue[0] ?? null
      return next ? { body: next } : { status: 204 }
    },
    'GET /api/projects/7/queue/progress': () => ({
      body: { completed: tasks.length - queue.length, remaining: queue.filter(Boolean).length },
    }),
    'GET /api/projects/7/queue/accuracy': () => ({
      body: { gold_answered: 4, gold_correct: 3, accuracy: 0.75 },
    }),
  })
  // Any POST to /assignments/:id/label records the body and advances the queue.
  const original = fetchMock.getMockImplementation()!
  fetchMock.mockImplementation(async (input, init) => {
    const match = String(input).match(/\/api\/assignments\/(\d+)\/label$/)
    if (match && init?.method === 'POST') {
      submitted.push({ id: match[1], body: JSON.parse(String(init.body)) })
      queue.shift()
      return new Response('{}', { status: 201 })
    }
    return original(input, init)
  })

  renderAt(<LabelPage />, { path: '/projects/7/label', route: '/projects/:projectId/label' })
  return { submitted, fetchMock }
}

describe('LabelPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the item and its label options', async () => {
    renderLabelPage([task(1)])
    expect(await screen.findByRole('img')).toHaveAttribute('src', '/img/1.png')
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual([
      '1 cat',
      '2 dog',
      '3 bird',
    ])
  })

  it('submits the clicked option with time on task, then loads the next item', async () => {
    const { submitted } = renderLabelPage([task(1), task(2)])
    await userEvent.click(await screen.findByRole('button', { name: /dog/ }))

    await waitFor(() => expect(screen.getByRole('img')).toHaveAttribute('src', '/img/2.png'))
    expect(submitted).toHaveLength(1)
    expect(submitted[0].id).toBe('1')
    expect(submitted[0].body).toMatchObject({ value: 'dog' })
    expect((submitted[0].body as { time_spent_ms: number }).time_spent_ms).toBeGreaterThanOrEqual(0)
  })

  it('labels with number keys', async () => {
    const { submitted } = renderLabelPage([task(1)])
    await screen.findByRole('img')
    await userEvent.keyboard('3')
    await waitFor(() => expect(submitted[0]?.body).toMatchObject({ value: 'bird' }))
  })

  it('ignores number keys beyond the option count', async () => {
    const { submitted } = renderLabelPage([task(1)])
    await screen.findByRole('img')
    await userEvent.keyboard('9')
    expect(submitted).toHaveLength(0)
  })

  it("shows the labeler's accuracy on check questions", async () => {
    renderLabelPage([task(1)])
    expect(await screen.findByLabelText('accuracy')).toHaveTextContent('75% (3 of 4)')
  })

  it('says when the queue is empty', async () => {
    renderLabelPage([null])
    expect(await screen.findByText('All done')).toBeInTheDocument()
  })
})
