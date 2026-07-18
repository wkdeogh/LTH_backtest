from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from dataclasses import replace
from datetime import date
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .data import DATA_ROOT, PACKAGE_ROOT, download_all_prices, load_prices, resolve_csv_path
from .engine import run_backtest
from .models import BacktestConfig
from .precision import decimal, to_primitive
from .random_compare import run_random_comparison
from .reporting import render_html_report


STATIC_ROOT = PACKAGE_ROOT / "static"


def _config(payload: dict, fill_model: str | None = None) -> BacktestConfig:
    return BacktestConfig(
        symbol=str(payload.get("symbol", "TQQQ")),
        split_count=int(payload.get("split_count", 40)),
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


def _dataset_meta(path: Path) -> dict | None:
    if not path.exists() or path.suffix.lower() != ".csv":
        return None
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            lines = file.readlines()
        if len(lines) < 2:
            return None
        first = lines[1].split(",", 1)[0]
        last = lines[-1].split(",", 1)[0]
        return {"path": str(path), "name": path.name, "rows": len(lines) - 1, "start": first, "end": last}
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "BackTestV2/2.0"

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
            self._json({"today": date.today().isoformat(), "datasets": datasets, "version": "2.0"})
            return
        self._serve_static(path_value)

    def do_POST(self) -> None:
        path_value = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path_value == "/api/run":
                symbol = str(payload.get("symbol", "TQQQ")).upper()
                csv_path = resolve_csv_path(payload.get("csv_path"), symbol)
                bars, diagnostics = load_prices(csv_path, str(payload["start_date"]), str(payload["end_date"]))
                qld_bars = None
                qld_path = resolve_csv_path(payload.get("qld_csv_path"), "QLD")
                if qld_path.exists():
                    qld_bars, _ = load_prices(qld_path, str(payload["start_date"]), str(payload["end_date"]))
                config = _config(payload)
                result = run_backtest(config, bars, diagnostics, qld_bars)
                response = to_primitive(result)
                if payload.get("compare_close_only", True) and config.fill_model == "intraday_high":
                    legacy = run_backtest(replace(config, fill_model="close_only"), bars, diagnostics, qld_bars)
                    response["fill_model_comparison"] = {
                        "close_only_ending_equity": legacy.summary["ending_equity"],
                        "close_only_profit_rate": legacy.summary["profit_rate"],
                        "intraday_minus_close_equity": decimal(result.summary["ending_equity"]) - decimal(legacy.summary["ending_equity"]),
                        "intraday_minus_close_profit_rate": decimal(result.summary["profit_rate"]) - decimal(legacy.summary["profit_rate"]),
                        "close_only_completed_rounds": len(legacy.rounds),
                    }
                self._json(response)
                return
            if path_value == "/api/random":
                csv_dir = Path(payload["csv_dir"]).expanduser() if payload.get("csv_dir") else None
                result = run_random_comparison(
                    symbols=[str(item) for item in payload.get("symbols", ["TQQQ", "SOXL"])],
                    splits=[int(item) for item in payload.get("splits", [20, 40])],
                    principal=decimal(payload.get("principal", "20000")),
                    start_date=str(payload["start_date"]),
                    end_date=str(payload["end_date"]),
                    count=int(payload.get("count", 100)),
                    min_days=int(payload.get("min_days", 60)),
                    max_days=int(payload["max_days"]) if payload.get("max_days") not in (None, "") else None,
                    seed=int(payload["seed"]) if payload.get("seed") not in (None, "") else None,
                    csv_dir=csv_dir,
                    compounding_type=str(payload.get("compounding_type", "compound")),
                    sell_percent=decimal(payload["sell_percent"]) if payload.get("sell_percent") not in (None, "") else None,
                    fill_model=str(payload.get("fill_model", "intraday_high")),
                    slippage_bps=decimal(payload.get("slippage_bps", "0")),
                    commission=decimal(payload.get("commission", "0")),
                    sell_fee_bps=decimal(payload.get("sell_fee_bps", "0")),
                )
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
    print(f"BackTest version2: {url}")
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
