from __future__ import annotations

import csv
import json
import mimetypes
import threading
import time
import webbrowser
from dataclasses import replace
from datetime import date
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from .data import DATA_ROOT, PACKAGE_ROOT, PRICE_BASIS_ACTUAL, align_price_series, download_all_prices, load_prices, resolve_csv_path
from .comparison import run_previous_high_hold_benchmarks, run_strategy_comparison
from .engine import run_backtest
from .models import BacktestConfig
from .parameter_sweep import run_parameter_sweep
from .precision import decimal, to_primitive
from .previous_high import PreviousHighConfig, run_previous_high_backtest
from .random_compare import run_random_comparison
from .reporting import render_html_report
from .round_analysis import run_round_start_analysis
from .strategy_random import MAX_STRATEGY_RANDOM_SAMPLES, run_strategy_random_comparison


STATIC_ROOT = PACKAGE_ROOT / "static"
RANDOM_JOB_LIMIT = 20
_RANDOM_JOBS: dict[str, dict] = {}
_RANDOM_JOBS_LOCK = threading.Lock()


def _config(payload: dict, fill_model: str | None = None) -> BacktestConfig:
    return BacktestConfig(
        symbol=str(payload.get("symbol", "SOXL")),
        split_count=int(payload.get("split_count", 20)),
        principal=decimal(payload.get("principal", "20000")),
        compounding_type=str(payload.get("compounding_type", "compound")),
        sell_percent=decimal(payload["sell_percent"]) if payload.get("sell_percent") not in (None, "") else None,
        fill_model=fill_model or str(payload.get("fill_model", "intraday_high")),
        initial_entry=str(payload.get("initial_entry", "web_loc")),
        first_buy_buffer_percent=decimal(payload.get("first_buy_buffer_percent", "12")),
        slippage_bps=decimal(payload.get("slippage_bps", "0")),
        commission=decimal(payload.get("commission", "0")),
        sell_fee_bps=decimal(payload.get("sell_fee_bps", "0")),
        annual_risk_free_rate=decimal(payload.get("annual_risk_free_rate", "0")),
    )


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _previous_high_config(payload: dict) -> PreviousHighConfig:
    return PreviousHighConfig(
        principal=decimal(payload.get("principal", "20000")),
        trigger_interval_pct=decimal(payload.get("trigger_interval_pct", "5")),
        divisions=int(payload.get("divisions", 20)),
        fractional_shares=_as_bool(payload.get("fractional_shares")),
        liquidation_offset_pct=decimal(payload.get("liquidation_offset_pct", "0")),
        slippage_bps=decimal(payload.get("slippage_bps", "0")),
        commission=decimal(payload.get("commission", "0")),
        sell_fee_bps=decimal(payload.get("sell_fee_bps", "0")),
        annual_risk_free_rate=decimal(payload.get("annual_risk_free_rate", "0")),
    )


def _load_previous_high_inputs(payload: dict) -> tuple[list, list, dict]:
    start_date = str(payload["start_date"])
    end_date = str(payload["end_date"])
    soxx_path = resolve_csv_path(payload.get("soxx_csv_path"), "SOXX")
    soxl_path = resolve_csv_path(payload.get("soxl_csv_path"), "SOXL")
    soxx_bars, soxx_diagnostics = load_prices(soxx_path, start_date, end_date)
    soxl_bars, soxl_diagnostics = load_prices(soxl_path, start_date, end_date)
    if soxx_diagnostics.get("price_basis") != soxl_diagnostics.get("price_basis"):
        raise ValueError("SOXX와 SOXL 데이터의 가격 기준이 다릅니다. 같은 기준의 CSV를 사용하세요.")
    diagnostics = {
        "SOXX": soxx_diagnostics,
        "SOXL": soxl_diagnostics,
        "requested_start_date": start_date,
        "requested_end_date": end_date,
    }
    return soxx_bars, soxl_bars, diagnostics


def _load_comparison_benchmarks(payload: dict, diagnostics: dict) -> tuple[list, list]:
    start_date = str(payload["start_date"])
    end_date = str(payload["end_date"])
    loaded: dict[str, list] = {}
    expected_basis = diagnostics["SOXX"].get("price_basis")
    for symbol in ("TQQQ", "QLD"):
        path = resolve_csv_path(payload.get(f"{symbol.lower()}_csv_path"), symbol)
        bars, symbol_diagnostics = load_prices(path, start_date, end_date)
        if symbol_diagnostics.get("price_basis") != expected_basis:
            raise ValueError("SOXX·SOXL·TQQQ·QLD 데이터의 가격 기준이 다릅니다. 같은 기준의 CSV를 사용하세요.")
        loaded[symbol] = bars
        diagnostics[symbol] = symbol_diagnostics
    return loaded["TQQQ"], loaded["QLD"]


def _run_payload(payload: dict) -> dict:
    analysis_mode = str(payload.get("analysis_mode", "lth_v4"))
    if analysis_mode not in {"lth_v4", "previous_high", "compare"}:
        raise ValueError("분석 모드는 lth_v4, previous_high, compare 중 하나여야 합니다.")
    if analysis_mode == "lth_v4":
        symbol = str(payload.get("symbol", "SOXL")).upper()
        csv_path = resolve_csv_path(payload.get("csv_path"), symbol)
        bars, diagnostics = load_prices(csv_path, str(payload["start_date"]), str(payload["end_date"]))
        qld_bars = None
        qld_path = resolve_csv_path(payload.get("qld_csv_path"), "QLD")
        if qld_path.exists():
            qld_bars, _ = load_prices(qld_path, str(payload["start_date"]), str(payload["end_date"]))
        config = _config(payload)
        result = run_backtest(config, bars, diagnostics, qld_bars)
        response = to_primitive(result)
        response["schema_version"] = 1
        response["result_type"] = "lth_v4"
        if _as_bool(payload.get("compare_close_only"), True) and config.fill_model == "intraday_high":
            legacy = run_backtest(replace(config, fill_model="close_only"), bars, diagnostics, qld_bars)
            response["fill_model_comparison"] = {
                "close_only_ending_equity": legacy.summary["ending_equity"],
                "close_only_profit_rate": legacy.summary["profit_rate"],
                "intraday_minus_close_equity": decimal(result.summary["ending_equity"]) - decimal(legacy.summary["ending_equity"]),
                "intraday_minus_close_profit_rate": decimal(result.summary["profit_rate"]) - decimal(legacy.summary["profit_rate"]),
                "close_only_completed_rounds": len(legacy.rounds),
            }
        return response

    soxx_bars, soxl_bars, diagnostics = _load_previous_high_inputs(payload)
    previous_config = _previous_high_config(payload)
    if analysis_mode == "previous_high":
        # A single-strategy request stays single-strategy all the way through
        # the engine and report export.  Keep aligned market bars solely for
        # the two selectable candlestick views.
        pairs, _ = align_price_series(soxx_bars, soxl_bars, "SOXX", "SOXL")
        result = run_previous_high_backtest(previous_config, soxx_bars, soxl_bars, diagnostics)
        result["benchmarks"] = run_previous_high_hold_benchmarks(
            previous_config,
            soxx_bars,
            soxl_bars,
            previous_result=result,
            data_diagnostics=diagnostics,
        )
        result["market_data"] = {
            "SOXX": [left for left, _ in pairs],
            "SOXL": [right for _, right in pairs],
        }
    else:
        tqqq_bars, qld_bars = _load_comparison_benchmarks(payload, diagnostics)
        result = run_strategy_comparison(
            previous_config,
            soxx_bars,
            soxl_bars,
            qld_prices=qld_bars,
            tqqq_prices=tqqq_bars,
            v4_split_count=int(payload.get("split_count", 20)),
            v4_compounding_type=str(payload.get("compounding_type", "compound")),
            v4_sell_percent=decimal(payload["sell_percent"]) if payload.get("sell_percent") not in (None, "") else None,
            v4_fill_model=str(payload.get("fill_model", "intraday_high")),
            v4_initial_entry=str(payload.get("initial_entry", "web_loc")),
            v4_first_buy_buffer_percent=decimal(payload.get("first_buy_buffer_percent", "12")),
            result_type="comparison",
            data_diagnostics=diagnostics,
        )
    actual_start = str(result["period"]["start"])
    if actual_start > str(payload["start_date"]):
        result["warnings"].append(
            f"요청 시작일 {payload['start_date']}보다 비교 종목 공통 데이터가 늦어 {actual_start}부터 계산했습니다."
        )
    return to_primitive(result)


def _run_sweep_payload(payload: dict) -> dict:
    soxx_bars, soxl_bars, diagnostics = _load_previous_high_inputs(payload)
    raw_intervals = payload.get("intervals", ["2.5", "3", "4", "5", "6", "7.5", "10"])
    raw_divisions = payload.get("divisions_candidates", payload.get("divisions", [10, 15, 20, 25, 30, 40]))
    if not isinstance(raw_intervals, list) or not isinstance(raw_divisions, list):
        raise ValueError("파라미터 후보는 배열이어야 합니다.")
    base_payload = dict(payload)
    if isinstance(base_payload.get("divisions"), list):
        base_payload["divisions"] = int(base_payload.get("base_divisions", 20))
    return to_primitive(run_parameter_sweep(
        _previous_high_config(base_payload),
        soxx_bars,
        soxl_bars,
        [decimal(value) for value in raw_intervals],
        [int(value) for value in raw_divisions],
        include_subperiods=_as_bool(payload.get("subperiod_validation", True)),
        data_diagnostics=diagnostics,
    ))


def _run_strategy_random_payload(payload: dict, progress_callback=None) -> dict:
    soxx_bars, soxl_bars, diagnostics = _load_previous_high_inputs(payload)
    tqqq_bars, qld_bars = _load_comparison_benchmarks(payload, diagnostics)
    return run_strategy_random_comparison(
        _previous_high_config(payload),
        soxx_bars,
        soxl_bars,
        tqqq_bars,
        qld_bars,
        count=int(payload.get("count", 100)),
        min_days=int(payload.get("min_days", 60)),
        max_days=int(payload["max_days"]) if payload.get("max_days") not in (None, "") else None,
        seed=int(payload["seed"]) if payload.get("seed") not in (None, "") else None,
        uniform_start_sampling=_as_bool(payload.get("uniform_start_sampling")),
        v4_split_count=int(payload.get("split_count", 20)),
        v4_compounding_type=str(payload.get("compounding_type", "compound")),
        v4_sell_percent=decimal(payload["sell_percent"]) if payload.get("sell_percent") not in (None, "") else None,
        v4_fill_model=str(payload.get("fill_model", "intraday_high")),
        v4_initial_entry=str(payload.get("initial_entry", "web_loc")),
        v4_first_buy_buffer_percent=decimal(payload.get("first_buy_buffer_percent", "12")),
        data_diagnostics=diagnostics,
        progress_callback=progress_callback,
    )


def _run_random_payload(payload: dict, progress_callback=None) -> dict:
    if str(payload.get("analysis_mode", "lth_v4")) == "compare":
        return _run_strategy_random_payload(payload, progress_callback)
    csv_dir = Path(payload["csv_dir"]).expanduser() if payload.get("csv_dir") else None
    return run_random_comparison(
        symbols=[str(item) for item in payload.get("symbols", ["TQQQ", "SOXL"])],
        splits=[int(item) for item in payload.get("splits", [20, 40])],
        principal=decimal(payload.get("principal", "20000")),
        start_date=str(payload["start_date"]),
        end_date=str(payload["end_date"]),
        count=int(payload.get("count", 100)),
        min_days=int(payload.get("min_days", 60)),
        max_days=int(payload["max_days"]) if payload.get("max_days") not in (None, "") else None,
        seed=int(payload["seed"]) if payload.get("seed") not in (None, "") else None,
        uniform_start_sampling=_as_bool(payload.get("uniform_start_sampling")),
        csv_dir=csv_dir,
        compounding_type=str(payload.get("compounding_type", "compound")),
        sell_percent=decimal(payload["sell_percent"]) if payload.get("sell_percent") not in (None, "") else None,
        fill_model=str(payload.get("fill_model", "intraday_high")),
        slippage_bps=decimal(payload.get("slippage_bps", "0")),
        commission=decimal(payload.get("commission", "0")),
        sell_fee_bps=decimal(payload.get("sell_fee_bps", "0")),
        progress_callback=progress_callback,
    )


def _update_random_job(job_id: str, completed: int, total: int, context: dict) -> None:
    with _RANDOM_JOBS_LOCK:
        job = _RANDOM_JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "running"
        job["completed"] = max(0, min(int(completed), int(total)))
        job["total"] = max(1, int(total))
        job["phase"] = str(context.get("phase", "backtesting"))
        job["message"] = str(context.get("message", "랜덤 구간을 계산하고 있습니다."))
        job["context"] = {key: value for key, value in context.items() if key not in {"phase", "message"}}


def _run_random_job(job_id: str, payload: dict) -> None:
    try:
        with _RANDOM_JOBS_LOCK:
            job = _RANDOM_JOBS[job_id]
            job["status"] = "running"
            job["phase"] = "loading"
            job["message"] = "가격 데이터와 공통 거래일을 준비하고 있습니다."
            job["started_at"] = time.time()
        result = _run_random_payload(
            payload,
            lambda completed, total, context: _update_random_job(job_id, completed, total, context),
        )
        with _RANDOM_JOBS_LOCK:
            job = _RANDOM_JOBS[job_id]
            job.update({
                "status": "completed",
                "phase": "completed",
                "message": "랜덤 비교가 완료되었습니다.",
                "completed": job["total"],
                "result": result,
                "finished_at": time.time(),
            })
    except Exception as error:
        with _RANDOM_JOBS_LOCK:
            job = _RANDOM_JOBS.get(job_id)
            if job is not None:
                job.update({
                    "status": "failed",
                    "phase": "failed",
                    "message": "랜덤 비교 중 오류가 발생했습니다.",
                    "error": str(error),
                    "finished_at": time.time(),
                })


def _random_job_snapshot(job_id: str) -> dict:
    with _RANDOM_JOBS_LOCK:
        job = _RANDOM_JOBS.get(job_id)
        if job is None:
            raise KeyError("랜덤 비교 작업을 찾을 수 없습니다.")
        snapshot = dict(job)
    now = snapshot.get("finished_at") or time.time()
    started = snapshot.get("started_at") or snapshot["created_at"]
    elapsed = max(0.0, float(now) - float(started))
    completed = int(snapshot.get("completed", 0))
    total = max(1, int(snapshot.get("total", 1)))
    snapshot["progress_pct"] = round(completed / total * 100, 1)
    snapshot["elapsed_seconds"] = round(elapsed, 1)
    snapshot["eta_seconds"] = (
        round(elapsed / completed * (total - completed), 1)
        if snapshot["status"] == "running" and completed > 0 else None
    )
    return to_primitive(snapshot)


def _start_random_job(payload: dict) -> dict:
    count = int(payload.get("count", 100))
    if count <= 0 or count > MAX_STRATEGY_RANDOM_SAMPLES:
        raise ValueError(f"랜덤 샘플 수는 1~{MAX_STRATEGY_RANDOM_SAMPLES:,}이어야 합니다.")
    strategy_comparison = str(payload.get("analysis_mode", "lth_v4")) == "compare"
    combinations = 1 if strategy_comparison else max(1, len(payload.get("symbols", []))) * max(1, len(payload.get("splits", [])))
    job_id = uuid4().hex
    created_at = time.time()
    with _RANDOM_JOBS_LOCK:
        completed_jobs = sorted(
            (item for item in _RANDOM_JOBS.values() if item["status"] in {"completed", "failed"}),
            key=lambda item: item["created_at"],
        )
        while len(_RANDOM_JOBS) >= RANDOM_JOB_LIMIT and completed_jobs:
            _RANDOM_JOBS.pop(completed_jobs.pop(0)["job_id"], None)
        if len(_RANDOM_JOBS) >= RANDOM_JOB_LIMIT:
            raise ValueError("동시에 보관할 수 있는 랜덤 비교 작업 수를 초과했습니다. 실행 중인 작업이 끝난 뒤 다시 시도하세요.")
        _RANDOM_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "phase": "queued",
            "message": "랜덤 비교 작업을 준비하고 있습니다.",
            "completed": 0,
            "total": count * combinations,
            "context": {},
            "created_at": created_at,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }
    threading.Thread(target=_run_random_job, args=(job_id, dict(payload)), daemon=True).start()
    return _random_job_snapshot(job_id)


def _dataset_meta(path: Path) -> dict | None:
    if not path.exists() or path.suffix.lower() != ".csv":
        return None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            date_key = next((key for key in reader.fieldnames or [] if key.strip().lower() == "date"), None)
            if date_key is None:
                return None
            basis_key = next((key for key in reader.fieldnames or [] if key.strip().lower() == "price_basis"), None)
            dates: list[str] = []
            bases: set[str] = set()
            for row in reader:
                if row.get(date_key, "").strip():
                    dates.append(row[date_key].strip())
                if basis_key and row.get(basis_key, "").strip():
                    bases.add(row[basis_key].strip().lower())
            dates.sort()
        if not dates:
            return None
        price_basis = PRICE_BASIS_ACTUAL if bases == {PRICE_BASIS_ACTUAL} else "legacy_or_custom"
        return {"path": str(path), "name": path.name, "rows": len(dates), "start": dates[0], "end": dates[-1], "dates": dates, "price_basis": price_basis}
    except (OSError, csv.Error, UnicodeError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "BackTestV3/3.0.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {self.address_string()} - {format % args}")

    def _json(self, data: object, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(to_primitive(data), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 50_000_000:
            raise ValueError("요청 본문 크기가 올바르지 않습니다.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("JSON 요청을 읽을 수 없습니다.") from error
        if not isinstance(payload, dict):
            raise ValueError("요청은 JSON 객체여야 합니다.")
        return payload

    def _serve_static(self, path_value: str) -> None:
        relative = "index.html" if path_value in {"", "/"} else unquote(path_value.lstrip("/"))
        target = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in target.parents and target != STATIC_ROOT.resolve():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.exists() or not target.is_file():
            target = STATIC_ROOT / "index.html"
        content = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        path_value = urlparse(self.path).path
        if path_value.startswith("/api/random/jobs/"):
            job_id = path_value.rsplit("/", 1)[-1]
            try:
                self._json(_random_job_snapshot(job_id))
            except KeyError as error:
                self._json({"error": str(error.args[0])}, HTTPStatus.NOT_FOUND)
            return
        if path_value == "/api/meta":
            datasets: list[dict] = []
            seen: set[Path] = set()
            for directory in (DATA_ROOT,):
                for path in sorted(directory.glob("*.csv")) if directory.exists() else []:
                    resolved = path.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    item = _dataset_meta(path)
                    if item:
                        datasets.append(item)
            self._json({"today": date.today().isoformat(), "datasets": datasets, "version": "3.0.0"})
            return
        self._serve_static(path_value)

    def do_POST(self) -> None:
        path_value = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path_value == "/api/run":
                self._json(_run_payload(payload))
                return
            if path_value == "/api/parameter-sweep":
                self._json(_run_sweep_payload(payload))
                return
            if path_value == "/api/random/jobs":
                self._json(_start_random_job(payload), HTTPStatus.ACCEPTED)
                return
            if path_value == "/api/random":
                self._json(_run_random_payload(payload))
                return
            if path_value == "/api/round-starts":
                symbol = str(payload.get("symbol", "SOXL")).upper()
                csv_path = resolve_csv_path(payload.get("csv_path"), symbol)
                bars, diagnostics = load_prices(csv_path, str(payload["start_date"]), str(payload["end_date"]))
                result = run_round_start_analysis(_config(payload), bars, diagnostics)
                self._json(result)
                return
            if path_value == "/api/download":
                saved_paths = download_all_prices()
                self._json({
                    "downloaded_at": date.today().isoformat(),
                    "datasets": [_dataset_meta(path) for path in saved_paths],
                })
                return
            if path_value == "/api/report":
                result_payload = payload.get("result")
                if not isinstance(result_payload, dict):
                    raise ValueError("리포트 결과가 없습니다.")
                content = render_html_report(result_payload).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=backtest-v2-report.html")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            self._json({"error": "API 경로를 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
        except (KeyError, TypeError, ValueError, FileNotFoundError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            self._json({"error": f"처리 중 오류가 발생했습니다: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    if not STATIC_ROOT.exists():
        raise FileNotFoundError(f"웹 UI 파일이 없습니다: {STATIC_ROOT}")
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}"
    print(f"BackTest version3: {url}")
    print("종료: Ctrl+C")
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
