import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DeltaBadge } from './HeadlineCards'

describe('DeltaBadge', () => {
  it('income up is good, spending up is bad, and says so in words', () => {
    const { rerender, container } = render(
      <DeltaBadge text="+4.6%" value={4.6} goodWhenUp prevMonth="2026-08" />,
    )
    expect(screen.getByText('+4.6%').className).toMatch(/good/)
    expect(container).toHaveTextContent('+4.6% (better) vs Aug')
    rerender(<DeltaBadge text="+4.6%" value={4.6} goodWhenUp={false} prevMonth="2026-08" />)
    expect(screen.getByText('+4.6%').className).toMatch(/bad/)
    expect(container).toHaveTextContent('(worse)')
  })

  it('no change is neither good nor bad; no previous month says so', () => {
    const { rerender, container } = render(
      <DeltaBadge text="+0.0%" value={0} goodWhenUp prevMonth="2026-08" />,
    )
    expect(container).not.toHaveTextContent(/better|worse/)
    rerender(<DeltaBadge text="—" value={null} goodWhenUp prevMonth={null} />)
    expect(container).toHaveTextContent('No earlier month')
  })
})
