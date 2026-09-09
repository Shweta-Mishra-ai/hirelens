"""
HireLens — Same-site / cross-site detection for the session cookie.

Why this exists: the session cookie's attributes have to change depending on
whether the frontend and this API share a registrable domain.

- Cross-site (`hirelens.vercel.app` frontend → `hirelens-api.onrender.com`
  API): the cookie must be `SameSite=None; Secure; Partitioned` to be sent at
  all, and Safari/Firefox-strict/Incognito will still drop it. That is today's
  default deployment.
- Same-site (`app.example.com` → `api.example.com`): `SameSite=Lax` works
  everywhere, in every browser, with no third-party-cookie caveat at all. This
  is the correct end state and the one the README recommends moving to.

Hardcoding "always cross-site" means the day the domains are unified, the app
keeps sending a needlessly weak cookie and nothing tells anyone. Hardcoding
"always same-site" breaks login today. So it is detected from FRONTEND_URL vs
BACKEND_URL, with an explicit override for the cases detection can't be sure
about.

FAIL-SAFE DIRECTION: when in doubt, assume cross-site. That is the strictly
more permissive cookie, so an incorrect guess degrades to today's known-working
behaviour rather than breaking login. Same-site is only chosen when it can be
proven from the configured URLs.
"""

import logging
from urllib.parse import urlparse

logger = logging.getLogger("hirelens")

# Hosting domains that are themselves public suffixes: every customer gets a
# subdomain, so two hosts sharing one of these are DIFFERENT sites even though
# a naive "last two labels" comparison says otherwise. `a.vercel.app` and
# `b.vercel.app` are as unrelated as two different companies.
#
# Getting this wrong in the other direction is the dangerous one: treating
# vercel.app-to-vercel.app as same-site would set SameSite=Lax and silently
# break login for everyone. Hence the explicit list.
_PUBLIC_SUFFIX_HOSTS = frozenset({
    "vercel.app",
    "onrender.com",
    "netlify.app",
    "herokuapp.com",
    "pages.dev",
    "workers.dev",
    "github.io",
    "fly.dev",
    "railway.app",
    "up.railway.app",
    "azurewebsites.net",
    "appspot.com",
    "firebaseapp.com",
    "web.app",
    "surge.sh",
    "now.sh",
    "ngrok.io",
    "ngrok-free.app",
})

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


def _host(url: str) -> str:
    """Hostname of a URL, lowercased, port and trailing dot stripped."""
    if not url:
        return ""
    candidate = url.strip()
    if "//" not in candidate:
        candidate = "//" + candidate
    host = (urlparse(candidate).hostname or "").lower().rstrip(".")
    return host


def registrable_domain(host: str) -> str:
    """The site a host belongs to, as far as cookies are concerned.

    Approximate — a full Public Suffix List lookup would need a dependency and
    a data file that goes stale. The approximation is "last two labels, unless
    the last two labels are themselves a known public suffix, in which case
    take three". That covers every real deployment shape this app has, and the
    only cost of being wrong is falling back to the cross-site cookie.
    """
    if not host or host in _LOCAL_HOSTS:
        return host
    labels = host.split(".")
    if len(labels) < 2:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in _PUBLIC_SUFFIX_HOSTS and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def is_same_site(frontend_url: str, backend_url: str) -> bool | None:
    """True/False if it can be determined, None if there isn't enough info.

    None is deliberately distinct from False: "we don't know" should read as
    a prompt to configure BACKEND_URL, not as a claim about the deployment.
    """
    fe, be = _host(frontend_url), _host(backend_url)
    if not fe or not be:
        return None

    # Local development: both on localhost (any port) is same-site. Ports do
    # not affect a cookie's site.
    if fe in _LOCAL_HOSTS and be in _LOCAL_HOSTS:
        return True
    if (fe in _LOCAL_HOSTS) != (be in _LOCAL_HOSTS):
        return False

    fe_site, be_site = registrable_domain(fe), registrable_domain(be)

    # Both on the same public-suffix host (two vercel.app apps, say) means two
    # different sites, regardless of the string comparison below.
    if ".".join(fe.split(".")[-2:]) in _PUBLIC_SUFFIX_HOSTS and fe_site == be_site:
        return fe == be

    return fe_site == be_site


def session_cookie_is_cross_site(settings) -> bool:
    """Whether the session cookie has to survive a cross-site request.

    Reads SESSION_COOKIE_CROSS_SITE first (explicit wins), then falls back to
    detection from FRONTEND_URL/BACKEND_URL, then to True (fail-safe).
    """
    override = settings.SESSION_COOKIE_CROSS_SITE
    if override is not None:
        return override

    same_site = is_same_site(settings.FRONTEND_URL, settings.BACKEND_URL)
    if same_site is None:
        # BACKEND_URL is unset — can't prove same-site, so assume the wider
        # setting. This is the current default deployment's situation.
        return True
    return not same_site
