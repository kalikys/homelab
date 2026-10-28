#!/usr/bin/env bash
# Publish the public CV site to the `public` container (LXC 104) at /opt/public/site.
#
# Source of truth is this git repo: site/ holds the static site, cvgen/ builds the CV PDFs.
# The site PDFs are build artifacts (git-ignored) regenerated here on every deploy, so the
# live site is always reproducible from a clean checkout — no hand-editing on the server.
#
# Run from the Mac (needs Chrome for the PDF build and ssh access to `homeserver`=pve).
#   ./deploy.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"   # services/public
SITE="$HERE/site"
CVGEN="$HERE/cvgen"
REMOTE="${REMOTE:-homeserver}"          # pve host (NOPASSWD sudo -> pct)
CT="${CT:-104}"                         # `public` container
DEST="/opt/public/site"

echo "==> Building CV PDFs from cvgen/ (EN, SK, ENG)"
python3 "$CVGEN/build_cv.py"
OUT="$CVGEN/out"

echo "==> Staging site tree (excluding live/generated: data/, cv/, backups, pdfs)"
STAGE="$(mktemp -d)"
cp -R "$SITE/." "$STAGE/"
rm -rf "$STAGE/data" "$STAGE/cv" "$STAGE"/.bak-* 2>/dev/null || true
find "$STAGE" -maxdepth 1 -name '*.pdf' -delete 2>/dev/null || true
# Ship the freshly built public CVs (the three downloadable variants only).
cp "$OUT/Kalislav-Smirnov-CV.pdf" "$OUT/Kalislav-Smirnov-CV-SK.pdf" "$OUT/Kalislav-Smirnov-CV-Engineering.pdf" "$STAGE/"

echo "==> Shipping to $REMOTE -> CT $CT:$DEST (additive, no deletes)"
TAR="$(mktemp -t sitedeploy).tgz"
tar -C "$STAGE" -czf "$TAR" .
scp -q "$TAR" "$REMOTE:/tmp/sitedeploy.tgz"
ssh "$REMOTE" "sudo -n pct push $CT /tmp/sitedeploy.tgz /tmp/sitedeploy.tgz \
  && sudo -n pct exec $CT -- bash -lc 'mkdir -p $DEST && tar -C $DEST -xzf /tmp/sitedeploy.tgz && rm -f /tmp/sitedeploy.tgz' \
  && rm -f /tmp/sitedeploy.tgz"
rm -f "$TAR"; rm -rf "$STAGE"

echo "==> Done. Live at https://kalik8s.com (CV PDFs regenerated from cvgen/)."
