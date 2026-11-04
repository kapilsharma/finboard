import { useEffect, useState } from 'react'
import { useJob, useRefreshAfterJob } from '../../api/hooks'
import type { Job } from '../../api/types'

/** Track one background job: start it with the job a mutation returned, then poll it. When it
 *  finishes, refresh whatever categorisation data it may have changed. */
export function useJobRunner() {
  const [jobId, setJobId] = useState<string | undefined>()
  const job = useJob(jobId)
  const refresh = useRefreshAfterJob()
  const status = job.data?.status
  const finished = status === 'succeeded' || status === 'failed' || status === 'cancelled'

  useEffect(() => {
    if (finished) refresh() // once per finished job
  }, [finished, jobId, refresh])

  return {
    job: job.data as Job | undefined,
    running: jobId !== undefined && !finished,
    finished,
    track: (id: string) => setJobId(id),
    reset: () => setJobId(undefined),
  }
}
