#!/usr/bin/env python3
"""venue_auth.py — venue credential gaps become h-task specs. Stdlib only.

A venue needing a key the machine lacks is not an error — it is a
SECRET/AUTHORIZATION h-task waiting to be filed. This maps gaps to
filing specs so agents escalate with operation + kind instead of
failing silently or hallucinating access.

  python3 meters/venue_auth.py audit [--env PREFIX]
  python3 meters/venue_auth.py check github
"""
from __future__ import annotations
import argparse
import json
import os

# venue -> {env vars holding credentials, kind, operation, recommendation}
VENUES = {
    "github": {"env": ["GITHUB_TOKEN", "GH_TOKEN"], "kind": "SECRET",
               "operation": "venue.github.auth",
               "recommendation": "paste a fine-grained token (repo scope)"},
    "telnyx": {"env": ["TELNYX_API_KEY"], "kind": "SECRET",
               "operation": "venue.telnyx.auth",
               "recommendation": "paste the Telnyx API key"},
    "cloudflare": {"env": ["CLOUDFLARE_API_TOKEN", "CF_API_TOKEN"],
                   "kind": "SECRET", "operation": "venue.cloudflare.auth",
                   "recommendation": "paste a scoped API token"},
    "openrouter": {"env": ["OPENROUTER_API_KEY"], "kind": "SECRET",
                   "operation": "venue.openrouter.auth",
                   "recommendation": "paste the OpenRouter key"},
    "stripe": {"env": ["STRIPE_SECRET_KEY"], "kind": "AUTHORIZATION",
               "operation": "venue.stripe.live",
               "recommendation": "confirm live keys (money moves after)"},
}


def audit(env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    gaps, ok = [], []
    for venue, spec in VENUES.items():
        present = [v for v in spec["env"] if env.get(v)]
        if present:
            ok.append(venue)
        else:
            gaps.append({"venue": venue, "kind": spec["kind"],
                         "operation": spec["operation"],
                         "need": f"missing one of: {', '.join(spec['env'])}",
                         "recommendation": spec["recommendation"]})
    return {"ok": ok, "gaps": gaps,
            "rule": "file each gap via escalate --kind KIND --need NEED"
                    " --operation OPERATION (proof-of-attempt still applies;"
                    " missing credential IS the failed check after one look)"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="venue_auth.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit")
    p = sub.add_parser("check")
    p.add_argument("venue")
    a = ap.parse_args(argv)
    if a.cmd == "audit":
        print(json.dumps(audit(), indent=1)[:3000])
    else:
        spec = VENUES.get(a.venue)
        if not spec:
            print(json.dumps({"error": f"unknown venue: {a.venue}"}))
            return 1
        print(json.dumps({"venue": a.venue, **spec}, indent=1)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
