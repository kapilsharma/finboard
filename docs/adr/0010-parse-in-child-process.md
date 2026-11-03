# ADR-0010: Decrypt + parse in a child process with a hard timeout

**Status:** Superseded by [ADR-0024](0024-celery-redis-jobs.md). Parsing now runs on the Celery `parse` queue, whose prefork workers provide the same isolation and a hard `time_limit` kill.

**Still valid from this ADR.** Python can't interrupt CPU-bound pdfminer code in a thread, so isolation in a separate, killable process is required. In-process timeouts are not an option.
