import { describe, expect, it } from 'vitest'
import {
  formatCompact,
  formatDayMonth,
  formatMonth,
  formatMonthAxis,
  formatMonthShort,
  formatOverLeft,
  formatPct,
  formatPts,
  formatRupees,
  formatSignedPct,
  formatSignedRupees,
  roundRupees,
} from './format'

describe('dashboard formats', () => {
  it.each([
    ['142702.04', '₹1,42,702'],
    ['96040.38', '₹96,040'],
    ['46661.66', '₹46,662'],
    ['15000.00', '₹15,000'],
    ['0.00', '₹0'],
    ['0.49', '₹0'],
    ['0.50', '₹1'],
    ['999.50', '₹1,000'],
    ['99999.99', '₹1,00,000'],
    ['-32750.04', '−₹32,750'],
    ['-0.40', '₹0'],
    ['9999999999999.50', '₹1,00,00,00,00,00,000'],
  ])('formatRupees(%s) = %s', (input, expected) => {
    expect(formatRupees(input)).toBe(expected)
  })

  it('rounds half away from zero with string arithmetic', () => {
    expect(roundRupees('2.5')).toEqual({ negative: false, whole: '3' })
    expect(roundRupees('-2.5')).toEqual({ negative: true, whole: '3' })
    expect(roundRupees('199.49')).toEqual({ negative: false, whole: '199' })
  })

  it.each([
    ['-22330.28', '−₹22,330'],
    ['1000.00', '+₹1,000'],
    ['0.00', '₹0'],
  ])('formatSignedRupees(%s) = %s', (input, expected) => {
    expect(formatSignedRupees(input)).toBe(expected)
  })

  it.each([
    ['-93.94', '₹94 over'],
    ['-268.00', '₹268 over'],
    ['680.00', '₹680 left'],
    ['0.00', '₹0 left'],
    ['-0.20', '₹0 left'],
    ['-123456.70', '₹1,23,457 over'],
  ])('formatOverLeft(%s) = %s (never a minus sign)', (input, expected) => {
    expect(formatOverLeft(input)).toBe(expected)
  })

  it.each([
    [0, '₹0'],
    [500, '₹500'],
    [1000, '₹1K'],
    [1500, '₹1.5K'],
    [50000, '₹50K'],
    [99999, '₹100K'],
    [100000, '₹1L'],
    [150000, '₹1.5L'],
    [1234567, '₹12.3L'],
    [20000000, '₹2Cr'],
    [-50000, '−₹50K'],
  ])('formatCompact(%s) = %s (not Intl, which prints "T")', (input, expected) => {
    expect(formatCompact(input)).toBe(expected)
  })

  it('formats percentages, points and months', () => {
    expect(formatPct(32.7)).toBe('32.7%')
    expect(formatPct(-5)).toBe('−5.0%')
    expect(formatPct(null)).toBe('—')
    expect(formatSignedPct(4.6)).toBe('+4.6%')
    expect(formatSignedPct(-11.3)).toBe('−11.3%')
    expect(formatSignedPct(0)).toBe('+0.0%')
    expect(formatPts(-10.2)).toBe('−10.2 pts')
    expect(formatPts(1)).toBe('+1.0 pts')
    expect(formatMonth('2026-09')).toBe('September 2026')
    expect(formatMonthShort('2026-08')).toBe('Aug')
    expect(formatMonthAxis('2026-07')).toBe("Jul '26")
    expect(formatDayMonth('2026-09-28')).toBe('28 Sep')
  })
})
