#!/usr/bin/env python3
"""
Fetches Kaggle GPU quota and writes the result to status.json.

Design contract
───────────────
• Always exits 0 so GitHub Actions always reaches the "commit" step.
• On any failure, writes {"status": "error", ...} to status.json so the
  dashboard shows the error instead of stale data.
• Never calls sys.exit(1) — errors are surfaced through status.json.

Authentication
──────────────
Reads KAGGLE_USERNAME and KAGGLE_KEY from environment variables (injected
from GitHub Secrets by the workflow). Uses HTTP Basic Auth, which is what
the Kaggle API client also uses under the hood.

Endpoint discovery
──────────────────
Kaggle's GPU quota is not part of the documented public API. The script
tries several known internal endpoints in order and stops at the first
HTTP-200 JSON response. If you get a parse_error with a raw_response,
open an issue so the field-name list can be extended.
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

# ── Config ────────────────────────────────────────────────────────────────────
_BASE    = "https://www.kaggle.com/api/v1"
_TIMEOUT = 30
_OUT     = os.environ.get("STATUS_JSON_PATH", "status.json")

# Must match the arc length in script.js (π × 90 ≈ 282.7)
_HEADERS = {
    "Accept":     "application/json",   # prevents HTML error pages on some routes
    "User-Agent": "kaggle-gpu-dashboard/1.1 (+github-actions)",
}


def _endpoints(username: str) -> list[str]:
    return [
        f"{_BASE}/users/{username}/kernelQuota",
        f"{_BASE}/kernel/quota",
        f"{_BASE}/kernels/quota",
        f"{_BASE}/users/{username}/acceleratorQuota",
    ]


# ── Credentials ───────────────────────────────────────────────────────────────

def get_credentials() -> tuple[str, str]:
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    key      = os.environ.get("KAGGLE_KEY",      "").strip()

    problems: list[str] = []
    if not username:
        problems.append("KAGGLE_USERNAME is empty or missing")
    if not key:
        problems.append("KAGGLE_KEY is empty or missing")
    elif len(key) < 20:
        problems.append(
            f"KAGGLE_KEY is only {len(key)} characters — "
            "it looks truncated (should be ~32 hex chars)"
        )

    if problems:
        raise EnvironmentError(
            "Credential problem(s):\n" +
            "\n".join(f"  • {p}" for p in problems) +
            "\n\nFix: GitHub repo → Settings → Secrets → Actions → "
            "add KAGGLE_USERNAME and KAGGLE_KEY from your kaggle.json file."
        )

    return username, key


# ── HTTP request (never raises) ───────────────────────────────────────────────

def _safe_get(url: str, auth: tuple) -> tuple[int, dict | None, str]:
    """
    Returns (http_status, parsed_json_or_None, error_detail_string).
    Swallows all exceptions and encodes them in the return value.
    """
    try:
        resp = requests.get(url, auth=auth, headers=_HEADERS, timeout=_TIMEOUT)
    except requests.Timeout:
        return 0, None, f"Timed out after {_TIMEOUT}s"
    except requests.ConnectionError as exc:
        return 0, None, f"Connection error: {exc}"
    except Exception as exc:          # noqa: BLE001
        return 0, None, f"Unexpected error: {exc}"

    code = resp.status_code
    ct   = resp.headers.get("Content-Type", "")

    # HTML response = Kaggle returned a login/error page, not an API response.
    # This is the most common failure mode when credentials are wrong or the
    # endpoint doesn't exist.
    if "text/html" in ct:
        preview = resp.text[:200].replace("\n", " ").strip()
        return code, None, (
            f"Got HTML instead of JSON (Content-Type: {ct!r}). "
            f"HTTP {code}. Page preview: {preview!r}. "
            "This usually means wrong credentials or a non-existent endpoint."
        )

    if code == 401:
        return code, None, (
            "HTTP 401 Unauthorized. "
            "Double-check that KAGGLE_USERNAME and KAGGLE_KEY match "
            "your kaggle.json exactly."
        )
    if code == 403:
        return code, None, "HTTP 403 Forbidden — the API key may lack permission."
    if code == 404:
        return code, None, f"HTTP 404 — endpoint not found: {url}"
    if code != 200:
        return code, None, f"HTTP {code}: {resp.text[:200]}"

    try:
        return 200, resp.json(), ""
    except ValueError:
        preview = resp.text[:200].replace("\n", " ").strip()
        return 200, None, f"HTTP 200 but body is not valid JSON. Preview: {preview!r}"


# ── Fetch loop ────────────────────────────────────────────────────────────────

def fetch_quota(username: str, key: str) -> dict:
    auth   = (username, key)
    errors: list[str] = []

    for url in _endpoints(username):
        code, data, detail = _safe_get(url, auth)

        if code == 200 and data is not None:
            print(f"[OK]   {url}")
            return data

        msg = f"{url} → {detail or f'HTTP {code}'}"
        print(f"[SKIP] {msg}")
        errors.append(msg)

        # Wrong credentials: no point hammering the other endpoints.
        if code == 401:
            break

    raise RuntimeError(
        "All Kaggle quota endpoints failed:\n" +
        "\n".join(f"  {i+1}. {e}" for i, e in enumerate(errors))
    )


# ── Parse ─────────────────────────────────────────────────────────────────────

def _first(data: dict, *keys):
    """First matching key, with case-insensitive fallback."""
    for k in keys:
        if k in data:
            return data[k]
    lowered = {k.lower(): v for k, v in data.items()}
    for k in keys:
        if k.lower() in lowered:
            return lowered[k.lower()]
    return None


def parse_quota(data: dict) -> dict:
    total = _first(data,
        "gpuQuota", "gpu_quota", "gpuHours", "gpu_hours",
        "totalGpu", "total_gpu", "gpuTotal", "gpu_total")
    used = _first(data,
        "gpuUsed", "gpu_used", "gpuHoursUsed", "gpu_hours_used",
        "usedGpu", "used_gpu", "gpuUtilized", "gpu_utilized")
    remaining = _first(data,
        "gpuRemaining", "gpu_remaining", "remainingGpu", "remaining_gpu",
        "gpuHoursRemaining", "gpu_hours_remaining")

    if remaining is None and total is not None and used is not None:
        remaining = round(float(total) - float(used), 2)
    if total is None and remaining is not None and used is not None:
        total = round(float(remaining) + float(used), 2)

    pct = None
    if total and float(total) > 0 and remaining is not None:
        pct = round((float(remaining) / float(total)) * 100, 1)

    return {"remaining_hours": remaining, "total_hours": total, "percentage_remaining": pct}


# ── Write ─────────────────────────────────────────────────────────────────────

def write_status(payload: dict) -> None:
    with open(_OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    # Echo the written payload so it appears in the Actions log
    print(f"[WRITE] {_OUT}")
    print(json.dumps(payload, indent=2))


# ── Main — never raises, never exits non-zero ─────────────────────────────────

def main() -> None:
    now = datetime.now(timezone.utc).isoformat()

    # 1. Credentials
    try:
        username, key = get_credentials()
    except EnvironmentError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        write_status({"status": "error", "error": str(exc), "last_updated": now})
        return   # exit 0 → workflow continues to commit step

    # 2. Fetch
    try:
        raw = fetch_quota(username, key)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        write_status({"status": "error", "error": str(exc), "last_updated": now})
        return   # exit 0

    # 3. Parse
    parsed = parse_quota(raw)

    if parsed["remaining_hours"] is None:
        # Got a valid JSON response but couldn't find quota fields.
        # Store it so the user can inspect raw_response and open an issue.
        warning = (
            f"Fetched JSON but could not find GPU-hours fields. "
            f"Top-level keys: {list(raw.keys())}. "
            "Check raw_response in status.json and open an issue."
        )
        print(f"[WARN] {warning}", file=sys.stderr)
        write_status({
            "status": "parse_error",
            "error": warning,
            "last_updated": now,
            "raw_response": raw,
        })
        return   # exit 0

    # 4. Success
    write_status({
        "status": "ok",
        "remaining_hours": parsed["remaining_hours"],
        "total_hours":     parsed["total_hours"],
        "percentage_remaining": parsed["percentage_remaining"],
        "last_updated": now,
        "raw_response": raw,   # kept for debugging field-name drift
    })


if __name__ == "__main__":
    main()
