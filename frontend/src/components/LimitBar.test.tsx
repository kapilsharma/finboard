import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { CategoryLimit } from '../api/types'
import { LimitBar } from './LimitBar'

function item(
  spent: string,
  limit: string | null,
  remaining: string | null,
  status: CategoryLimit['status'],
): CategoryLimit {
  return {
    category: { id: 'c1', name: 'Dining out', type: 'expense', colour: null },
    spent,
    limit,
    remaining,
    pct_used: null,
    status,
  }
}

describe('LimitBar', () => {
  it('over the limit: "₹94 over" (no minus sign), red, with a tick at the limit', () => {
    render(<LimitBar item={item('4093.94', '4000.00', '-93.94', 'over')} />)
    const over = screen.getByText('₹94 over')
    expect(over.className).toMatch(/over/)
    expect(screen.getByText('₹4,094 of ₹4,000')).toBeInTheDocument()
    const tick = screen.getByTestId('limit-tick')
    expect(tick.style.left).toBe(`${(4000 / 4093.94) * 100}%`)
    expect(screen.getByTestId('limit-fill').style.width).toBe('100%')
    expect(screen.queryByText(/−/)).not.toBeInTheDocument()
  })

  it('under the limit: "₹680 left", green, no tick, fill proportional', () => {
    render(<LimitBar item={item('5320.00', '6000.00', '680.00', 'under')} />)
    expect(screen.getByText('₹680 left').className).toMatch(/ok/)
    expect(screen.queryByTestId('limit-tick')).not.toBeInTheDocument()
    expect(screen.getByTestId('limit-fill').style.width).toBe(`${(5320 / 6000) * 100}%`)
  })

  it('exactly at the limit is "₹0 left", not over', () => {
    render(<LimitBar item={item('32000.00', '32000.00', '0.00', 'under')} />)
    expect(screen.getByText('₹0 left')).toBeInTheDocument()
  })

  it('no limit: muted bar and "No limit set"', () => {
    render(<LimitBar item={item('6850.00', null, null, 'no_limit')} />)
    expect(screen.getByText('No limit set')).toBeInTheDocument()
    expect(screen.getByText('₹6,850')).toBeInTheDocument()
    expect(screen.queryByTestId('limit-fill')).not.toBeInTheDocument()
  })

  it('is a toggle button that reports its state', async () => {
    const onClick = vi.fn()
    render(<LimitBar item={item('1.00', '2.00', '1.00', 'under')} selected onClick={onClick} />)
    const button = screen.getByRole('button', { name: /Dining out/ })
    expect(button).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(button)
    expect(onClick).toHaveBeenCalled()
  })
})
