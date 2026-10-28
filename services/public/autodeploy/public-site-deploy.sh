#!/usr/bin/env bash
# GitOps deploy of kalik8s.com. Runs inside the `public` container (LXC 104) from public-site-deploy.timer.
#
# Fetches origin/$BRANCH (default main) into a dedicated clone, rebuilds the CVs in the cvgen container and
# syncs services/public/site/ plus the built CVs to the web root with --delete, so the live site is exactly
# the commit. Only data/ (written live by the stats service) is left alone. Does nothing if the commit is
# already deployed, unless FORCE=1. After a deploy it reinstalls itself from the repo.
#
# Installed as /usr/local/sbin/public-site-deploy (see README.md next to it).
set -euo pipefail

main() {
    local repo=/opt/public/repo dest=/opt/public/site state=/opt/public/.deployed-sha
    local url=https://github.com/kalikys/homelab.git branch=${BRANCH:-main}
    local pub=$repo/services/public

    [ -d "$repo/.git" ] || git clone -q "$url" "$repo"
    git -C "$repo" fetch -q origin "$branch"
    local sha
    sha=$(git -C "$repo" rev-parse FETCH_HEAD)
    if [ "$sha" = "$(cat "$state" 2>/dev/null)" ] && [ "${FORCE:-0}" != 1 ]; then
        return 0
    fi
    git -C "$repo" checkout -q --force --detach "$sha"
    git -C "$repo" clean -qfdx -- services/public
    if [ ! -f "$pub/cvgen/Dockerfile" ]; then
        echo "origin/$branch@${sha:0:7} has no cvgen/Dockerfile yet, nothing deployed"
        return 0
    fi

    docker build -q -t public-cvgen "$pub/cvgen" >/dev/null
    docker run --rm -v "$pub/cvgen:/cvgen" public-cvgen >/dev/null

    local stage
    stage=$(mktemp -d)
    trap 'rm -rf "$stage"' RETURN
    rsync -a "$pub/site/" "$stage/"
    cp "$pub"/cvgen/out/Kalislav-Smirnov-CV*.pdf "$stage/"
    mkdir -p "$stage/cv"
    cp "$pub"/cvgen/out/cv/*.pdf "$pub"/cvgen/out/cv/*.txt "$pub"/cvgen/out/cv/*.docx "$stage/cv/"
    chmod -R a+rX "$stage"
    rsync -a --delete --exclude=/data/ "$stage/" "$dest/"

    echo "$sha" > "$state"
    install -m 0755 "$pub/autodeploy/public-site-deploy.sh" /usr/local/sbin/public-site-deploy
    echo "deployed origin/$branch@${sha:0:7}"
}

main "$@"
