#!/usr/bin/env python3
"""One-shot production deployment: Render (backend) + Vercel (frontend).

Creates or updates the Render web service from the settings in render.yaml,
pushes the backend environment, deploys the frontend to Vercel with
VITE_API_BASE_URL pointing at the real Render URL, pins CORS to the Vercel
origin, and points Supabase auth at it.

Credentials, both one-time:

    RENDER_API_KEY   dashboard.render.com → Account Settings → API Keys
                     (Render's CLI cannot create services or set env vars, so
                     the REST API is the only scriptable route)
    vercel login     Vercel's CLI uses an OAuth device flow; approve in browser.
                     A VERCEL_TOKEN env var works instead.

Usage:
    export RENDER_API_KEY=...        # not echoed anywhere
    python3 scripts/deploy.py

Secrets are read from backend/.env and frontend/.env.local (both gitignored) and
are never printed: only variable NAMES appear in the output.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND_ENV = REPO / "backend" / ".env"
FRONTEND_ENV = REPO / "frontend" / ".env.local"
SERVICE_NAME = "fitness-tracker-api"
GITHUB_REPO = "https://github.com/Aahil101/fitness_tracker"
SUPABASE_REF = "hoahlhknjjfoketgqkul"
RENDER_API = "https://api.render.com/v1"

# Backend variables to copy up. Names match render.yaml and app/config.py.
BACKEND_KEYS = [
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "USDA_API_KEY",
]
# Upstash is deliberately omitted: the cache falls back to an in-process store.


def step(msg: str) -> None:
    print(f"\n\033[1m== {msg} ==\033[0m", flush=True)


def die(msg: str) -> None:
    print(f"\033[31mFAILED: {msg}\033[0m", file=sys.stderr)
    sys.exit(1)


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        die(f"missing {path}")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, quiet: bool = False,
        stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, input=stdin_text,
        env={**os.environ, "PATH": f"/opt/homebrew/bin:{os.environ.get('PATH','')}"},
    )
    if check and result.returncode != 0 and not quiet:
        print(result.stdout[-1500:])
        print(result.stderr[-1500:], file=sys.stderr)
    return result


# --------------------------------------------------------------------------- #
# Render REST API
# --------------------------------------------------------------------------- #
def render_api(method: str, path: str, key: str, body: dict | None = None) -> tuple[int, object]:
    request = urllib.request.Request(
        f"{RENDER_API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw[:400]
    except urllib.error.URLError as error:
        die(f"cannot reach the Render API: {error}")
        raise  # unreachable, keeps type checkers happy


def find_service(key: str) -> dict | None:
    status, data = render_api("GET", "/services?limit=100", key)
    if status != 200 or not isinstance(data, list):
        return None
    for entry in data:
        service = entry.get("service", entry)
        if service.get("name") == SERVICE_NAME:
            return service
    return None


def create_service(key: str, env_values: dict[str, str]) -> dict:
    status, owners = render_api("GET", "/owners", key)
    if status != 200 or not owners:
        die(f"could not list Render owners (HTTP {status}): {owners}")
    owner_id = (owners[0].get("owner") or owners[0]).get("id")  # type: ignore[index]

    payload = {
        "type": "web_service",
        "name": SERVICE_NAME,
        "ownerId": owner_id,
        "repo": GITHUB_REPO,
        "branch": "main",
        "autoDeploy": "yes",
        "rootDir": "backend",
        "envVars": [
            {"key": "APP_ENV", "value": "production"},
            {"key": "LOG_LEVEL", "value": "INFO"},
            {"key": "PYTHON_VERSION", "value": "3.12.7"},
            *[
                {"key": k, "value": env_values[k]}
                for k in BACKEND_KEYS
                if env_values.get(k)
            ],
        ],
        "serviceDetails": {
            "env": "python",
            "plan": "free",
            "region": "oregon",
            "healthCheckPath": "/health",
            "envSpecificDetails": {
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": (
                    "uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers"
                ),
            },
        },
    }
    status, data = render_api("POST", "/services", key, payload)
    if status not in (200, 201):
        die(f"Render service creation failed (HTTP {status}): {data}")
    service = data.get("service", data) if isinstance(data, dict) else {}
    print(f"  created service {service.get('id')}")
    return service


def set_render_env(key: str, service_id: str, updates: dict[str, str]) -> None:
    """Merge updates into the service environment (PUT replaces the whole set)."""
    status, current = render_api("GET", f"/services/{service_id}/env-vars?limit=100", key)
    existing: dict[str, str] = {}
    if status == 200 and isinstance(current, list):
        for entry in current:
            var = entry.get("envVar", entry)
            if var.get("key"):
                existing[var["key"]] = var.get("value", "")
    existing.update(updates)

    payload = [{"key": k, "value": v} for k, v in existing.items()]
    status, data = render_api("PUT", f"/services/{service_id}/env-vars", key, payload)
    if status not in (200, 201):
        print(f"  WARN could not update env vars (HTTP {status}): {data}")
    else:
        print(f"  updated: {', '.join(sorted(updates))}")


def trigger_deploy(key: str, service_id: str) -> None:
    status, data = render_api("POST", f"/services/{service_id}/deploys", key, {})
    if status not in (200, 201):
        print(f"  WARN could not trigger a deploy (HTTP {status}): {data}")
    else:
        deploy = data.get("deploy", data) if isinstance(data, dict) else {}
        print(f"  deploy {deploy.get('id', '?')} queued")


def wait_for_health(url: str, attempts: int = 60, delay: int = 15) -> bool:
    """Free Render services build slowly and cold-start; be patient."""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=25) as response:
                if response.status == 200:
                    print(f"  attempt {attempt}: HTTP 200")
                    print("  " + response.read().decode()[:300])
                    return True
                print(f"  attempt {attempt}: HTTP {response.status}")
        except Exception as error:  # noqa: BLE001 - transient during build
            print(f"  attempt {attempt}: {type(error).__name__}")
        time.sleep(delay)
    return False


# --------------------------------------------------------------------------- #
# Vercel
# --------------------------------------------------------------------------- #
def vercel_env_set(frontend: Path, key: str, value: str) -> None:
    run(["vercel", "env", "rm", key, "production", "--yes"], cwd=frontend, check=False, quiet=True)
    result = run(["vercel", "env", "add", key, "production"], cwd=frontend,
                 check=False, stdin_text=value)
    print(f"  set {key}" if result.returncode == 0 else f"  WARN could not set {key}")


def main() -> None:
    backend_env = read_env(BACKEND_ENV)
    frontend_env = read_env(FRONTEND_ENV)

    step("0. credentials")
    render_key = os.environ.get("RENDER_API_KEY", "").strip()
    if not render_key:
        die(
            "RENDER_API_KEY is not set.\n"
            "  Create one at dashboard.render.com → Account Settings → API Keys, then:\n"
            "      export RENDER_API_KEY=...\n"
            "  (Render's CLI cannot create services or set env vars.)"
        )
    if run(["vercel", "whoami"], check=False, quiet=True).returncode != 0:
        die("not logged in to Vercel — run: vercel login   (or set VERCEL_TOKEN)")
    status, _ = render_api("GET", "/owners", render_key)
    if status != 200:
        die(f"RENDER_API_KEY rejected by the Render API (HTTP {status})")
    print("  render: API key accepted")
    print(f"  vercel: {run(['vercel', 'whoami'], check=False).stdout.strip().splitlines()[-1]}")

    step("1. Render backend service")
    service = find_service(render_key)
    if service:
        print(f"  reusing existing service {service.get('id')}")
    else:
        service = create_service(render_key, backend_env)
    service_id = service["id"]

    step("2. backend environment")
    set_render_env(render_key, service_id, {
        "APP_ENV": "production",
        "LOG_LEVEL": "INFO",
        **{k: backend_env[k] for k in BACKEND_KEYS if backend_env.get(k)},
    })
    print("  (Upstash left unset by design)")

    step("3. resolving the backend URL")
    api_url = ""
    for _ in range(20):
        status, data = render_api("GET", f"/services/{service_id}", render_key)
        if status == 200 and isinstance(data, dict):
            details = (data.get("service", data)).get("serviceDetails") or {}
            api_url = (details.get("url") or "").rstrip("/")
        if api_url:
            break
        time.sleep(10)
    if not api_url:
        die("Render did not report a service URL yet — re-run in a minute")
    print(f"  backend URL: {api_url}")

    step("4. waiting for the backend to build and pass its health check")
    trigger_deploy(render_key, service_id)
    if not wait_for_health(api_url):
        die(f"backend never became healthy — inspect: render logs --service-name {SERVICE_NAME}")

    step("5. Vercel project and environment")
    frontend = REPO / "frontend"
    run(["vercel", "link", "--yes"], cwd=frontend, check=False, quiet=True)
    vercel_env_set(frontend, "VITE_SUPABASE_URL", frontend_env["VITE_SUPABASE_URL"])
    vercel_env_set(frontend, "VITE_SUPABASE_ANON_KEY", frontend_env["VITE_SUPABASE_ANON_KEY"])
    vercel_env_set(frontend, "VITE_API_BASE_URL", api_url)
    print(f"  VITE_API_BASE_URL -> {api_url}  (never localhost)")

    step("6. deploying the frontend to production")
    result = run(["vercel", "deploy", "--prod", "--yes"], cwd=frontend, check=False)
    combined = result.stdout + result.stderr
    matches = re.findall(r"https://[a-zA-Z0-9._-]+\.vercel\.app", combined)
    if not matches:
        print(combined[-2000:])
        die("could not determine the Vercel production URL")
    web_url = matches[-1]
    print(f"  frontend URL: {web_url}")

    step("7. pinning backend CORS to the production origin")
    set_render_env(render_key, service_id, {"CORS_ORIGINS": web_url})
    trigger_deploy(render_key, service_id)
    print("  waiting for the redeploy to serve the new CORS value…")
    wait_for_health(api_url, attempts=40)

    step("8. Supabase auth URLs")
    # Written narrowly so `config push` cannot silently change anything else,
    # and enable_confirmations stays as already chosen.
    (REPO / "supabase" / "config.toml").write_text(
        f'project_id = "{SUPABASE_REF}"\n\n'
        "[auth]\n"
        f'site_url = "{web_url}"\n'
        f'additional_redirect_urls = ["{web_url}", "{web_url}/"]\n'
        "enable_confirmations = false\n"
    )
    result = run(["supabase", "config", "push", "--project-ref", SUPABASE_REF], cwd=REPO, check=False)
    print("  " + (result.stdout or result.stderr).strip()[-300:])

    step("9. production smoke test")
    for label, url in (("frontend", web_url), ("backend", f"{api_url}/health")):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                print(f"  {label:9} HTTP {response.status}  {url}")
        except Exception as error:  # noqa: BLE001
            print(f"  {label:9} FAILED  {url}  {error}")

    flow = Path("/tmp/e2e/prod_flow.mjs")
    if flow.exists():
        print("  running the browser smoke test against production…")
        subprocess.run(["node", str(flow)], env={**os.environ, "APP_URL": web_url}, check=False)

    step("DONE")
    print(f"  frontend: {web_url}")
    print(f"  backend:  {api_url}")


if __name__ == "__main__":
    main()
