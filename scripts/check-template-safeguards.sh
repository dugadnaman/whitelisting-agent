#!/bin/sh
set -eu

python -m pytest -q \
  tests/test_connection_check.py \
  tests/test_offline_review_readback.py \
  tests/test_approval_refresh.py \
  tests/test_jira_approval_results.py \
  tests/test_connection_workflow.py \
  tests/test_upload_draft_storage.py \
  tests/test_upload_template_editor.py \
  tests/test_upload_review_edits.py \
  tests/test_jira_connection_workflow.py \
  tests/test_whatsapp_native_upload.py \
  tests/test_dynamic_spreadsheet_loader.py \
  tests/test_loose_cell_templates.py \
  tests/test_loose_sms_cells.py \
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
  tests/test_attached_sheets_and_comments.py \
  tests/test_tcn597_brief_parsing.py \
  tests/test_excel_parser_gaps.py \
  tests/test_client_brief_upload_destination.py \
  tests/test_portal_credential_validation.py \
  tests/test_inventory_contract.py

node --test frontend/lib/tab-state.test.cjs frontend/lib/template-status.test.cjs frontend/lib/whitelisting.test.cjs
