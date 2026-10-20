#!/usr/bin/env bash
# Deploy kalik8s.com (services/public/site + nginx/default.conf) to LXC 104 from origin/main. Run on the Mac.
#   1. backup of the live site and nginx conf on LXC 104 (/root/public-backup-<time>.tgz)
#   2. site files from `git archive origin/main` (never from a working copy), extracted over the live dir
#      without deleting anything (live-only files such as ads.txt, CV PDFs and data/stats.json stay)
#   3. CV PDFs from kosice-campaign/cv/out (if present)
#   4. nginx conf written in place (keeps the inode of the bind-mounted file), `nginx -t`, reload
#   5. checks against the public URL
set -euo pipefail
cd "$(dirname "$0")/.."
PCT="sudo /usr/sbin/pct"
STAMP=$(date +%Y%m%d-%H%M)
CV_OUT="$HOME/prj/homeserver/kosice-campaign/cv/out"

git fetch -q origin
echo "deploying origin/main @ $(git rev-parse --short origin/main)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git archive origin/main services/public/site services/public/nginx/default.conf | tar -x -C "$TMP"
grep -q 'mission' "$TMP/services/public/site/index.html" || { echo "origin/main has no redesign yet: merge the PR first"; exit 1; }

ssh homeserver "$PCT exec 104 -- tar -C /opt/public -czf /root/public-backup-$STAMP.tgz site nginx/default.conf && echo 'backup: /root/public-backup-$STAMP.tgz on LXC 104'"

COPYFILE_DISABLE=1 tar --no-xattrs -C "$TMP/services/public/site" -czf - . \
  | ssh homeserver "$PCT exec 104 -- tar -xzf - -C /opt/public/site --no-same-owner"
echo "site files: uploaded"

if [ -f "$CV_OUT/Kalislav-Smirnov-CV.pdf" ]; then
  COPYFILE_DISABLE=1 tar --no-xattrs -C "$CV_OUT" -czf - Kalislav-Smirnov-CV.pdf Kalislav-Smirnov-CV-SK.pdf \
    | ssh homeserver "$PCT exec 104 -- tar -xzf - -C /opt/public/site --no-same-owner"
  echo "CV PDFs: uploaded"
fi

ssh homeserver "$PCT exec 104 -- bash -c 'cat > /opt/public/nginx/default.conf.new'" < "$TMP/services/public/nginx/default.conf"
ssh homeserver "$PCT exec 104 -- bash -c 'cat /opt/public/nginx/default.conf.new > /opt/public/nginx/default.conf && rm /opt/public/nginx/default.conf.new && docker exec site nginx -t && docker exec site nginx -s reload && echo nginx: reloaded'"

sleep 2
for u in / /ru/ /sk/ /lab/ /media/launch-169.webp /motion.js /cv.md /Kalislav-Smirnov-CV.pdf; do
  curl -s -o /dev/null -w "%{http_code}  https://kalik8s.com$u\n" "https://kalik8s.com$u?v=$STAMP"
done
curl -s -o /dev/null -w "%{http_code}  /e/reach_payload (expect 204)\n" -X POST "https://kalik8s.com/e/reach_payload?src=deploycheck&lang=en"
page=$(curl -s "https://kalik8s.com/?v=$STAMP")
case "$page" in *"Mission KS"*) echo "live page: new design" ;; *) echo "live page: OLD design still served (cache?)" ;; esac
