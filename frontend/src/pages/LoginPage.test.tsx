import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockApi, renderAt } from '../test/render'
import LoginPage from './LoginPage'

describe('LoginPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the API error on a bad password', async () => {
    mockApi({
      'POST /api/auth/login': () => ({
        status: 401,
        body: { detail: 'Incorrect email or password' },
      }),
    })
    renderAt(<LoginPage />)

    await userEvent.type(screen.getByLabelText('Email'), 'a@b.dev')
    await userEvent.type(screen.getByLabelText('Password'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password')
    expect(localStorage.getItem('gauge.token')).toBeNull()
  })

  it('stores the token and leaves the page after a demo sign-in', async () => {
    const fetchMock = mockApi({
      'POST /api/auth/login': () => ({ body: { access_token: 'tok' } }),
      'GET /api/auth/me': () => ({ body: { id: 1, email: 'admin@gauge.dev', role: 'admin' } }),
    })
    renderAt(<LoginPage />)

    await userEvent.click(screen.getByRole('button', { name: 'Admin' }))

    expect(await screen.findByText('Navigated away')).toBeInTheDocument()
    expect(localStorage.getItem('gauge.token')).toBe('tok')
    const loginBody = fetchMock.mock.calls[0][1]?.body as URLSearchParams
    expect(loginBody.get('username')).toBe('admin@gauge.dev')
  })
})
