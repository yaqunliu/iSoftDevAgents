#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="${1:?project name required}"
USE_CASE_FILE="${2:?use case file required}"
DIALOG_MAP_FILE="${3:?dialog map file required}"
API_METHODS_FILE="${4:?api methods json required}"
OUTPUT_DIR="${5:?output dir required}"

PAGE_DESC_FILE="${OUTPUT_DIR}/page_descriptions.json"
DAR_FILE="${OUTPUT_DIR}/dar_model.json"

mkdir -p "${OUTPUT_DIR}"

cd "${SCRIPT_DIR}"

python3 page_description.py \
  --project-name "${PROJECT_NAME}" \
  --dialog-map-file "${DIALOG_MAP_FILE}" \
  --api-methods-file "${API_METHODS_FILE}" \
  --output-file "${PAGE_DESC_FILE}"

python3 dar_model.py \
  --page-description-file "${PAGE_DESC_FILE}" \
  --use-case-file "${USE_CASE_FILE}" \
  --output-file "${DAR_FILE}"

python3 ui_design.py \
  --project-name "${PROJECT_NAME}" \
  --page-description-file "${PAGE_DESC_FILE}" \
  --api-methods-file "${API_METHODS_FILE}" \
  --output-dir "${OUTPUT_DIR}/app"
