from __future__ import annotations

from app.models.report import CampaignMetrics




class WorkbookValidationError(ValueError):
    pass


class ExcelService:
    INPUT_HEADERS = (
        "Date",
        "Channel",
        "Brand",
        "Campaign Name",
        "Campaign Channel Type",
        "Track Goals for",
        "Campaign ID",
    )
    REQUIRED_HEADERS = {
        "Date",
        "Channel",
        "Brand",
        "Campaign Name",
        "Campaign Channel Type",
        "Track Goals for",
        "Campaign ID",
        "Campaign Purchased Customers",
        "Campaign Purchased Customers - Online",
        "Campaign Purchased Customers - Offline",
        "Influenced Revenue",
        "Influenced Revenue - Online",
        "Influenced Revenue - Offline",
    }

    @staticmethod
    def metric_values(campaign_type: str, metrics: CampaignMetrics) -> dict[str, int | float]:
        """Map totals and channel-type breakdowns to their sheet headers."""
        values: dict[str, int | float] = {
            "Campaign Purchased Customers": metrics.unique_users,
            "Influenced Revenue": metrics.total_revenue,
        }
        if campaign_type == "Overall":
            breakdown = (
                metrics.online_unique_users,
                metrics.offline_unique_users,
                metrics.online_revenue,
                metrics.offline_revenue,
            )
            if any(value is None for value in breakdown):
                raise WorkbookValidationError(
                    "Overall campaign metrics must include online and offline breakdowns"
                )
            values.update({
                "Campaign Purchased Customers - Online": metrics.online_unique_users,
                "Campaign Purchased Customers - Offline": metrics.offline_unique_users,
                "Influenced Revenue - Online": metrics.online_revenue,
                "Influenced Revenue - Offline": metrics.offline_revenue,
            })
        elif campaign_type == "Online":
            values.update({
                "Campaign Purchased Customers - Online": (
                    metrics.online_unique_users
                    if metrics.online_unique_users is not None else metrics.unique_users
                ),
                "Influenced Revenue - Online": (
                    metrics.online_revenue
                    if metrics.online_revenue is not None else metrics.total_revenue
                ),
            })
        elif campaign_type == "Offline":
            values.update({
                "Campaign Purchased Customers - Offline": (
                    metrics.offline_unique_users
                    if metrics.offline_unique_users is not None else metrics.unique_users
                ),
                "Influenced Revenue - Offline": (
                    metrics.offline_revenue
                    if metrics.offline_revenue is not None else metrics.total_revenue
                ),
            })
        else:
            raise WorkbookValidationError(f"Unsupported campaign type {campaign_type!r}")
        return values

