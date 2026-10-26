import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockApi, renderAt } from '../test/render'
import AuditPage from './AuditPage'

const entry = (id: number, action: string) => ({
  id,
  actor_email: 'admin@x.dev',
  action,
  target_type: 'item',
  target_id: id,
  before: action === 'item.resolve' ? { value: 'cat', note: null } : null,
  after: { value: 'dog' },
  created_at: '2026-10-26T12:00:00Z',
})

describe('AuditPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('filters by action and shows before and after', async () => {
    localStorage.setItem('gauge.token', 'test-token')
    const fetchMock = mockApi({
      'GET /api/auth/me': () => ({ body: { id: 1, email: 'admin@x.dev', role: 'admin' } }),
      'GET /api/audit': () => ({
        body: { total: 2, entries: [entry(2, 'item.resolve'), entry(1, 'label.create')] },
      }),
    })
    renderAt(<AuditPage />, { path: '/audit', route: '/audit' })

    expect(await screen.findByText('1–2 of 2')).toBeInTheDocument()
    expect(screen.getByText('before {"value":"cat","note":null}')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Older' })).toBeDisabled()

    await userEvent.selectOptions(screen.getByLabelText('Action'), 'item.resolve')
    const urls = fetchMock.mock.calls.map(([input]) => String(input))
    expect(urls.at(-1)).toContain('action=item.resolve')
  })
})
