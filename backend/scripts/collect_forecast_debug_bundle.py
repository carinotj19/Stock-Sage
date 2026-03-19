from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.db.models import ForecastRun
from app.db.session import SessionLocal
from app.jobs.run_forecast_daily import run_daily_forecast
from app.jobs.run_scraper_cycle import run_scraper_cycle
from app.services.dashboard_service import DashboardService


logging.getLogger("cmdstanpy").setLevel(logging.WARNING)


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def _latest_run_id() -> int:
    with SessionLocal() as db:
        run_id = db.scalar(select(ForecastRun.id).order_by(ForecastRun.id.desc()))
    if run_id is None:
        raise RuntimeError("No forecast runs found. Run the forecast job first.")
    return int(run_id)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _run_plateau_audit(run_id: int, output_csv: Path, output_summary: Path) -> None:
    script_path = Path(__file__).with_name("audit_forecast_plateau.py")
    backend_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(script_path),
        "--run-id",
        str(run_id),
        "--output-csv",
        str(output_csv),
        "--output-summary",
        str(output_summary),
    ]
    try:
        subprocess.run(
            cmd,
            cwd=str(backend_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stdout_tail = "\n".join((exc.stdout or "").splitlines()[-20:])
        stderr_tail = "\n".join((exc.stderr or "").splitlines()[-20:])
        raise RuntimeError(
            "audit_forecast_plateau.py failed.\n"
            f"stdout_tail:\n{stdout_tail}\n"
            f"stderr_tail:\n{stderr_tail}"
        ) from exc


def _run_sales_freshness_backfill(
    *,
    mode: str,
    stale_days: int,
    days: int,
    apply_import: bool,
    replace_prefix: bool,
    output_csv: Path,
) -> None:
    script_path = Path(__file__).with_name("generate_sales_freshness_backfill_csv.py")
    backend_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(script_path),
        "--mode",
        str(mode),
        "--stale-days",
        str(int(stale_days)),
        "--days",
        str(int(days)),
        "--out",
        str(output_csv),
    ]
    if apply_import:
        cmd.append("--apply-import")
    if replace_prefix:
        cmd.append("--replace-prefix")
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(backend_root),
            check=True,
            capture_output=True,
            text=True,
        )
        stdout = (completed.stdout or "").strip()
        if stdout:
            print(stdout)
    except subprocess.CalledProcessError as exc:
        stdout_tail = "\n".join((exc.stdout or "").splitlines()[-20:])
        stderr_tail = "\n".join((exc.stderr or "").splitlines()[-20:])
        raise RuntimeError(
            "generate_sales_freshness_backfill_csv.py failed.\n"
            f"stdout_tail:\n{stdout_tail}\n"
            f"stderr_tail:\n{stderr_tail}"
        ) from exc


def _safe_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{round(float(value), digits)}%"


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float((numerator / denominator) * 100.0)


def _load_summary_map(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _build_markdown_report(
    *,
    run_id: int,
    model_version: str,
    evaluation_days: int,
    window_hours: int,
    forecast_report: dict[str, object],
    scraper_rows: list[dict[str, object]],
    audit_summary: dict[str, object],
) -> str:
    summary = forecast_report.get("summary", {}) or {}
    evaluation_full = forecast_report.get("evaluation_full", {}) or {}
    evaluation_mature = forecast_report.get("evaluation_mature", {}) or {}
    evaluation_non_mature = forecast_report.get("evaluation_non_mature", {}) or {}
    explainability_rows = forecast_report.get("explainability_rows", []) or []
    qa_summary = forecast_report.get("qa_summary")
    qa_report = forecast_report.get("qa_report")

    sku_count = int(summary.get("sku_count") or 0)
    high_conf_summary = summary.get("high_confidence_count")
    high_conf = (
        int(high_conf_summary)
        if isinstance(high_conf_summary, (int, float))
        else sum(
            1
            for row in explainability_rows
            if isinstance(row, dict)
            and isinstance(row.get("confidence_score"), (int, float))
            and float(row["confidence_score"]) >= 0.7
        )
    )
    high_conf_mature = summary.get("high_confidence_mature_count")
    high_conf_non_mature = summary.get("high_confidence_non_mature_count")
    mature_count = summary.get("mature_sku_count")
    non_mature_count = summary.get("non_mature_sku_count")
    gated = sum(
        1
        for row in explainability_rows
        if isinstance(row, dict) and int(row.get("suggested_qty") or 0) <= 0
    )
    baseline_fallback = sum(
        1
        for row in explainability_rows
        if isinstance(row, dict)
        and isinstance(row.get("explanation"), str)
        and "baseline fallback" in row["explanation"].lower()
    )
    avg_conf = summary.get("avg_confidence")
    avg_conf_pct = None if avg_conf is None else round(float(avg_conf) * 100.0, 1)

    matched = int(
        sum(int(row.get("matched_skus_24h") or 0) for row in scraper_rows if isinstance(row, dict))
    )
    total = len(scraper_rows) * sku_count
    scraper_coverage = round(_safe_ratio(matched, total), 1)
    degraded_sources = sum(1 for row in scraper_rows if isinstance(row, dict) and bool(row.get("degraded")))
    stale_sources = sum(1 for row in scraper_rows if isinstance(row, dict) and bool(row.get("stale")))

    computed_reason_counts = audit_summary.get("computed_reason_counts", {}) or {}
    computed_action_counts = audit_summary.get("computed_action_counts", {}) or {}

    top_actionable = []
    for row in explainability_rows:
        if not isinstance(row, dict):
            continue
        qty = int(row.get("suggested_qty") or 0)
        conf = row.get("confidence_score")
        if qty <= 0 or conf is None:
            continue
        top_actionable.append(
            (
                float(conf),
                str(row.get("sku") or ""),
                qty,
                str(row.get("predicted_stockout_date") or "n/a"),
            )
        )
    top_actionable.sort(reverse=True)

    lines: list[str] = []
    lines.append(f"# Forecast Debug Bundle (run_id={run_id})")
    lines.append("")
    lines.append(f"- Generated at (UTC): {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Model version: {model_version}")
    lines.append(f"- Evaluation days: {evaluation_days}")
    lines.append(f"- Scraper window hours: {window_hours}")
    lines.append(f"- Data QA summary: {qa_summary or 'n/a'}")
    lines.append(f"- Data QA report: {qa_report or 'n/a'}")
    lines.append("")
    lines.append("## KPI Snapshot")
    lines.append(
        "- "
        f"full_wmape={_safe_pct(evaluation_full.get('model_wmape_pct'), 2)} | "
        f"mature_wmape={_safe_pct(evaluation_mature.get('model_wmape_pct'), 2)} | "
        f"non_mature_wmape={_safe_pct(evaluation_non_mature.get('model_wmape_pct'), 2)} | "
        f"avg_conf={('n/a' if avg_conf_pct is None else str(avg_conf_pct) + '%')} | "
        f"high_conf={high_conf}/{sku_count} | "
        f"gated={gated}/{sku_count} | "
        f"baseline_fallback={baseline_fallback}/{sku_count} | "
        f"scraper_coverage={scraper_coverage}%"
    )
    lines.append(
        "- "
        f"mature_skus={mature_count if mature_count is not None else 'n/a'} | "
        f"non_mature_skus={non_mature_count if non_mature_count is not None else 'n/a'} | "
        f"high_conf_mature={high_conf_mature if high_conf_mature is not None else 'n/a'} | "
        f"high_conf_non_mature={high_conf_non_mature if high_conf_non_mature is not None else 'n/a'}"
    )
    lines.append(
        f"- Sources: total={len(scraper_rows)} | degraded={degraded_sources} | stale={stale_sources}"
    )
    lines.append("")
    lines.append("## Audit Action Counts")
    if isinstance(computed_action_counts, dict) and computed_action_counts:
        for key in sorted(computed_action_counts):
            lines.append(f"- {key}: {computed_action_counts[key]}")
    else:
        lines.append("- n/a")
    lines.append("")
    lines.append("## Audit Reason Counts")
    if isinstance(computed_reason_counts, dict) and computed_reason_counts:
        for key in sorted(computed_reason_counts):
            lines.append(f"- {key}: {computed_reason_counts[key]}")
    else:
        lines.append("- n/a")
    lines.append("")
    lines.append("## Top Actionable SKUs (qty > 0)")
    if not top_actionable:
        lines.append("- none")
    else:
        for conf, sku, qty, stockout in top_actionable[:10]:
            lines.append(f"- {sku}: qty={qty}, confidence={round(conf, 3)}, stockout={stockout}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a one-command forecast debug bundle (md/json/csv).")
    parser.add_argument("--run-id", type=int, default=None, help="Forecast run id. Defaults to latest run.")
    parser.add_argument(
        "--run-scraper",
        action="store_true",
        help="Run scraper cycle before collecting debug artifacts.",
    )
    parser.add_argument(
        "--scraper-verbose",
        action="store_true",
        help="Verbose scraper logs (effective only with --run-scraper).",
    )
    parser.add_argument(
        "--run-forecast",
        action="store_true",
        help="Run forecast job before collecting debug artifacts.",
    )
    parser.add_argument(
        "--run-sales-backfill",
        action="store_true",
        help="Run sales freshness backfill helper before forecast/debug collection.",
    )
    parser.add_argument(
        "--sales-backfill-mode",
        choices=["template", "synthetic"],
        default="synthetic",
        help="Backfill mode for --run-sales-backfill (default: synthetic).",
    )
    parser.add_argument(
        "--sales-backfill-stale-days",
        type=int,
        default=14,
        help="Stale threshold days for --run-sales-backfill (default: 14).",
    )
    parser.add_argument(
        "--sales-backfill-days",
        type=int,
        default=14,
        help="Number of recent days to backfill for --run-sales-backfill (default: 14).",
    )
    parser.add_argument(
        "--sales-backfill-apply-import",
        action="store_true",
        help="Apply generated sales backfill via import_sales_history_csv.",
    )
    parser.add_argument(
        "--sales-backfill-replace-prefix",
        action="store_true",
        help="When applying backfill import, replace existing rows using same receipt prefix.",
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=30,
        help="Forecast horizon for --run-forecast (default: 30).",
    )
    parser.add_argument(
        "--evaluation-days",
        type=int,
        default=30,
        help="Evaluation window days for forecast report (default: 30).",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=24,
        help="Scraper quality window hours (default: 24).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: backend/data).",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else _default_data_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id

    if args.run_scraper:
        inserted = run_scraper_cycle(verbose=args.scraper_verbose)
        print(f"scraper_rows_inserted={inserted}")

    if args.run_sales_backfill:
        backfill_output_csv = output_dir / "sales_freshness_backfill.latest.csv"
        apply_import = bool(args.sales_backfill_apply_import)
        if str(args.sales_backfill_mode).strip().lower() == "synthetic":
            apply_import = True
        replace_prefix = bool(args.sales_backfill_replace_prefix) or apply_import
        _run_sales_freshness_backfill(
            mode=str(args.sales_backfill_mode).strip().lower(),
            stale_days=max(1, int(args.sales_backfill_stale_days)),
            days=max(1, int(args.sales_backfill_days)),
            apply_import=apply_import,
            replace_prefix=replace_prefix,
            output_csv=backfill_output_csv,
        )

    if args.run_forecast:
        run_id = run_daily_forecast(horizon_days=max(1, int(args.horizon_days)))
        print(f"forecast_run_id={run_id}")

    if run_id is None:
        run_id = _latest_run_id()

    noisy_buffer = io.StringIO()
    with contextlib.redirect_stdout(noisy_buffer), contextlib.redirect_stderr(noisy_buffer):
        with SessionLocal() as db:
            service = DashboardService(db)
            report_obj = service.get_forecast_report(
                include_details=True,
                evaluation_days=max(1, int(args.evaluation_days)),
                run_id=int(run_id),
            )
            scraper_obj = service.get_scraper_source_quality(window_hours=max(1, int(args.window_hours)))

    report_payload = report_obj.model_dump(mode="json")
    scraper_payload = [row.model_dump(mode="json") for row in scraper_obj]

    report_json_path = output_dir / f"forecast_report_run{run_id}.json"
    scraper_json_path = output_dir / f"scraper_source_quality_run{run_id}.json"
    audit_csv_path = output_dir / f"forecast_plateau_audit_run{run_id}.csv"
    audit_summary_path = output_dir / f"forecast_plateau_audit_run{run_id}.summary.json"
    markdown_path = output_dir / f"forecast_debug_bundle_run{run_id}.md"

    _write_json(report_json_path, report_payload)
    _write_json(scraper_json_path, scraper_payload)
    _run_plateau_audit(int(run_id), audit_csv_path, audit_summary_path)
    audit_summary_payload = _load_summary_map(audit_summary_path)

    markdown = _build_markdown_report(
        run_id=int(run_id),
        model_version=str(report_obj.model_version),
        evaluation_days=max(1, int(args.evaluation_days)),
        window_hours=max(1, int(args.window_hours)),
        forecast_report=report_payload,
        scraper_rows=scraper_payload,
        audit_summary=audit_summary_payload,
    )
    markdown_path.write_text(markdown, encoding="utf-8")

    print(f"run_id={run_id}")
    print(f"output_md={markdown_path.resolve()}")
    print(f"output_forecast_json={report_json_path.resolve()}")
    print(f"output_scraper_json={scraper_json_path.resolve()}")
    print(f"output_audit_csv={audit_csv_path.resolve()}")
    print(f"output_audit_summary={audit_summary_path.resolve()}")


if __name__ == "__main__":
    main()
