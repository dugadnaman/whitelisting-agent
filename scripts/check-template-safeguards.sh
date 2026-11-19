#!/bin/sh
set -eu

python -m pytest -q \
  tests/test_whatsapp_native_upload.py \
  tests/test_dynamic_spreadsheet_loader.py \
  tests/test_upload_preview_connectivity.py \
  tests/test_sms_upload_regressions.py \
  tests/test_sms_brief.py \
  tests/test_sms_brief_api.py \
  tests/test_sms_dlt.py \
  tests/test_vilpower_client.py \
  tests/test_whatsapp_media_transport.py \
  tests/test_jira_upload_contract.py \
  tests/test_jira_brief_endpoint.py \
  tests/test_jira_preview_quality.py \
  tests/test_portal_credential_validation.py \
  tests/test_inventory_contract.py
