import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ME, mockApi, renderRoute } from './test/utils'

describe('app shell', () => {
  it('shows the navigation once the user is known', async () => {
    mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /settings': () => ({ body: { theme: 'system' } }),
      'GET /dashboard': () => ({ body: null }),
      'GET /dashboard/months': () => ({ body: { months: [] } }),
    })
    renderRoute('/')
    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('heading', { name: 'Personal finance' })).toBeInTheDocument()
    expect(screen.getByText(/No transactions yet/)).toBeInTheDocument()
  })

  it('explains when the server is unreachable', async () => {
    mockApi({ 'GET /me': () => ({ status: 503, body: { status: 503, code: 'x', title: 'Down' } }) })
    renderRoute('/')
    expect(await screen.findByRole('heading', { name: "Can't reach Finboard" })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('redirects /settings to the accounts tab and switches tabs', async () => {
    mockApi({
      'GET /me': () => ({ body: ME }),
      'GET /settings': () => ({ body: { theme: 'system' } }),
      'GET /accounts': () => ({ body: { items: [] } }),
      'GET /categories': () => ({ body: { items: [] } }),
    })
    renderRoute('/settings')
    expect(await screen.findByRole('heading', { name: 'Accounts' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Categories' }))
    expect(await screen.findByRole('heading', { name: 'Categories' })).toBeInTheDocument()
  })
})
