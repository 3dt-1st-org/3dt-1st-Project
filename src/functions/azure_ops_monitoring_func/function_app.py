from __future__ import annotations

import hashlib
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass

import azure.functions as func

from monitoring_jobs._common import get_connection
from monitoring_jobs.collect_cost import run as run_collect_cost
from monitoring_jobs.collect_health_metrics import run as run_collect_health_metrics
from monitoring_jobs.collect_log_kpi import run as run_collect_log_kpi
from monitoring_jobs.ingest_stream_kpi import run as run_ingest_stream_kpi
from monitoring_jobs.snapshot_resources import run as run_snapshot_resources


APP = func.FunctionApp()
LOG = logging.getLogger("azure-ops-monitoring-func")

INVENTORY_CRON = os.getenv("MONITORING_INVENTORY_CRON", "0 5 0 * * *")
HEALTH_CRON = os.getenv("MONITORING_HEALTH_CRON", "0 */5 * * * *")
LOG_KPI_CRON = os.getenv("MONITORING_LOG_KPI_CRON", "20 */5 * * * *")
COST_CRON = os.getenv("MONITORING_COST_CRON", "0 */30 * * * *")


@dataclass(frozen=True)
class RuntimeSettings:
    subscription_id: str
    resource_group: str
    log_workspace_id: str
    db_dsn: str
    init_schema: bool
    log_level: str


def _is_truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


EVENTHUB_KPI_ENABLED = _is_truthy(os.getenv("MONITORING_EVENTHUB_KPI_ENABLED", "0"))
EVENTHUB_KPI_NAME = (os.getenv("MONITORING_EVENTHUB_KPI_NAME") or "azure-ops-kpi").strip()
EVENTHUB_KPI_CONSUMER_GROUP = (
    os.getenv("MONITORING_EVENTHUB_KPI_CONSUMER_GROUP") or "ops-realtime-ingest"
).strip()
EVENTHUB_KPI_CONNECTION_SETTING = (
    os.getenv("MONITORING_EVENTHUB_KPI_CONNECTION_SETTING") or "EVENTHUB_KPI_CONNECTION"
).strip()


def _load_settings() -> RuntimeSettings:
    db_dsn = (os.getenv("DB_DSN") or "").strip()
    if not db_dsn:
        raise RuntimeError("DB_DSN is required for Azure Ops monitoring timers.")

    return RuntimeSettings(
        subscription_id=(
            os.getenv("AZ_SUBSCRIPTION_ID")
            or "5bff8a75-037e-4d67-94cf-6fc62202174d"
        ).strip(),
        resource_group=(os.getenv("AZ_RESOURCE_GROUP") or "3dt-1st-team2").strip(),
        log_workspace_id=(
            os.getenv("LOG_ANALYTICS_WORKSPACE_ID")
            or "3a6ae1f6-a887-4b1f-ad70-56f270c974ca"
        ).strip(),
        db_dsn=db_dsn,
        init_schema=_is_truthy(os.getenv("MONITORING_INIT_SCHEMA", "0")),
        log_level=(os.getenv("MONITORING_LOG_LEVEL") or "INFO").strip().upper(),
    )


def _lock_key(lock_name: str) -> int:
    digest = hashlib.sha256(lock_name.encode("utf-8")).digest()
    unsigned = int.from_bytes(digest[:8], "big", signed=False)
    return unsigned - (1 << 64) if unsigned >= (1 << 63) else unsigned


@contextmanager
def _job_lock(db_dsn: str, lock_name: str):
    key = _lock_key(lock_name)
    conn = get_connection(db_dsn)
    acquired = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
            row = cur.fetchone()
            acquired = bool(row and row[0])
        yield acquired
    finally:
        try:
            if acquired:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (key,))
                conn.commit()
        finally:
            conn.close()


def _run_with_lock(lock_name: str, job) -> None:
    settings = _load_settings()
    logging.getLogger().setLevel(getattr(logging, settings.log_level, logging.INFO))

    with _job_lock(settings.db_dsn, lock_name) as acquired:
        if not acquired:
            LOG.warning("Skip %s: advisory lock already held by another worker.", lock_name)
            return
        job(settings)


def _run_inventory(settings: RuntimeSettings) -> None:
    run_snapshot_resources(
        subscription=settings.subscription_id,
        resource_group=settings.resource_group,
        db_dsn=settings.db_dsn,
        init_schema=settings.init_schema,
        dry_run=False,
        print_json=False,
        log_level=settings.log_level,
    )


def _run_health(settings: RuntimeSettings) -> None:
    run_collect_health_metrics(
        subscription=settings.subscription_id,
        resource_group=settings.resource_group,
        db_dsn=settings.db_dsn,
        init_schema=settings.init_schema,
        dry_run=False,
        window_minutes=65,
        log_level=settings.log_level,
    )


def _run_log_kpi(settings: RuntimeSettings) -> None:
    run_collect_log_kpi(
        subscription=settings.subscription_id,
        resource_group=settings.resource_group,
        db_dsn=settings.db_dsn,
        init_schema=settings.init_schema,
        dry_run=False,
        workspace_id=settings.log_workspace_id,
        lookback_minutes=120,
        log_level=settings.log_level,
    )


def _run_cost(settings: RuntimeSettings) -> None:
    run_collect_cost(
        subscription=settings.subscription_id,
        resource_group=settings.resource_group,
        db_dsn=settings.db_dsn,
        init_schema=settings.init_schema,
        dry_run=False,
        log_level=settings.log_level,
    )


@APP.timer_trigger(
    schedule=INVENTORY_CRON,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def monitoring_inventory_timer(timer: func.TimerRequest) -> None:
    if timer.past_due:
        LOG.warning("monitoring_inventory_timer is running late.")
    _run_with_lock("monitoring_inventory", _run_inventory)


@APP.timer_trigger(
    schedule=HEALTH_CRON,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def monitoring_health_timer(timer: func.TimerRequest) -> None:
    if timer.past_due:
        LOG.warning("monitoring_health_timer is running late.")
    _run_with_lock("monitoring_health", _run_health)


@APP.timer_trigger(
    schedule=LOG_KPI_CRON,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def monitoring_log_kpi_timer(timer: func.TimerRequest) -> None:
    if timer.past_due:
        LOG.warning("monitoring_log_kpi_timer is running late.")
    _run_with_lock("monitoring_log_kpi", _run_log_kpi)


@APP.timer_trigger(
    schedule=COST_CRON,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def monitoring_cost_timer(timer: func.TimerRequest) -> None:
    if timer.past_due:
        LOG.warning("monitoring_cost_timer is running late.")
    _run_with_lock("monitoring_cost", _run_cost)


if EVENTHUB_KPI_ENABLED:

    @APP.event_hub_message_trigger(
        arg_name="event",
        event_hub_name=EVENTHUB_KPI_NAME,
        connection=EVENTHUB_KPI_CONNECTION_SETTING,
        consumer_group=EVENTHUB_KPI_CONSUMER_GROUP,
    )
    def monitoring_stream_kpi_eventhub(event: func.EventHubEvent) -> None:
        settings = _load_settings()
        logging.getLogger().setLevel(getattr(logging, settings.log_level, logging.INFO))

        try:
            upserted = run_ingest_stream_kpi(
                db_dsn=settings.db_dsn,
                raw_payload=event.get_body(),
                init_schema=settings.init_schema,
                dry_run=False,
                log_level=settings.log_level,
            )
            LOG.debug("Stream KPI event ingested rows=%d", upserted)
        except Exception:
            LOG.exception("Failed to ingest stream KPI Event Hub message.")
