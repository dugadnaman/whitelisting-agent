"""Captured HTTP contract regressions; no real credentials or network."""
import asyncio
import copy
import json
import math
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from unittest.mock import patch

import httpx

with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
    "APPAREL_ATTRIBUTION_STORAGE_DIR": directory,
    "APPAREL_GOOGLE_SERVICE_ACCOUNT_FILE": "", "APPAREL_GOOGLE_SERVICE_ACCOUNT_JSON": "",
}):
    from app.config.settings import Settings
    from app.models.report import CampaignMetrics, CampaignRow
    from app.services.moengage_service import (
        APPAREL_ACCOUNT_ID, MoEngageAuthenticationError, MoEngageError, MoEngageService,
        behavior_payload, range_total,
    )


class HttpAttributionTests(unittest.TestCase):
    def setUp(self):
        self.row = CampaignRow(2, date(2026, 10, 3), "VS", "SMS", "Online", "readable-campaign",
                               "A campaign", "3 - 4 Oct", date(2026, 10, 3), date(2026, 10, 4))
        self.config = {"base_url": "https://dashboard-03.moengage.com", "bearer_token": "synthetic-bearer",
                       "refresh_token": "synthetic-refresh", "cookie": ""}
        self.calls, self.payloads = [], []
        self.account = self.profile_account = APPAREL_ACCOUNT_ID
        self.attributes = {"Txn_Channel": {"data_types": ["string"]}, "Order_Net_Val": {"data_types": ["double"]},
                           "Brand_PM": {"data_types": ["array_string"]}, "Txn_Brand": {"data_types": ["string"]}}
        self.state, self.failure = "SUCCESSFUL", None
        self.settings = Settings()

    def provider(self, request):
        path = request.url.path
        self.calls.append(path)
        if self.failure:
            return httpx.Response(self.failure, json={"message": "synthetic-session-secret"})
        if path == "/dash/auth/listApps":
            data = {"code": 200, "status": "success", "loggedIn": False, "data": [
                {"id": "a" * 24, "name": "VS_IN", "account_id": self.account, "activated": True, "is_test": False}]}
        elif path == "/dash/auth/changeApp":
            data = {"code": 200, "status": "success", "data": {"bearer": "bound-bearer", "app_access_details": "ALLOWED"}}
        elif path == "/getLoggedInUserData":
            data = {"data": {"account_id": self.profile_account, "dbName": "VS_IN"}}
        elif path.endswith("/user-event-attrs"):
            data = {"attributes": self.attributes}
        elif path.endswith("/behavior"):
            self.payloads.append(json.loads(request.content))
            data = {"request_id": "b" * 24}
        elif path.endswith("/status"):
            data = {"status": self.state}
        elif path.endswith("/results"):
            query = self.payloads[-1]
            filters = query["events"][0]["actions"][0]["c_at_trigger_seg_v2"]["included_filters"]["filters"][0]["attributes"]["filters"]
            online_buyers = [{"a", "b"}, {"a", "b", "c", "d", "e", "f", "g"}]
            offline_buyers = [{"f", "h", "i"}, {"f", "g", "h", "i", "j"}]
            if not filters:
                buyers = [left | right for left, right in zip(online_buyers, offline_buyers)]
                revenues = [9098, 35726]
            elif filters[0]["negate"]:
                buyers, revenues = offline_buyers, [100, 300]
            else:
                buyers, revenues = online_buyers, [8998, 35426]
            selected = [i for i, day in enumerate(("2026-10-03", "2026-10-04"))
                        if query["timerange"]["start"][:10] <= day <= query["timerange"]["end"][:10]]
            if query["granularity"] == "e":
                value = len(set().union(*(buyers[i] for i in selected))) if query["analysis_type"] == "users" else sum(revenues[i] for i in selected)
                points = [(value, "entire")]
            else:
                points = [(len(buyers[i]) if query["analysis_type"] == "users" else revenues[i], ("2026/10/03", "2026/10/04")[i]) for i in selected]
            data = {"data": [{"metric": value, "granularity": day, "splitby": [], "grouped_by": [],
                              "step": "A", "tseq": 0, "cseq": 0} for value, day in points]}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=data)

    def service(self):
        return MoEngageService(self.settings, session_loader=lambda: self.config,
                               transport=httpx.MockTransport(self.provider))

    def test_whole_range_deduplicates_repeat_days_and_online_offline_overlap(self):
        metrics = asyncio.run(self.service().fetch_metrics(replace(self.row, campaign_type="Overall")))
        self.assertEqual(metrics, CampaignMetrics(10, 44824, 7, 5, 44424, 400))
        self.assertEqual(len(self.payloads), 5)
        for payload in self.payloads:
            delivery = payload["segmentation"][0]["filters"]["included_filters"]["filters"][0]
            self.assertEqual(delivery["action_name"], "SMS_DELIVERED")
            self.assertEqual(delivery["primary_time_range"]["value"], 120)
            self.assertEqual(delivery["attributes"]["filters"][0]["name"], "moe_campaign_id")
            self.assertEqual(delivery["attributes"]["filters"][0]["value"], ["readable-campaign"])
            self.assertEqual(payload["timerange"]["end"], "2026-10-04 23:59:59")


    def test_distinct_purchasers_and_revenue_for_each_type_and_delivery_channel(self):
        for channel in ("SMS", "WhatsApp", "RCS"):
            for kind, expected in (
                ("Online", CampaignMetrics(7, 44424, 7, None, 44424, None)),
                ("Offline", CampaignMetrics(5, 400, None, 5, None, 400)),
                ("Overall", CampaignMetrics(10, 44824, 7, 5, 44424, 400)),
            ):
                with self.subTest(channel=channel, kind=kind):
                    self.assertEqual(asyncio.run(self.service().fetch_metrics(replace(self.row, channel=channel, campaign_type=kind))), expected)

    def test_entire_period_respects_single_day_goal_boundaries(self):
        for day, users, revenue in ((3, 2, 8998), (4, 7, 35426)):
            with self.subTest(day=day):
                row = replace(self.row, start_date=date(2026, 10, day), end_date=date(2026, 10, day))
                self.assertEqual(asyncio.run(self.service().fetch_metrics(row)), CampaignMetrics(users, revenue, users, None, revenue, None))
    def test_foreign_organization_or_workspace_mismatch_never_submits(self):
        for field in ("account", "profile_account"):
            with self.subTest(field=field):
                setattr(self, field, "foreign-organization")
                with self.assertRaises(MoEngageError):
                    asyncio.run(self.service().fetch_metrics(self.row))
                self.assertNotIn("/api/analytics/v4/behavior", self.calls)
                setattr(self, field, APPAREL_ACCOUNT_ID)

    def test_goal_instruction_prefixes_preserve_month_and_year_rollover(self):
        from app.utils.excel_utils import parse_tracking_range
        for text, sent, start, end in (
            ("Track goals from 30th till 02nd Nov", date(2026, 10, 30), date(2026, 10, 30), date(2026, 11, 2)),
            ("Track goals from 30th till 02nd Nov", date(2026, 10, 27), date(2026, 10, 30), date(2026, 11, 2)),
            ("Track goals for 31st to 02nd Jan", date(2026, 12, 31), date(2026, 12, 31), date(2027, 1, 2)),
            ("Track goal: 31st until 1st Mar", date(2024, 2, 28), None, None),
            ("Track goals from 28th till 01st Mar", date(2024, 2, 28), date(2024, 2, 28), date(2024, 3, 1)),
            ("Track goals from 2026-10-30 to 2026-11-02", date(2026, 10, 30), date(2026, 10, 30), date(2026, 11, 2)),
        ):
            with self.subTest(text=text, sent=sent):
                if start is None:
                    with self.assertRaises(ValueError):
                        parse_tracking_range(text, sent)
                else:
                    self.assertEqual(parse_tracking_range(text, sent), (start, end))

    def test_crocs_offline_only_uses_all_purchases_and_overall_has_no_online_share(self):
        for channel in ("SMS", "WhatsApp", "RCS"):
            for kind in ("Offline", "Overall"):
                for classification in ("missing", "present", "malformed"):
                    with self.subTest(channel=channel, kind=kind, classification=classification):
                        self.setUp()
                        self.settings.moengage_ui_config["workspace_map"]["Crocs"] = "VS_IN"
                        if classification == "missing":
                            self.attributes.pop("Txn_Channel")
                        elif classification == "malformed":
                            self.attributes["Txn_Channel"] = None
                        metrics = asyncio.run(self.service().fetch_metrics(replace(self.row, brand="Crocs", channel=channel, campaign_type=kind)))
                        expected = CampaignMetrics(10, 44824, 0, 10, 0, 44824) if kind == "Overall" else CampaignMetrics(10, 44824, None, 10, None, 44824)
                        self.assertEqual(metrics, expected)
                        self.assertEqual(len(self.payloads), 2)
                        for payload in self.payloads:
                            sale = payload["events"][0]["actions"][0]["c_at_trigger_seg_v2"]["included_filters"]["filters"][0]
                            self.assertEqual(sale["attributes"]["filters"], [])

    def test_crocs_online_source_rows_are_rejected_before_provider_requests(self):
        with self.assertRaises(MoEngageError):
            asyncio.run(self.service().fetch_metrics(replace(self.row, brand="Crocs")))
        self.assertEqual(self.calls, [])
        with self.assertRaises(MoEngageError):
            behavior_payload(replace(self.row, brand="Crocs"), "unique_users", self.attributes, {})

    def test_missing_classification_is_not_fabricated_zeroes(self):
        self.attributes.pop("Txn_Channel")
        with self.assertRaises(MoEngageError):
            asyncio.run(self.service().fetch_metrics(self.row))
        self.assertEqual(self.payloads, [])

    def test_special_brand_filters_and_all_delivery_channels(self):
        for channel, event in {"SMS": "SMS_DELIVERED", "WhatsApp": "MOE_WHATSAPP_DELIVERED", "RCS": "MOE_RCS_DELIVERED"}.items():
            payload = behavior_payload(replace(self.row, brand="CIS", channel=channel), "unique_users", self.attributes, {})
            purchase = payload["events"][0]["actions"][0]["c_at_trigger_seg_v2"]["included_filters"]["filters"][0]
            self.assertEqual(purchase["attributes"]["filters"][1]["value"], "SP")
            self.assertEqual(payload["segmentation"][0]["filters"]["included_filters"]["filters"][0]["action_name"], event)
        agipl = replace(self.row, brand="AGIPL", attribution_brand="BBW")
        payload = behavior_payload(agipl, "total_revenue", self.attributes, {"BBW": "BBW"})
        filters = payload["events"][0]["actions"][0]["c_at_trigger_seg_v2"]["included_filters"]["filters"][0]["attributes"]["filters"]
        self.assertEqual((filters[1]["name"], filters[1]["operator"], filters[1]["value"]), ("Txn_Brand", "contains", "BBW"))
        with self.assertRaises(MoEngageError):
            behavior_payload(replace(agipl, attribution_brand="AGIPL"), "unique_users", self.attributes, {"BBW": "BBW"})

    def test_daily_duplicate_split_and_non_numeric_results_are_rejected(self):
        valid = [{"metric": 7, "granularity": "entire", "splitby": [], "grouped_by": [], "step": "A", "tseq": 0, "cseq": 0}]
        invalid = [valid * 2, [], [None], [{"metric": 2, "granularity": "2026/10/03"}]]
        for changes in ({"metric": True}, {"metric": "7"}, {"metric": math.inf}, {"metric": math.nan},
                        {"metric": 1.5}, {"metric": -1}, {"step": "B"}, {"splitby": ["store"]},
                        {"granularity": "2026/10/05"}, {"grouped_by": ["user"]}):
            broken = copy.deepcopy(valid)
            broken[0].update(changes)
            invalid.append(broken)
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(MoEngageError):
                range_total({"data": rows}, "unique_users")

    def test_expired_authentication_and_timeout_never_echo_or_resubmit(self):
        self.failure = 401
        with self.assertRaises(MoEngageAuthenticationError) as error:
            asyncio.run(self.service().fetch_metrics(self.row))
        self.assertNotIn("synthetic-session-secret", str(error.exception))
        self.failure = None
        self.state = "PROCESSING"
        self.settings.moengage_query_timeout_seconds = 0.01
        with self.assertRaises(MoEngageError):
            asyncio.run(self.service().fetch_metrics(self.row))
        self.assertEqual(len(self.payloads), 1)
