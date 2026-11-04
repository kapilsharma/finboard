/** Plain helpers for import status (kept out of component files for fast refresh). */

import { IMPORT_IN_FLIGHT, type ImportResource } from '../../api/types'
import { formatDate } from '../../lib/format'

export function statusLine(resource: ImportResource): string {
  switch (resource.status) {
    case 'uploaded':
      return 'Waiting for a free slot (other statements are being read).'
    case 'queued':
    case 'processing':
      return 'Reading the statement…'
    case 'needs_password':
      return 'This statement is password-protected.'
    case 'parsed': {
      const counts = resource.counts
      const period = resource.period
        ? `${formatDate(resource.period.start)} – ${formatDate(resource.period.end)}`
        : 'unknown period'
      return counts
        ? `${counts.new} new, ${counts.duplicate} already imported · ${period}`
        : 'Ready to review.'
    }
    case 'committed':
      return resource.result
        ? `Imported ${resource.result.inserted}, skipped ${resource.result.skipped}.`
        : 'Imported.'
    case 'failed':
      return resource.error ?? 'Failed.'
    case 'rolled_back':
      return 'Rolled back.'
    case 'discarded':
      return 'Discarded.'
  }
}

export function isInFlight(resource: ImportResource | undefined) {
  return resource !== undefined && IMPORT_IN_FLIGHT.has(resource.status)
}
