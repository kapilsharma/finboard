import { describe, expect, it } from 'vitest'
import { formatBytes, formatDate, formatMoney, groupIndian } from './format'

describe('format', () => {
  it('groups in lakhs and crores', () => {
    expect(groupIndian('142702.04')).toBe('1,42,702.04')
    expect(groupIndian('20000000')).toBe('2,00,00,000.00')
    expect(groupIndian('999.5')).toBe('999.50')
    expect(groupIndian('0.00')).toBe('0.00')
  })

  it('formats money strings without arithmetic', () => {
    expect(formatMoney('2350.00')).toBe('₹2,350.00')
    expect(formatMoney('-94.00')).toBe('−₹94.00')
    // More digits than a float can hold exactly survive untouched.
    expect(formatMoney('999999999999.99')).toBe('₹9,99,99,99,99,999.99')
    expect(formatMoney(null)).toBe('—')
  })

  it('formats dates and sizes', () => {
    expect(formatDate('2026-09-05')).toMatch(/^5 Sep/)
    expect(formatDate(null)).toBe('—')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2 * 1024 * 1024)).toBe('2.0 MB')
  })
})
