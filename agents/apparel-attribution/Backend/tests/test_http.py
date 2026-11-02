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
        behavior_payload, daily_total,
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
            online = not query["events"][0]["actions"][0]["c_at_trigger_seg_v2"]["included_filters"]["filters"][0]["attributes"]["filters"][0]["negate"]
            numbers = ([2, 7] if query["analysis_type"] == "users" else [8998, 35426]) if online else [0, 0]
            data = {"data": [{"metric": value, "granularity": day, "splitby": [], "grouped_by": [],
                              "step": "A", "tseq": 0, "cseq": 0}
                             for day, value in zip(["2026/10/03", "2026/10/04"], numbers)]}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=data)

    def service(self):
        return MoEngageService(self.settings, session_loader=lambda: self.config,
                               transport=httpx.MockTransport(self.provider))

    def test_http_contract_preserves_daily_sums_overall_splits_and_campaign_scope(self):
        metrics = asyncio.run(self.service().fetch_metrics(replace(self.row, campaign_type="Overall")))
        self.assertEqual(metrics, CampaignMetrics(9, 44424, 9, 0, 44424, 0))
        self.assertEqual(len(self.payloads), 4)
        for payload in self.payloads:
            delivery = payload["segmentation"][0]["filters"]["included_filters"]["filters"][0]
            self.assertEqual(delivery["action_name"], "SMS_DELIVERED")
            self.assertEqual(delivery["primary_time_range"]["value"], 120)
            self.assertEqual(delivery["attributes"]["filters"][0]["name"], "moe_campaign_id")
            self.assertEqual(delivery["attributes"]["filters"][0]["value"], ["readable-campaign"])
            self.assertEqual(payload["timerange"]["end"], "2026-10-04 23:59:59")

    def test_foreign_organization_or_workspace_mismatch_never_submits(self):
        for field in ("account", "profile_account"):
            with self.subTest(field=field):
                setattr(self, field, "foreign-organization")
                with self.assertRaises(MoEngageError):
                    asyncio.run(self.service().fetch_metrics(self.row))
                self.assertNotIn("/api/analytics/v4/behavior", self.calls)
                setattr(self, field, APPAREL_ACCOUNT_ID)

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

    def test_partial_duplicate_split_and_non_numeric_results_are_rejected(self):
        valid = [{"metric": 2, "granularity": "2026/10/03", "splitby": [], "grouped_by": [], "step": "A", "tseq": 0, "cseq": 0},
                 {"metric": 7, "granularity": "2026/10/04", "splitby": [], "grouped_by": [], "step": "A", "tseq": 0, "cseq": 0}]
        invalid = [valid[:1], valid + [valid[0]], []]
        for changes in ({"metric": True}, {"metric": "7"}, {"metric": math.inf}, {"metric": math.nan},
                        {"metric": 1.5}, {"metric": -1}, {"step": "B"}, {"splitby": ["store"]},
                        {"granularity": "2026/10/05"}, {"grouped_by": ["user"]}):
            broken = copy.deepcopy(valid)
            broken[1].update(changes)
            invalid.append(broken)
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(MoEngageError):
                daily_total({"data": rows}, self.row, "unique_users")

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
