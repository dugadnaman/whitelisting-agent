from __future__ import annotations

import csv
import io
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from app.config.settings import spreadsheet_identity
from app.core.dependencies import get_report_service, require_machine
from app.models.report import ReportJob
from app.schemas.report_schema import (
    CampaignPreviewResponse, HealthResponse, HistoryResponse, JobResponse,
    MoEngageSessionRequest, MoEngageSessionResponse, SetupRequest, SetupResponse,
    SheetConnectRequest, SheetConnectionResponse, StartJobRequest, StartJobResponse,
)
from app.services.moengage_browser_service import BrowserAutomationError
from app.services.moengage_service import MoEngageError
from app.services.report_service import ReportService


router = APIRouter(dependencies=[Depends(require_machine)])


def ensure_no_active_job(service: ReportService) -> None:
    if service.has_active_work():
        raise HTTPException(status_code=409, detail="Another attribution job is running or cancelling; wait for it to finish")


def ensure_google(service: ReportService) -> None:
    if not service.google.configured:
        raise HTTPException(status_code=503, detail="An administrator must install valid Google service-account credentials")
    if not service.settings.google_spreadsheet_url:
        raise HTTPException(status_code=503, detail="An administrator must configure the approved Apparel sheet")


def google_config_response(service: ReportService) -> dict:
    return {
        "configured": service.google.configured,
        "service_account_email": service.google.service_account_email(),
        "spreadsheet_url": service.settings.google_spreadsheet_url,
        "worksheet_name": service.settings.google_worksheet_name,
    }


def setup_response(service: ReportService) -> SetupResponse:
    return SetupResponse(
        spreadsheet_url=service.settings.google_spreadsheet_url,
        worksheet_name=service.settings.google_worksheet_name,
        ui_config=service.settings.moengage_ui_config,
        google_configured=service.google.configured,
        service_account_email=service.google.service_account_email(),
        browser_login_url=service.settings.moengage_browser_login_url or None,
    )


def session_response(service: ReportService, status: str, message: str) -> MoEngageSessionResponse:
    return MoEngageSessionResponse(
        status=status, message=message, profile_id=service.moengage.active_profile,
        profiles=service.moengage.available_profiles(),
        login_url=service.settings.moengage_browser_login_url or None,
    )


def job_response(job: ReportJob, include_results: bool = True) -> JobResponse:
    return JobResponse(
        job_id=job.id, filename=job.filename, status=job.state.value,
        progress=job.progress, total_rows=job.total_rows, processed_rows=job.processed_rows,
        successful_rows=job.successful_rows, failed_rows=job.failed_rows, skipped_rows=job.skipped_rows,
        current_row=job.current_row, current_brand=job.current_brand, error=job.error,
        download_ready=bool(job.results), created_at=job.created_at,
        started_at=job.started_at, finished_at=job.finished_at,
        results=[asdict(result) for result in job.results[-250:]] if include_results else [],
    )


@router.get("/health", response_model=HealthResponse)
async def health(service: ReportService = Depends(get_report_service)):
    status, _ = await service.moengage.browser.status()
    return HealthResponse(
        status="ok", moengage_mode="browser", configured_brands=service.moengage.configured_brands(),
        google_configured=service.google.configured, moengage_connected=status == "connected",
        mock_writes_enabled=False,
    )


@router.get("/google/config")
async def google_config(service: ReportService = Depends(get_report_service)):
    return google_config_response(service)


@router.get("/setup", response_model=SetupResponse)
async def get_setup(service: ReportService = Depends(get_report_service)):
    return setup_response(service)


@router.put("/setup", response_model=SetupResponse)
async def update_setup(payload: SetupRequest, service: ReportService = Depends(get_report_service)):
    async with service.admission_lock:
        ensure_no_active_job(service)
        try:
            service.settings.persist_setup(payload.spreadsheet_url, payload.worksheet_name, payload.ui_config)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Could not persist setup on the worker /data volume") from exc
        await service.moengage.browser.close()
        service.moengage.browser.ui = service.settings.moengage_ui_config
        service.sheet_connections.clear()
        service.google._worksheet_cache.clear()
        return setup_response(service)


@router.post("/google/credentials")
async def upload_google_credentials(
    credential: UploadFile = File(...), service: ReportService = Depends(get_report_service),
):
    async with service.admission_lock:
        ensure_no_active_job(service)
        if service.settings.sealed_google_credentials:
            raise HTTPException(status_code=409, detail="Google credentials are sealed by deployment configuration. Remove GOOGLE_SERVICE_ACCOUNT_JSON/GOOGLE_SERVICE_ACCOUNT_FILE and restart before installing a durable uploaded key.")
        if not (credential.filename or "").lower().endswith(".json"):
            raise HTTPException(status_code=422, detail="Choose a .json service-account key")
        try:
            content = await credential.read(128 * 1024 + 1)
            service.google.install_credentials(content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Could not persist credentials on the worker /data volume") from exc
        finally:
            await credential.close()
        return google_config_response(service)


@router.post("/google/connect", response_model=SheetConnectionResponse)
async def connect_google_sheet(payload: SheetConnectRequest, service: ReportService = Depends(get_report_service)):
    async with service.admission_lock:
        ensure_google(service)
        try:
            approved = spreadsheet_identity(service.settings.google_spreadsheet_url)
            requested = spreadsheet_identity(payload.spreadsheet_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if requested != approved or payload.worksheet_name != service.settings.google_worksheet_name:
            raise HTTPException(status_code=403, detail="Connect only to the approved Apparel sheet and worksheet; an administrator can change setup")
        try:
            connection = await service.connect_sheet(service.settings.google_spreadsheet_url, service.settings.google_worksheet_name)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Could not connect to the approved sheet. Verify sharing, the worksheet title and required headers.") from exc
        return SheetConnectionResponse(
            connection_id=connection.id, spreadsheet_title=connection.spreadsheet_title,
            worksheet_title=connection.worksheet_title, row_count=connection.row_count,
            brands=connection.brands, channels=connection.channels, campaign_types=connection.campaign_types,
            sent_dates=connection.sent_dates, preview=connection.preview, warnings=connection.warnings,
            warning_sent_date_from=connection.warning_sent_date_from, warning_sent_date_to=connection.warning_sent_date_to,
        )


@router.get("/google/connections/{connection_id}/campaigns", response_model=CampaignPreviewResponse)
async def preview_google_sheet_campaigns(
    connection_id: str, brands: list[str] = Query(default=[]), channels: list[str] = Query(default=[]),
    sent_date: date | None = None, sent_date_from: date | None = None, sent_date_to: date | None = None,
    limit: int = Query(default=100, ge=1, le=250), service: ReportService = Depends(get_report_service),
):
    ensure_google(service)
    if sent_date and (sent_date_from or sent_date_to):
        raise HTTPException(status_code=422, detail="Choose a sent date or range, not both")
    if bool(sent_date_from) != bool(sent_date_to):
        raise HTTPException(status_code=422, detail="Both sent-date range values are required")
    if sent_date_from and sent_date_to and (sent_date_from > sent_date_to or (sent_date_to - sent_date_from).days > 366):
        raise HTTPException(status_code=422, detail="Choose an ordered sent-date range of at most 366 days")
    try:
        count, preview, warnings, warning_from, warning_to = await service.preview_sheet_campaigns(
            connection_id, brands, channels, sent_date, limit, sent_date_from, sent_date_to,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not read the approved Google worksheet") from exc
    return CampaignPreviewResponse(
        row_count=count, preview=preview, warnings=warnings,
        warning_sent_date_from=warning_from, warning_sent_date_to=warning_to,
    )


@router.get("/moengage/session", response_model=MoEngageSessionResponse)
async def moengage_session(service: ReportService = Depends(get_report_service)):
    status, message = await service.moengage.browser.status()
    return session_response(service, status, message)


async def open_session(payload: MoEngageSessionRequest, service: ReportService, reset: bool):
    async with service.admission_lock:
        ensure_no_active_job(service)
        if not service.settings.moengage_remote_cdp_url or not service.settings.moengage_browser_login_url:
            raise HTTPException(status_code=503, detail="Configure private Chromium and its protected HTTPS login URL before opening login")
        try:
            if reset:
                await service.moengage.reset_profile(payload.profile_id)
            else:
                await service.moengage.select_profile(payload.profile_id)
            message = await service.moengage.browser.start_login(payload.profile_id)
        except BrowserAutomationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return session_response(service, "waiting_for_login", message)


@router.post("/moengage/session/start", response_model=MoEngageSessionResponse)
async def start_moengage_session(payload: MoEngageSessionRequest, service: ReportService = Depends(get_report_service)):
    return await open_session(payload, service, False)


@router.post("/moengage/session/reset", response_model=MoEngageSessionResponse)
async def reset_moengage_session(payload: MoEngageSessionRequest, service: ReportService = Depends(get_report_service)):
    return await open_session(payload, service, True)


def ensure_execution(service: ReportService, brands: list[str], target: str | None):
    ensure_google(service)
    if not service.moengage.execution_configured():
        raise HTTPException(status_code=503, detail="Configure private Chromium and genuine MoEngage report mappings before running attribution")
    supported = {brand.casefold() for brand in service.moengage.configured_brands()}
    missing = [brand for brand in brands if brand.casefold() not in supported]
    if missing:
        raise HTTPException(status_code=422, detail="Unsupported report brands: " + ", ".join(missing))
    if any(brand.casefold() == "agipl" for brand in brands):
        if not target or target.strip().casefold() not in supported - {"agipl"}:
            raise HTTPException(status_code=422, detail="Choose an actual supported attribution brand other than AGIPL")


@router.post("/jobs", response_model=StartJobResponse, status_code=202)
async def start_job(payload: StartJobRequest, service: ReportService = Depends(get_report_service)):
    # One lock spans awaited authentication and task creation. A second request
    # cannot observe idle state while the first is still checking the browser.
    async with service.admission_lock:
        ensure_no_active_job(service)
        ensure_execution(service, payload.brands, payload.agipl_attribution_brand)
        try:
            connection = service.sheet_connections.get(payload.sheet_connection_id)
            if not connection:
                raise KeyError("Google Sheet connection not found or server was restarted")
            service.assert_approved_connection(connection)
            await service.moengage.ensure_authenticated()
            job = service.create_sheet_job(
                payload.sheet_connection_id, payload.overwrite_existing, payload.row_limit,
                payload.brands, payload.channels, payload.sent_date,
                payload.sent_date_from, payload.sent_date_to, payload.agipl_attribution_brand,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (BrowserAutomationError, MoEngageError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return StartJobResponse(job_id=job.id, status=job.state.value)


@router.get("/jobs", response_model=HistoryResponse)
async def list_jobs(service: ReportService = Depends(get_report_service)):
    jobs = sorted(service.jobs.values(), key=lambda job: job.created_at, reverse=True)
    return HistoryResponse(jobs=[job_response(job, include_results=False) for job in jobs[:30]])


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, service: ReportService = Depends(get_report_service)):
    try:
        return job_response(service.get_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str, service: ReportService = Depends(get_report_service)):
    async with service.admission_lock:
        try:
            return job_response(await service.cancel_job(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/retry-failed", response_model=StartJobResponse, status_code=202)
async def retry_failed_job(job_id: str, service: ReportService = Depends(get_report_service)):
    async with service.admission_lock:
        ensure_no_active_job(service)
        try:
            original = service.get_job(job_id)
            connection = service.sheet_connections.get(original.upload_id)
            if not connection:
                raise KeyError("Google Sheet connection not found or server was restarted")
            failed = {result.excel_row for result in original.results if result.status == "failed"}
            selected = [row.brand for row in connection.campaigns if row.excel_row in failed]
            ensure_execution(service, selected, original.agipl_attribution_brand)
            await service.moengage.ensure_authenticated()
            job = service.retry_failed_sheet_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (BrowserAutomationError, MoEngageError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return StartJobResponse(job_id=job.id, status=job.state.value)


def csv_cell(value):
    # CSV consumers may open campaign names in Excel. Prevent formula execution.
    return "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value


@router.get("/jobs/{job_id}/results.csv")
async def download_job_results(job_id: str, service: ReportService = Depends(get_report_service)):
    try:
        job = service.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Sheet Row", "Campaign", "Campaign ID", "Brand", "Channel", "Type", "Goal Range", "Status",
        "Unique Users - Total", "Unique Users - Online", "Unique Users - Offline", "Revenue - Total",
        "Revenue - Online", "Revenue - Offline", "Message",
    ])
    for result in job.results:
        values = [
            result.excel_row, result.campaign_name, result.campaign_id, result.brand, result.channel,
            result.campaign_type, result.date_range, result.status, result.unique_users,
            result.online_unique_users, result.offline_unique_users, result.total_revenue,
            result.online_revenue, result.offline_revenue, result.message,
        ]
        writer.writerow([csv_cell(value) if value is not None else "" for value in values])
    return Response(content=output.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="attribution-results-{job.id[:8]}.csv"',
    })
