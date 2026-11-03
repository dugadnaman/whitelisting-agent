"""Adversarial consumer scenarios: shared sheets, retries, input boundaries and provider failures."""
import asyncio
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import test_worker as fixtures
import test_http as http_fixtures
from app.config.settings import Settings
from app.models.report import CampaignMetrics, JobState, SheetConnection
from app.services.excel_service import WorkbookValidationError
from app.services.google_sheet_service import GoogleSheetService
from app.services.moengage_service import MoEngageAuthenticationError, MoEngageError, range_total
from app.services.report_service import ReportService
from app.utils.excel_utils import parse_tracking_range


class SharedSheetSafetyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings = Settings(storage_dir=Path(self.folder.name), google_spreadsheet_url=fixtures.SHEET_URL,
                                 google_service_account_file=Path(self.folder.name) / "absent-key.json",
                                 moengage_ui_config=fixtures.UI)
        self.service = ReportService(self.settings)
        self.sheet = fixtures.WorksheetFixture()
        self.service.google._worksheet_cache[(fixtures.SHEET_ID, "Mastersheet")] = self.sheet
        self.rows, _ = self.service.google._read_worksheet(self.sheet)
        self.service.sheet_connections["connection"] = SheetConnection(
            "connection", fixtures.SHEET_ID, fixtures.SHEET_URL, "Verification", "Mastersheet", len(self.rows),
            ["Aldo"], ["WhatsApp", "SMS"], ["Online", "Overall"], [date(2026, 8, 1)], [], campaigns=self.rows)
        self.service.moengage.ensure_authenticated = AsyncMock()
        self.service.moengage.fetch_metrics = AsyncMock(return_value=CampaignMetrics(7, 450, 5, 2, 300, 150))

    def complete_target(self):
        for column, value in enumerate([7, 5, 2, 450, 300, 150], start=8):
            self.sheet.sheet.cell(3, column).value = value

    def run_job(self, **kwargs):
        return self.service.create_sheet_job("connection", kwargs.get("overwrite", False), None,
                                             ["Aldo"], ["SMS"], date(2026, 8, 1))

    def test_changed_campaign_or_moved_row_is_never_written(self):
        async def scenario():
            for mutation in ("id", "insert", "goal"):
                with self.subTest(mutation=mutation):
                    self.sheet = fixtures.WorksheetFixture()
                    self.service.google._worksheet_cache[(fixtures.SHEET_ID, "Mastersheet")] = self.sheet
                    target = self.service.google._read_worksheet(self.sheet)[0][1]
                    if mutation == "id":
                        self.sheet.sheet["G3"] = "a-different-campaign"
                    elif mutation == "insert":
                        self.sheet.sheet.insert_rows(3)
                    else:
                        self.sheet.sheet["F3"] = "2 Aug"
                    with self.assertRaises(WorkbookValidationError):
                        await self.service.google.write_metrics(fixtures.SHEET_ID, "Mastersheet", target,
                                                                CampaignMetrics(7, 450, 5, 2, 300, 150))
                    self.assertEqual(self.sheet.writes, [])
        asyncio.run(scenario())

    def test_values_completed_during_query_are_preserved_without_overwrite(self):
        target = self.rows[1]
        self.complete_target()
        before = list(self.sheet.sheet.values)
        written = asyncio.run(self.service.google.write_metrics(fixtures.SHEET_ID, "Mastersheet", target,
                                                                CampaignMetrics(99, 999, 90, 9, 900, 99)))
        self.assertIsNotNone(written)
        self.assertEqual(written.existing_revenue, 450)
        self.assertEqual(list(self.sheet.sheet.values), before)
        self.assertEqual(self.sheet.writes, [])

    def test_explicit_overwrite_still_replaces_metrics(self):
        target = self.rows[1]
        self.complete_target()
        written = asyncio.run(self.service.google.write_metrics(fixtures.SHEET_ID, "Mastersheet", target,
                                                                CampaignMetrics(9, 600, 5, 4, 350, 250),
                                                                overwrite_existing=True))
        self.assertIsNone(written)
        self.assertEqual([self.sheet.sheet.cell(3, column).value for column in range(8, 14)], [9, 5, 4, 600, 350, 250])

    def test_retry_cannot_query_a_replacement_campaign_at_the_same_row(self):
        async def scenario():
            self.service.moengage.fetch_metrics.side_effect = MoEngageError("Provider failure")
            original = self.run_job()
            await self.service.tasks[original.id]
            self.sheet.sheet["G3"] = "replacement-campaign"
            self.service.moengage.fetch_metrics.reset_mock()
            self.service.moengage.fetch_metrics.side_effect = None
            retry = self.service.retry_failed_sheet_job(original.id)
            await self.service.tasks[retry.id]
            self.service.moengage.fetch_metrics.assert_not_awaited()
            self.assertEqual(self.sheet.writes, [])
            self.assertEqual(retry.state, JobState.FAILED)
        asyncio.run(scenario())

    def test_retry_preserves_results_completed_after_an_ambiguous_failure(self):
        async def scenario():
            self.service.moengage.fetch_metrics.side_effect = MoEngageError("Provider failure")
            original = self.run_job()
            await self.service.tasks[original.id]
            self.complete_target()
            before = list(self.sheet.sheet.values)
            self.service.moengage.fetch_metrics.reset_mock()
            self.service.moengage.fetch_metrics.side_effect = None
            retry = self.service.retry_failed_sheet_job(original.id)
            await self.service.tasks[retry.id]
            self.service.moengage.fetch_metrics.assert_not_awaited()
            self.assertEqual((retry.successful_rows, retry.failed_rows, retry.skipped_rows), (0, 0, 1))
            self.assertEqual(list(self.sheet.sheet.values), before)
        asyncio.run(scenario())

    def test_authentication_expiry_stops_before_remaining_rows(self):
        async def scenario():
            self.sheet.sheet.append(["01/08/2026", "SMS", "Aldo", "Later campaign", "Online", "1 Aug", "later", "", "", "", "", "", ""])
            self.service.moengage.fetch_metrics.side_effect = MoEngageAuthenticationError("Expired")
            job = self.run_job()
            await self.service.tasks[job.id]
            self.assertEqual((job.state, job.total_rows, job.processed_rows, job.failed_rows), (JobState.FAILED, 2, 1, 1))
            self.assertEqual(self.service.moengage.fetch_metrics.await_count, 1)
            self.assertEqual(self.sheet.writes, [])
        asyncio.run(scenario())


class InputBoundaryTests(unittest.TestCase):
    def test_iso_goal_ranges_preserve_both_dates_and_reject_reversed_bounds(self):
        for separator in (" - ", " to ", " – "):
            with self.subTest(separator=separator):
                self.assertEqual(parse_tracking_range("2026-10-03" + separator + "2026-10-04", date(2026, 10, 3)),
                                 (date(2026, 10, 3), date(2026, 10, 4)))
        with self.assertRaises(ValueError):
            parse_tracking_range("2026-10-04 - 2026-10-03", date(2026, 10, 3))

    def test_customer_counts_outside_safe_integer_bounds_are_rejected(self):
        base = {"metric": 0, "granularity": "entire", "splitby": [], "grouped_by": [], "step": "A", "tseq": 0, "cseq": 0}
        for value in (2**53, 10**400):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(MoEngageError):
                range_total({"data": [dict(base, metric=value)]}, "unique_users")

    def test_boolean_series_indices_are_not_accepted_as_zero(self):
        for field in ("tseq", "cseq"):
            base = {"metric": 0, "granularity": "entire", "splitby": [], "grouped_by": [], "step": "A", "tseq": 0, "cseq": 0}
            base[field] = False
            with self.subTest(field=field), self.assertRaises(MoEngageError):
                range_total({"data": [base]}, "unique_users")


class ProviderBoundaryTests(unittest.TestCase):
    def case(self):
        case = http_fixtures.HttpAttributionTests()
        case.setUp()
        return case

    def test_malformed_brand_attribute_metadata_is_a_safe_provider_error(self):
        case = self.case()
        for malformed in (None, [], {"data_types": "string"}, {"data_types": ["double"]}):
            with self.subTest(metadata=malformed), self.assertRaises(MoEngageError):
                attributes = dict(case.attributes, Txn_Brand=malformed)
                http_fixtures.behavior_payload(replace(case.row, brand="AGIPL", attribution_brand="BBW"),
                                               "unique_users", attributes, {"BBW": "BBW"})

    def test_exact_integer_total_at_json_boundary_and_rejection_above_it(self):
        maximum = 2**53 - 1
        point = {"metric": maximum, "granularity": "entire", "splitby": [], "grouped_by": [], "step": "A", "tseq": 0, "cseq": 0}
        self.assertEqual(range_total({"data": [point]}, "unique_users"), maximum)
        point["metric"] = maximum + 1
        with self.assertRaises(MoEngageError):
            range_total({"data": [point]}, "unique_users")

    def test_http_errors_invalid_envelopes_and_unknown_states_never_write_metrics(self):
        import httpx
        for status, body, authentication in (
            (401, {"detail": "private-provider-session"}, True),
            (403, {}, True), (302, {}, True), (429, {}, False), (500, {}, False),
            (200, {"code": 401}, True), (200, {"code": "403"}, True),
            (200, [], False), (200, {"status": []}, False), (200, {"loggedIn": False}, True),
        ):
            case = self.case()
            with self.subTest(status=status, body=body):
                service = case.service()
                service.transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
                expected = MoEngageAuthenticationError if authentication else MoEngageError
                with self.assertRaises(expected) as error:
                    asyncio.run(service.fetch_metrics(case.row))
                self.assertNotIn("private-provider-session", str(error.exception))
                self.assertEqual(case.payloads, [])
        for state in ("FAILED", "CANCELLED", "UNKNOWN"):
            case = self.case()
            case.state = state
            with self.subTest(state=state), self.assertRaises(MoEngageError):
                asyncio.run(case.service().fetch_metrics(case.row))
            self.assertEqual(len(case.payloads), 1)

    def test_iso_source_dates_are_not_reinterpreted_as_day_first(self):
        sheet = fixtures.WorksheetFixture()
        sheet.sheet["A3"] = "2026-10-03"
        sheet.sheet["F3"] = "2026-10-03 - 2026-10-04"
        google = GoogleSheetService(Path("no-test-key"))
        rows, warnings = google._read_worksheet(sheet, date(2026, 10, 3), date(2026, 10, 4))
        target = next(row for row in rows if row.excel_row == 3)
        self.assertEqual((target.campaign_date, target.start_date, target.end_date),
                         (date(2026, 10, 3), date(2026, 10, 3), date(2026, 10, 4)))
