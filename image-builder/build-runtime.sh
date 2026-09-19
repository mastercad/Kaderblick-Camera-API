#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT_DIRECTORY=${1:?Ausgabeverzeichnis fehlt}
RUNTIME_NAME=kaderblick-camera-runtime-bookworm-arm64.tar.xz
FILES_DIRECTORY="${REPOSITORY_ROOT}/image-builder/stage-kaderblick/00-runtime/files"
STAGING_DIRECTORY=$(mktemp -d)
trap 'rm -rf "${STAGING_DIRECTORY}"' EXIT

install -d "${OUTPUT_DIRECTORY}" "${STAGING_DIRECTORY}/camera-api"
cp -a "${REPOSITORY_ROOT}/src" "${STAGING_DIRECTORY}/camera-api/src"
find "${STAGING_DIRECTORY}/camera-api/src" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${STAGING_DIRECTORY}/camera-api/src" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
install -m 0644 "${FILES_DIRECTORY}/requirements-image.txt" "${STAGING_DIRECTORY}/"
install -m 0644 "${FILES_DIRECTORY}/camera_service.service" \
  "${FILES_DIRECTORY}/kaderblick_app.service" "${FILES_DIRECTORY}"/*.conf \
  "${FILES_DIRECTORY}"/*.rules "${STAGING_DIRECTORY}/"
install -m 0755 "${FILES_DIRECTORY}/kaderblick-firstboot.py" \
  "${STAGING_DIRECTORY}/kaderblick-firstboot.py"
install -m 0755 "${FILES_DIRECTORY}/install-runtime.sh" \
  "${STAGING_DIRECTORY}/install-runtime.sh"

tar -C "${STAGING_DIRECTORY}" -cJf "${OUTPUT_DIRECTORY}/${RUNTIME_NAME}" .
(
  cd "${OUTPUT_DIRECTORY}"
  sha256sum "${RUNTIME_NAME}" > "${RUNTIME_NAME}.sha256"
)
