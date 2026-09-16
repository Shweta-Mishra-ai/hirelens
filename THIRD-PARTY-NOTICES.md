# Third-Party Notices

HireLens is proprietary software (see [LICENSE](LICENSE)). It incorporates
open-source components, each under its own licence. Those licences apply to
those components only.

**Every dependency permits commercial, closed-source distribution.** There is
no GPL, AGPL, SSPL or other reciprocal licence anywhere in the tree — audited
with `pip-licenses` and `license-checker-rseidelsohn`, production dependencies
only.

---

## Summary

| Licence | Backend | Frontend |
|---|--:|--:|
| MIT | 40 | 30 |
| BSD (2/3-clause) | 14 | 1 |
| Apache-2.0 | 11 | 2 |
| ISC | 1 | 3 |
| MPL-2.0 | 1 | — |
| CC-BY-4.0 | — | 1 |
| 0BSD / Unlicense / PSF / MIT-0 | 3 | 1 |

---

## What you must actually do

**MIT, BSD, ISC, Apache-2.0** — keep the copyright notice and licence text
with any distribution. Shipping this as a hosted service (SaaS) triggers no
obligation at all; shipping it as installable software means including this
file. Apache-2.0 additionally requires stating any significant changes you
make to those components.

**MPL-2.0 — `certifi`** — file-level copyleft. Using it unmodified, as this
project does, carries no obligation beyond attribution. If you ever *modify
certifi's own source files*, those modified files must be made available under
MPL-2.0. Your own code stays proprietary either way.

**CC-BY-4.0 — `caniuse-lite`** — a build-time browser-support dataset.
Requires attribution, which this file provides. Nothing ships to the browser.

---

## Regenerating this audit

```bash
cd backend && pip install pip-licenses && python -m piplicenses --format=markdown
cd frontend && npx license-checker-rseidelsohn --production --summary
```

Re-run it before any release, and whenever a dependency is added.

---

## Services, not dependencies

These are used over the network under their own terms of service, not bundled:
Google Gemini, Groq, Anthropic, Supabase, Render, Vercel, Resend, and the
GitHub public API. Their terms govern your use of them, and several restrict
what you may do with their output — worth reading before you resell analysis
built on them.

---

*This file is a good-faith engineering audit, not legal advice. Have a lawyer
review it before you sell.*
