#!/usr/bin/env python3
"""
Fetches Kaggle GPU quota and writes the result to status.json.

Authentication: reads KAGGLE_USERNAME and KAGGLE_KEY from environment variables,
which GitHub Actions injects from the repository secrets.

Kaggle does not document a public GPU-quota endpoint, but their web app calls
  GET /api/v1/users/{username}/kernelQuota
with HTTP Basic auth (username + API key). This script tries that endpoint and
several fallbacks, then normalises the varying field-name conventions.
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

# ── Endpoints to try, in order of preference ────────────────────────────────
_BASE = "https://www.kaggle.com/api/v1"


def _candidate_urls(username: str) -> list[str]:
    return [
        f"{_BASE}/users/{username}/kernelQuota",
        f"{_BASE}/kernel/quota",
        f"{_BASE}/kernels/quota",
        f"{_BASE}/users/{username}/acceleratorQuota",
    ]


# ── Credential helpers ───────────────────────────────────────────────────────

def get_credentials() -> tuple[str, str]:
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    if not username or not key:
        raise EnvironmentError(
            "Both KAGGLE_USERNAME and KAGGLE_KEY environment variables must be set."
        )
    return username, key


# ── Fetch ────────────────────────────────────────────────────────────────────

def fetch_raw_quota(username: str, key: str) -> dict:
    """
    Try each candidate URL until one returns HTTP 200.
    Raises RuntimeError if all fail.
    """
    auth = (username, key)
    last_error = "No endpoints attempted."

    for url in _candidate_urls(username):
        try:
            resp = requests.get(url, auth=auth, timeout=30)
            if resp.status_code == 200:
                print(f"[OK] Fetched quota from {url}")
                return resp.json()
            last_error = f"HTTP {resp.status_code} at {url}: {resp.text[:200]}"
            print(f"[SKIP] {last_error}")
        except requests.RequestException as exc:
            last_error = f"Request error at {url}: {exc}"
            print(f"[SKIP] {last_error}")

    raise RuntimeError(
        f"All Kaggle quota endpoints failed. Last error: {last_error}\n\n"
        "Possible reasons:\n"
        "  • Your KAGGLE_USERNAME or KAGGLE_KEY is wrong.\n"
        "  • Kaggle changed their internal API (open an issue).\n"
        "See README.md for troubleshooting steps."
    )


# ── Parse ────────────────────────────────────────────────────────────────────

def _first(data: dict, *keys):
    """Return the value of the first matching key (case-insensitive fallback)."""
    for k in keys:
        if k in data:
            return data[k]
    # Case-insensitive fallback
    lower = {k.lower(): v for k, v in data.items()}
    for k in keys:
        if k.lower() in lower:
            return lower[k.lower()]
    return None


def parse_quota(data: dict) -> dict:
    """
    Normalise the raw Kaggle API response into {remaining, total, pct}.
    Handles camelCase and snake_case field names, and both "used" and
    "remaining" representations.
    """
    total = _first(
        data,
        "gpuQuota", "gpu_quota", "gpuHours", "gpu_hours",
        "totalGpu", "total_gpu", "gpuTotal", "gpu_total",
    )
    used = _first(
        data,
        "gpuUsed", "gpu_used", "gpuHoursUsed", "gpu_hours_used",
        "usedGpu", "used_gpu", "gpuUtilized", "gpu_utilized",
    )
    remaining = _first(
        data,
        "gpuRemaining", "gpu_remaining", "remainingGpu", "remaining_gpu",
        "gpuHoursRemaining", "gpu_hours_remaining",
    )

    # Derive missing values
    if remaining is None and total is not None and used is not None:
        remaining = round(float(total) - float(used), 2)
    if total is None and remaining is not None and used is not None:
        total = round(float(remaining) + float(used), 2)

    pct = None
    if total and float(total) > 0 and remaining is not None:
        pct = round((float(remaining) / float(total)) * 100, 1)

    return {
        "remaining_hours": remaining,
        "total_hours": total,
        "percentage_remaining": pct,
    }


# ── Write ────────────────────────────────────────────────────────────────────

def write_status(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"[WRITE] {path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    out_path = os.environ.get("STATUS_JSON_PATH", "status.json")
    now_iso = datetime.now(timezone.utc).isoformat()

    # --- get credentials ---
    try:
        username, key = get_credentials()
    except EnvironmentError as exc:
        write_status(out_path, {
            "status": "error",
            "error": str(exc),
            "last_updated": now_iso,
        })
        sys.exit(1)

    # --- fetch ---
    try:
        raw = fetch_raw_quota(username, key)
    except RuntimeError as exc:
        write_status(out_path, {
            "status": "error",
            "error": str(exc),
            "last_updated": now_iso,
        })
        sys.exit(1)

    # --- parse ---
    parsed = parse_quota(raw)

    # Warn if we couldn't extract the values but don't fail;
    # the dashboard will show a "data unavailable" state.
    if parsed["remaining_hours"] is None:
        print(
            "[WARN] Could not parse GPU hours from API response.\n"
            f"       Raw response: {json.dumps(raw, indent=2)}\n"
            "       Please open an issue with the output above."
        )

    write_status(out_path, {
        "status": "ok",
        "remaining_hours": parsed["remaining_hours"],
        "total_hours": parsed["total_hours"],
        "percentage_remaining": parsed["percentage_remaining"],
        "last_updated": now_iso,
        # Raw response helps debug field-name mismatches without re-running
        "raw_response": raw,
    })


if __name__ == "__main__":
    main()
