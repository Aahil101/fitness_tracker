#!/usr/bin/env bash
# Deploy the frontend to Vercel from a clean mirror.
#
# Why a mirror instead of `vercel deploy` in place: frontend/dist-preview is a
# corrupted directory (65535 entries) that hangs any tool which walks it,
# including the Vercel CLI, eslint and even ls. Until the filesystem is repaired
# (reboot, or `diskutil verifyVolume /`), anything that traverses this directory
# has to be run somewhere else.
#
# Why this script rather than copying by hand: doing it by hand copied only src/,
# so vercel.json never reached the deploy. Production therefore ran for weeks
# with no SPA rewrite — every route except / returned a Vercel 404 on refresh or
# a direct link — and without the security headers or the sw.js no-cache rule the
# PWA update flow depends on. Syncing the whole project minus the known-bad
# directories removes the chance to forget a file again.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIRROR="${FE_DEPLOY_DIR:-/tmp/fe-deploy}"

echo "==> mirroring $HERE -> $MIRROR"
mkdir -p "$MIRROR"

# --delete keeps the mirror honest: a file removed from the repo must disappear
# from the deploy too. The excludes cover build output, dependencies, and the
# corrupted directory that is the whole reason this script exists.
rsync -a --delete \
  --exclude 'node_modules/' \
  --exclude 'dist/' \
  --exclude 'dist-preview/' \
  --exclude 'dev-dist/' \
  --exclude '.vercel/' \
  "$HERE"/ "$MIRROR"/

# Fail loudly if the file whose absence caused the 404s is missing again.
for required in vercel.json package.json vite.config.ts index.html; do
  if [[ ! -f "$MIRROR/$required" ]]; then
    echo "!! $required did not reach the mirror — refusing to deploy" >&2
    exit 1
  fi
done
echo "==> mirror complete, required files present"

cd "$MIRROR"
echo "==> vercel deploy --prod"
vercel deploy --prod --yes

cat <<'DONE'

==> verify the SPA rewrite survived, since a missing vercel.json fails silently:
    for p in "" diary analytics fasting coach settings; do
      printf "/%-10s " "$p"
      curl -s -o /dev/null -w "%{http_code}\n" "https://frontend-fitness-575c.vercel.app/$p"
    done
    # every one of these must be 200
DONE
