from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone

from app.config.settings import Settings, spreadsheet_identity
from app.models.report import (
    CampaignRow,
    JobState,
    ReportJob,
    RowResult,
    SheetConnection,
)
from app.services.google_sheet_service import GoogleSheetService, previous_completed_week
from app.services.moengage_service import MoEngageService
from app.services.moengage_browser_service import (
    BrowserAuthenticationError,
    BrowserUnavailableError,
)


logger = logging.getLogger(__name__)
MAX_JOB_HISTORY = 100
MAX_SHEET_CONNECTIONS = 10


class ReportService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.moengage = MoEngageService(settings)
        self.google = GoogleSheetService(
            settings.google_service_account_file,
            settings.google_service_account_json,
        )
        self.sheet_connections: dict[str, SheetConnection] = {}
        self.jobs: dict[str, ReportJob] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.admission_lock = asyncio.Lock()

    def has_active_work(self) -> bool:
        return any(job.state in {JobState.QUEUED, JobState.PROCESSING} for job in self.jobs.values()) or any(
            not task.done() for task in self.tasks.values()
        )

    def assert_approved_connection(self, connection: SheetConnection) -> None:
        if (not self.settings.google_spreadsheet_url
                or connection.spreadsheet_id != spreadsheet_identity(self.settings.google_spreadsheet_url)
                or connection.worksheet_title != self.settings.google_worksheet_name):
            raise ValueError("Reconnect to the approved Apparel sheet and worksheet")

    def _prune_memory(self) -> None:
        pinned = {job.upload_id for job in self.jobs.values()}
        removable = [key for key in self.sheet_connections if key not in pinned]
        while len(self.sheet_connections) > MAX_SHEET_CONNECTIONS and removable:
            self.sheet_connections.pop(removable.pop(0), None)
        terminal_jobs = sorted(
            (
                job for job in self.jobs.values()
                if job.state not in {JobState.QUEUED, JobState.PROCESSING}
            ),
            key=lambda job: job.created_at,
        )
        while len(self.jobs) > MAX_JOB_HISTORY and terminal_jobs:
            oldest_job = terminal_jobs.pop(0)
            self.jobs.pop(oldest_job.id, None)
            self.tasks.pop(oldest_job.id, None)

    async def connect_sheet(self, spreadsheet_url: str, worksheet_name: str) -> SheetConnection:
        warning_sent_date_from, warning_sent_date_to = previous_completed_week()
        spreadsheet, worksheet, rows, warnings = await self.google.connect(
            spreadsheet_url,
            worksheet_name,
            warning_sent_date_from,
            warning_sent_date_to,
        )
        connection_id = uuid.uuid4().hex
        connection = SheetConnection(
            id=connection_id,
            spreadsheet_id=spreadsheet.id,
            spreadsheet_url=spreadsheet_url,
            spreadsheet_title=spreadsheet.title,
            worksheet_title=worksheet.title,
            row_count=len(rows),
            brands=sorted({row.brand for row in rows}),
            channels=sorted({row.channel for row in rows}),
            campaign_types=sorted({row.campaign_type for row in rows}),
            sent_dates=sorted({row.campaign_date for row in rows}, reverse=True),
            preview=[self._campaign_dict(row) for row in rows[:12]],
            campaigns=rows,
            warnings=warnings[:100],
            warning_sent_date_from=warning_sent_date_from,
            warning_sent_date_to=warning_sent_date_to,
        )
        self.sheet_connections[connection_id] = connection
        self._prune_memory()
        return connection

    def create_sheet_job(
        self,
        connection_id: str,
        overwrite_existing: bool,
        row_limit: int | None,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
        agipl_attribution_brand: str | None = None,
    ) -> ReportJob:
        self._prune_memory()
        connection = self.sheet_connections.get(connection_id)
        if not connection:
            raise KeyError("Google Sheet connection not found or server was restarted")
        if self.has_active_work():
            raise ValueError("Another attribution job is still running or cancelling")
        self.assert_approved_connection(connection)
        job_id = uuid.uuid4().hex
        job = ReportJob(
            id=job_id,
            upload_id=connection_id,
            filename=connection.spreadsheet_title,
            agipl_attribution_brand=agipl_attribution_brand,
        )
        self.jobs[job_id] = job
        self._prune_memory()
        self.tasks[job_id] = asyncio.create_task(
            self._process_sheet(
                job, connection, overwrite_existing, row_limit, brands, channels,
                sent_date, sent_date_from, sent_date_to, agipl_attribution_brand,
            )
        )
        return job

    def retry_failed_sheet_job(self, job_id: str) -> ReportJob:
        original = self.get_job(job_id)
        if original.state not in {
            JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED
        }:
            raise ValueError("Wait for the current run to finish before retrying failed campaigns")
        failed_rows = {
            result.excel_row for result in original.results if result.status == "failed"
        }
        if not failed_rows:
            raise ValueError("This run has no failed campaigns to retry")
        connection = self.sheet_connections.get(original.upload_id)
        if not connection:
            raise KeyError("Google Sheet connection not found or server was restarted")
        if self.has_active_work():
            raise ValueError("Another attribution job is still running or cancelling")
        self.assert_approved_connection(connection)
        retry_id = uuid.uuid4().hex
        retry = ReportJob(
            id=retry_id,
            upload_id=original.upload_id,
            filename=f"{original.filename} · failed retry",
            agipl_attribution_brand=original.agipl_attribution_brand,
        )
        self.jobs[retry_id] = retry
        self._prune_memory()
        self.tasks[retry_id] = asyncio.create_task(
            self._process_sheet(
                retry, connection, True, None,
                agipl_attribution_brand=original.agipl_attribution_brand,
                row_numbers=failed_rows,
            )
        )
        return retry

    async def _process_sheet(
        self,
        job: ReportJob,
        connection: SheetConnection,
        overwrite: bool,
        row_limit: int | None,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
        agipl_attribution_brand: str | None = None,
        row_numbers: set[int] | None = None,
    ):
        job.state = JobState.PROCESSING
        job.started_at = datetime.now(timezone.utc)
        try:
            campaigns, _ = await self.google.read_campaigns(connection.spreadsheet_id, connection.worksheet_title)
            campaigns = self._filter_campaigns(
                campaigns, brands, channels, sent_date, sent_date_from, sent_date_to
            )
            if row_numbers is not None:
                campaigns = [
                    campaign for campaign in campaigns
                    if campaign.excel_row in row_numbers
                ]
            if row_limit:
                campaigns = campaigns[:row_limit]
            job.total_rows = len(campaigns)
            requires_browser = any(
                overwrite or not self._has_complete_existing_metrics(campaign)
                for campaign in campaigns
            )
            if requires_browser:
                # Do not create failed row results while Chromium is restarting.
                # A failed preflight leaves the entire job safely retryable.
                await self.moengage.ensure_authenticated()
            for campaign in campaigns:
                if job.state == JobState.CANCELLED:
                    break
                job.current_row, job.current_brand = campaign.excel_row, campaign.brand
                query_campaign = (
                    replace(campaign, attribution_brand=agipl_attribution_brand)
                    if campaign.brand.casefold() == "agipl"
                    else campaign
                )
                result = RowResult(
                    excel_row=campaign.excel_row, brand=campaign.brand, channel=campaign.channel,
                    campaign_type=campaign.campaign_type, campaign_id=campaign.campaign_id,
                    campaign_name=campaign.campaign_name,
                    date_range=f"{campaign.start_date.isoformat()} → {campaign.end_date.isoformat()}", status="processing",
                )
                job.results.append(result)
                authentication_expired = False
                if not overwrite and self._has_complete_existing_metrics(campaign):
                    result.status, result.message = "skipped", "Existing Google Sheet values preserved"
                    self._copy_existing_metrics(result, campaign)
                    job.skipped_rows += 1
                else:
                    try:
                        metrics = await self._fetch_metrics_with_browser_recovery(query_campaign)
                        await self.google.write_metrics(connection.spreadsheet_id, connection.worksheet_title, campaign, metrics)
                        result.status = "success"
                        self._copy_metrics(result, metrics)
                        job.successful_rows += 1
                    except BrowserAuthenticationError as exc:
                        result.status, result.message = "failed", str(exc)
                        job.failed_rows += 1
                        job.state = JobState.FAILED
                        job.error = (
                            "MoEngage login expired. Automation stopped immediately; "
                            "remaining campaigns were not processed. Complete login and rerun "
                            "the same filters with overwrite disabled."
                        )
                        authentication_expired = True
                        logger.warning(
                            "MoEngage login expired at sheet row %s; stopping job %s",
                            campaign.excel_row,
                            job.id,
                        )
                    except Exception as exc:
                        result.status, result.message = "failed", str(exc)
                        job.failed_rows += 1
                        logger.exception(
                            "Campaign row %s failed for brand %s",
                            campaign.excel_row,
                            campaign.brand,
                        )
                job.processed_rows += 1
                if authentication_expired:
                    break
            if job.state not in {JobState.CANCELLED, JobState.FAILED}:
                job.state = JobState.COMPLETED
        except Exception as exc:
            job.state, job.error = JobState.FAILED, str(exc)
            logger.exception("Sheet job %s failed", job.id)
        finally:
            job.current_row = job.current_brand = None
            job.finished_at = datetime.now(timezone.utc)
            self.tasks.pop(job.id, None)


    async def _fetch_metrics_with_browser_recovery(
        self,
        campaign: CampaignRow,
    ):
        """Retry a read-only campaign query after a transient Chromium restart."""
        attempts = max(1, self.settings.moengage_max_retries + 1)
        for attempt in range(attempts):
            try:
                return await self.moengage.fetch_metrics(campaign)
            except BrowserUnavailableError:
                if attempt + 1 >= attempts:
                    raise
                logger.warning(
                    "Railway Chromium unavailable for row %s; waiting before attempt %s/%s",
                    campaign.excel_row,
                    attempt + 2,
                    attempts,
                )
                await self.moengage.wait_until_ready()
        raise AssertionError("Browser recovery loop ended unexpectedly")

    async def shutdown(self) -> None:
        """Finish background cancellation before disconnecting from Chromium."""
        async with self.admission_lock:
            for job_id in list(self.tasks):
                await self.cancel_job(job_id)
            await self.moengage.browser.close()

    async def cancel_job(self, job_id: str) -> ReportJob:
        job = self.get_job(job_id)
        task = self.tasks.get(job_id)
        if job.state in {JobState.QUEUED, JobState.PROCESSING} or (task and not task.done()):
            job.state = JobState.CANCELLED
            if job.results and job.results[-1].status == "processing":
                job.results[-1].status = "failed"
                job.results[-1].message = "Run cancelled before this row completed; reconnect and preserve existing values on rerun"
                job.failed_rows += 1
                job.processed_rows += 1
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.tasks.pop(job_id, None)
            job.current_row = job.current_brand = None
            job.finished_at = datetime.now(timezone.utc)
        return job

    def get_job(self, job_id: str) -> ReportJob:
        if job_id not in self.jobs:
            raise KeyError("Job not found")
        return self.jobs[job_id]

    @staticmethod
    def _copy_metrics(result: RowResult, metrics):
        result.unique_users = metrics.unique_users
        result.total_revenue = metrics.total_revenue
        result.online_unique_users = metrics.online_unique_users
        result.offline_unique_users = metrics.offline_unique_users
        result.online_revenue = metrics.online_revenue
        result.offline_revenue = metrics.offline_revenue

    @staticmethod
    def _copy_existing_metrics(result: RowResult, campaign):
        result.unique_users = int(campaign.existing_unique_users)
        result.total_revenue = float(campaign.existing_revenue)
        result.online_unique_users = (
            int(campaign.existing_online_unique_users)
            if campaign.existing_online_unique_users is not None else None
        )
        result.offline_unique_users = (
            int(campaign.existing_offline_unique_users)
            if campaign.existing_offline_unique_users is not None else None
        )
        result.online_revenue = campaign.existing_online_revenue
        result.offline_revenue = campaign.existing_offline_revenue

    @staticmethod
    def _has_complete_existing_metrics(campaign) -> bool:
        if campaign.existing_unique_users is None or campaign.existing_revenue is None:
            return False
        if campaign.campaign_type == "Overall":
            return all(value is not None for value in (
                campaign.existing_online_unique_users,
                campaign.existing_offline_unique_users,
                campaign.existing_online_revenue,
                campaign.existing_offline_revenue,
            ))
        if campaign.campaign_type == "Online":
            return (
                campaign.existing_online_unique_users is not None
                and campaign.existing_online_revenue is not None
            )
        if campaign.campaign_type == "Offline":
            return (
                campaign.existing_offline_unique_users is not None
                and campaign.existing_offline_revenue is not None
            )
        return False

    @staticmethod
    def _filter_brands(campaigns, brands: list[str] | None):
        allowed = {brand.strip().casefold() for brand in brands or [] if brand.strip()}
        if not allowed:
            return campaigns
        return [campaign for campaign in campaigns if campaign.brand.casefold() in allowed]

    @staticmethod
    def _filter_campaigns(
        campaigns,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
    ):
        selected = ReportService._filter_brands(campaigns, brands)
        allowed_channels = {
            channel.strip().casefold() for channel in channels or [] if channel.strip()
        }
        if allowed_channels:
            selected = [
                campaign
                for campaign in selected
                if campaign.channel.casefold() in allowed_channels
            ]
        if sent_date:
            selected = [
                campaign for campaign in selected if campaign.campaign_date == sent_date
            ]
        else:
            if sent_date_from:
                selected = [
                    campaign for campaign in selected
                    if campaign.campaign_date >= sent_date_from
                ]
            if sent_date_to:
                selected = [
                    campaign for campaign in selected
                    if campaign.campaign_date <= sent_date_to
                ]
        return selected

    async def preview_sheet_campaigns(
        self,
        connection_id: str,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        limit: int = 100,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
    ):
        connection = self.sheet_connections.get(connection_id)
        if not connection:
            raise KeyError("Google Sheet connection not found or server was restarted")
        self.assert_approved_connection(connection)
        warning_from, warning_to = (
            (sent_date, sent_date) if sent_date else
            (sent_date_from, sent_date_to) if sent_date_from and sent_date_to else
            previous_completed_week()
        )
        rows, warnings = await self.google.read_campaigns(
            connection.spreadsheet_id, connection.worksheet_title, warning_from, warning_to,
        )
        campaigns = self._filter_campaigns(rows, brands, channels, sent_date, sent_date_from, sent_date_to)
        return len(campaigns), [self._campaign_dict(row) for row in campaigns[:limit]], warnings[:100], warning_from, warning_to

    @staticmethod
    def _campaign_dict(row):
        return {
            "excel_row": row.excel_row,
            "brand": row.brand,
            "channel": row.channel,
            "campaign_type": row.campaign_type,
            "campaign_id": row.campaign_id,
            "campaign_name": row.campaign_name,
            "sent_date": row.campaign_date.isoformat(),
            "date_range": f"{row.start_date.isoformat()} → {row.end_date.isoformat()}",
        }
