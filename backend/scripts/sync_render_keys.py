"""Copy the local key pool into the Render service's environment.

Render's API can replace the whole environment list in one call, which is a good
way to delete SUPABASE_SERVICE_ROLE_KEY by forgetting to include it. So each
variable is set individually with PUT /env-vars/{key}, leaving everything else
alone.

Nothing here prints a value. It reports names, how many keys each variable holds
and their lengths, which is enough to confirm the right thing was sent without
putting a credential in the terminal scrollback or in this session's transcript.

Usage:
    .venv/bin/python scripts/sync_render_keys.py [--apply]

Without --apply it only reports what would change.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

import httpx

SERVICE_ID = "srv-da8ittbtqb8s73abmqe0"
API = "https://api.render.com/v1"

#: The variables this script owns. Anything else on the service is untouched.
SYNCED = ("GEMINI_API_KEY", "GEMINI_API_KEYS", "GROQ_API_KEY", "GROQ_API_KEYS", "GEMINI_MODEL")


def local_env() -> dict[str, str]:
    path = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        sys.exit(f"No {path}; nothing to sync.")
    text = path.read_text()
    return {k: v.strip() for k, v in re.findall(r"^([A-Z0-9_]+)=(.*)$", text, re.M)}


def token() -> str:
    key_file = pathlib.Path.home() / ".render_api_key"
    if key_file.exists():
        return key_file.read_text().strip()
    from_env = os.environ.get("RENDER_API_KEY", "").strip()
    if from_env:
        return from_env
    sys.exit("No Render API key in ~/.render_api_key or RENDER_API_KEY.")


def describe(value: str) -> str:
    """A value's shape, never its content."""
    parts = [p for p in value.replace("\n", ",").split(",") if p.strip()]
    if len(parts) == 1:
        return f"1 value, {len(parts[0])} chars"
    return f"{len(parts)} values, lengths {[len(p) for p in parts]}"


def main() -> None:
    apply = "--apply" in sys.argv
    values = local_env()
    headers = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json"}

    with httpx.Client(timeout=30.0, headers=headers) as client:
        listing = client.get(f"{API}/services/{SERVICE_ID}/env-vars", params={"limit": 100})
        listing.raise_for_status()
        remote = {
            item["envVar"]["key"]: item["envVar"].get("value", "")
            for item in listing.json()
        }
        print(f"Service has {len(remote)} environment variables.")

        for name in SYNCED:
            wanted = values.get(name)
            if not wanted:
                print(f"  {name}: not set locally, skipping")
                continue

            current = remote.get(name)
            if current == wanted:
                print(f"  {name}: already correct ({describe(wanted)})")
                continue

            was = "absent" if current is None else describe(current)
            print(f"  {name}: {was} -> {describe(wanted)}", end="")
            if not apply:
                print("  [dry run]")
                continue

            resp = client.put(
                f"{API}/services/{SERVICE_ID}/env-vars/{name}", json={"value": wanted}
            )
            if resp.status_code >= 400:
                print(f"  FAILED {resp.status_code}: {resp.text[:200]}")
                sys.exit(1)
            print("  updated")

    if not apply:
        print("\nDry run. Re-run with --apply to write these, then deploy.")
    else:
        print("\nWritten. A deploy is needed for the service to pick them up.")


if __name__ == "__main__":
    main()
