import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockApi, renderAt } from '../test/render'
import LandingPage from './LandingPage'

const reviewer = { id: 2, email: 'reviewer@gauge.dev', role: 'reviewer' }

describe('LandingPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('signs in as the reviewer and opens the drift demo on the drifter', async () => {
    const fetchMock = mockApi({
      'POST /api/auth/login': () => ({ body: { access_token: 'tok' } }),
      'GET /api/auth/me': () => ({ body: reviewer }),
      'GET /api/projects': () => ({
        body: [
          { id: 1, name: 'CIFAR-10 demo' },
          { id: 7, name: 'Simulated labelers (drift demo)' },
        ],
      }),
    })
    renderAt(<LandingPage />, { route: '/' })

    await userEvent.click(screen.getByRole('button', { name: /Catch a drifting labeler/ }))

    expect(await screen.findByText('Navigated away')).toBeInTheDocument()
    const loginBody = fetchMock.mock.calls[0][1]?.body as URLSearchParams
    expect(loginBody.get('username')).toBe('reviewer@gauge.dev')
    expect(localStorage.getItem('gauge.token')).toBe('tok')
  })

  it('shows the error when the demo sign-in fails', async () => {
    mockApi({
      'POST /api/auth/login': () => ({ status: 503, body: { detail: 'Database unavailable' } }),
    })
    renderAt(<LandingPage />, { route: '/' })

    await userEvent.click(screen.getByRole('button', { name: /Label images yourself/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Database unavailable')
    expect(screen.getByRole('button', { name: /Label images yourself/ })).toBeEnabled()
  })

  it('draws the drift chart without the API', () => {
    const fetchMock = mockApi({})
    renderAt(<LandingPage />, { route: '/' })
    expect(screen.getByRole('img', { name: /jumps to about 40% on day 6/ })).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
