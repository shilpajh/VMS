---
paths:
  - "apps/web/**/*.ts"
  - "apps/web/**/*.tsx"
---

# React web portal rules
- TypeScript strict; consume typed contracts from packages/contracts — never hand-roll response shapes.
- No business/approval/status policy in the UI; the server decides, the UI renders.
- Show the full canonical status set: Requested, Registered, Awaiting Approval, Awaiting Dual Sign-off, Held, Checked-in, Checked-out, Denied, Safe.
- WCAG 2.1 AA: keyboard nav, contrast, ARIA labels, timeout extensions. All strings via i18next.
- When a success/result state UNMOUNTS the form that submitted it (a `mutation.isSuccess ? result : form` swap), move focus to the result region — `role="status"` + `tabIndex={-1}` + a `useEffect` that calls `.focus()` on success. Otherwise the submit button unmounts and focus silently reverts to `<body>` for sighted keyboard users (WCAG 2.4.3). This bug recurred on CheckinPage (US-01) and PortalRequestForm (US-13b) — copy the pattern, don't rediscover it.
- TanStack Query for server state; no tokens/PII in localStorage.
- One consistent primary color/theme across all portals (blue per prototype).
