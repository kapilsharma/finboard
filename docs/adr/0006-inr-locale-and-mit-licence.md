# ADR-0006: INR / en-IN formatting; MIT licence

**Status:** Accepted (given — HANDOVER §2)

**Decision.** v1 is single-currency INR with `en-IN` formatting (₹1,42,000; compact ₹50K / ₹1L / ₹1.5L / ₹2Cr using a custom formatter, because Intl's en-IN compact produces "T"). Locale and currency are read from settings so they can vary later. The code is MIT-licensed.
