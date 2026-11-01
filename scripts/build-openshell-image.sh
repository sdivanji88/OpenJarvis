#!/usr/bin/env bash
# Build the OpenJarvis OpenShell sandbox image (D-041).
#
# Stages the OpenJarvis wheel, a hash-locked requirements file and the Linux
# wheels it needs into deploy/openshell/build/, then has OpenShell build deploy/openshell/ and push
# the image into the gateway's cluster by creating (and deleting) a throwaway
# sandbox. Run this whenever OpenJarvis or uv.lock changes; agent runs never
# build images.
#
#   scripts/build-openshell-image.sh            # stage and build
#   scripts/build-openshell-image.sh --stage    # stage only (for a local podman build)

set -euo pipefail

cd "$(dirname "$0")/.."

CONTEXT=deploy/openshell
BUILD="$CONTEXT/build"

rm -rf "$BUILD"
mkdir -p "$BUILD"
uv build --wheel --out-dir "$BUILD" --quiet
uv export --frozen --no-dev --no-emit-project --no-header --format requirements-txt \
  --output-file "$BUILD/requirements.txt" --quiet
# Download Linux wheels here so the image build needs no network; pip checks
# every wheel against the hashes from uv.lock.
case "${OPENSHELL_ARCH:-$(uname -m)}" in
  arm64 | aarch64) ARCH=aarch64 ;;
  x86_64 | amd64) ARCH=x86_64 ;;
  *) echo "Unsupported architecture; set OPENSHELL_ARCH" >&2; exit 2 ;;
esac
uvx pip download --quiet --require-hashes --only-binary=:all: \
  --python-version 3.12 --implementation cp \
  --platform "manylinux_2_28_$ARCH" --platform "manylinux_2_17_$ARCH" \
  --platform "manylinux2014_$ARCH" --platform "linux_$ARCH" \
  -r "$BUILD/requirements.txt" -d "$BUILD/wheels"
echo "Staged $(ls "$BUILD"/*.whl), $BUILD/requirements.txt and $(ls "$BUILD/wheels" | wc -l | tr -d ' ') $ARCH wheels"

if [ "${1:-}" = "--stage" ]; then
  exit 0
fi

NAME="oj-image-build-$(date +%s)"
trap 'openshell sandbox delete "$NAME" >/dev/null 2>&1 || true' EXIT
LOG="$BUILD/openshell-build.log"
openshell sandbox create --name "$NAME" --from "$CONTEXT" --no-tty --no-auto-providers -- true \
  2>&1 | tee "$LOG"
IMAGE=$(sed 's/\x1b\[[0-9;]*m//g' "$LOG" | grep -o 'openshell/sandbox-from:[0-9]*' | tail -1)
[ -n "$IMAGE" ] || { echo "Could not find the built image tag in $LOG" >&2; exit 1; }
echo
echo "Image ready. Set it in ~/.openjarvis/config.toml:"
echo "  [sandbox]"
echo "  image = \"$IMAGE\""
