from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Iterable

from .precision import to_primitive


def _price_basis_copy(data: dict) -> str:
    basis = str(
        data.get("config", {}).get("price_basis")
        or data.get("diagnostics", {}).get("resolved_price_basis")
        or data.get("diagnostics", {}).get("price_basis")
        or "unknown"
    )
    if basis == "actual_split_adjusted":
        return "분할 반영·배당 미보정 실제 OHLC 가격수익률"
    return f"입력 CSV OHLC · 가격 기준 {basis} · 조정 여부 미확인"


def write_json(result: object, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_primitive(result), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return path


def _write_csv(rows: Iterable[dict], path: Path) -> Path:
    materialized = [to_primitive(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        if not materialized:
            file.write("")
            return path
        writer = csv.DictWriter(file, fieldnames=list(materialized[0].keys()))
        writer.writeheader()
        writer.writerows(materialized)
    return path


def write_result_csvs(result: object, directory: Path) -> list[Path]:
    data = to_primitive(result)
    directory.mkdir(parents=True, exist_ok=True)
    paths = [
        _write_csv(data.get("executions", []), directory / "executions.csv"),
        _write_csv(data.get("rounds", []), directory / "rounds.csv"),
        _write_csv(data.get("equity_curve", []), directory / "equity_curve.csv"),
        _write_csv(data.get("monthly_returns", []), directory / "monthly_returns.csv"),
    ]
    if data.get("result_type") in {"previous_high", "comparison"}:
        paths.extend([
            _write_csv(data.get("yearly_returns", []), directory / "yearly_returns.csv"),
            _write_csv(data.get("drawdown_buckets", []), directory / "drawdown_buckets.csv"),
            _write_csv(data.get("comparison", {}).get("equity_curve", []), directory / "comparison_equity.csv"),
            _write_csv(data.get("comparison", {}).get("yearly_returns", []), directory / "yearly_comparison.csv"),
        ])
    return paths


def _render_lth_html_report(result: object) -> str:
    data = to_primitive(result)
    summary = data["summary"]
    metrics = data["metrics"]
    config = data["config"]
    period = data["period"]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")

    def money(value: float) -> str:
        return f"${value:,.2f}"

    cards = [
        ("최종 자산", money(summary["ending_equity"])),
        ("총수익률", f"{summary['profit_rate']:+,.2f}%"),
        ("종가 기준 MDD", f"{metrics.get('close_mdd', 0):,.2f}%"),
        ("CAGR", f"{metrics.get('cagr', 0):,.2f}%"),
        ("완료 라운드", f"{summary['completed_rounds']:,}"),
        ("장중 고가 체결", f"{data['diagnostics'].get('intraday_high_only_fills', 0):,}건"),
    ]
    card_html = "".join(f"<article><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></article>" for label, value in cards)
    warning_html = "".join(f"<li>{html.escape(item)}</li>" for item in data.get("warnings", [])) or "<li>경고 없음</li>"
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(config['symbol'])} BackTest version3</title>
<style>
:root{{--bg:#f4f7f5;--panel:#fff;--ink:#15251d;--muted:#617068;--line:#dce5df;--green:#08775b;--red:#c73e3e;--blue:#2463d4}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Arial,"Malgun Gothic",sans-serif}}
header{{padding:28px max(24px,calc((100vw - 1280px)/2));background:#10271f;color:#fff}}h1{{margin:0 0 6px;font-size:28px}}header p{{margin:0;color:#c9d7d1}}
main{{max-width:1280px;margin:auto;padding:22px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}article,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}article span{{display:block;color:var(--muted)}}article strong{{display:block;font-size:23px;margin-top:5px}}.panel{{margin-top:14px}}h2{{font-size:18px;margin:0 0 12px}}canvas{{width:100%;height:340px}}.table{{overflow:auto;max-height:520px}}table{{border-collapse:collapse;width:100%;min-width:920px}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th{{position:sticky;top:0;background:#eef3f0}}td:first-child,th:first-child{{text-align:left}}ul{{margin:0;padding-left:20px}}
</style></head><body>
<header><h1>BackTest version3 · {html.escape(config['symbol'])} {config['split_count']}분할</h1><p>{period['start']} ~ {period['end']} · {period['trading_days']:,}거래일 · {html.escape(config['fill_model'])}</p></header>
<main><section class="cards">{card_html}</section>
<section class="panel"><h2>자산 곡선</h2><canvas id="chart" width="1200" height="340"></canvas></section>
<section class="panel"><h2>주의·가정</h2><ul>{warning_html}</ul></section>
<section class="panel"><h2>완료 라운드</h2><div class="table"><table id="rounds"></table></div></section>
<section class="panel"><h2>체결 내역</h2><div class="table"><table id="executions"></table></div></section></main>
<script>const DATA={payload};
function table(id,rows,keys){{const el=document.getElementById(id);if(!rows.length){{el.innerHTML='<tr><td>데이터 없음</td></tr>';return}}el.innerHTML='<thead><tr>'+keys.map(k=>`<th>${{k}}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+keys.map(k=>`<td>${{r[k]??''}}</td>`).join('')+'</tr>').join('')+'</tbody>'}}
table('rounds',DATA.rounds,['round_number','started_at','ended_at','starting_equity','ending_equity','profit_rate','close_mdd','benchmark_profit_rate','mdd_peak_date','mdd_trough_date','execution_count']);
table('executions',DATA.executions,['sequence','date','side','order_type','label','order_price','fill_price','quantity','gross_amount','fees','t_before','t_after']);
const c=document.getElementById('chart'),x=c.getContext('2d'),p=DATA.equity_curve,hasQld=p.some(v=>v.qld_benchmark_equity!=null),vals=p.flatMap(v=>hasQld?[v.equity,v.benchmark_equity,v.qld_benchmark_equity]:[v.equity,v.benchmark_equity]),lo=Math.min(...vals),hi=Math.max(...vals),pad=34;
x.clearRect(0,0,c.width,c.height);x.strokeStyle='#dce5df';for(let i=0;i<5;i++){{let y=pad+(c.height-pad*2)*i/4;x.beginPath();x.moveTo(pad,y);x.lineTo(c.width-pad,y);x.stroke()}}
function line(key,color){{x.strokeStyle=color;x.lineWidth=2.5;x.beginPath();p.forEach((v,i)=>{{let px=pad+(c.width-pad*2)*i/Math.max(p.length-1,1),py=c.height-pad-(v[key]-lo)/Math.max(hi-lo,1)*(c.height-pad*2);i?x.lineTo(px,py):x.moveTo(px,py)}});x.stroke()}}line('equity','#08775b');line('benchmark_equity','#2463d4');if(hasQld)line('qld_benchmark_equity','#d18a18');
</script></body></html>"""


def _render_previous_high_single_html_report(result: object) -> str:
    """Render the public previous-high result without comparison-only fields."""
    data = to_primitive(result)
    summary = data["summary"]
    metrics = data["metrics"]
    strategy_metrics = data["strategy_metrics"]
    period = data["period"]
    price_basis_copy = html.escape(_price_basis_copy(data))
    config = data["config"]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")

    def money(value: float) -> str:
        return f"${value:,.2f}"

    cards = [
        ("최종 자산", money(summary["ending_equity"])),
        ("총수익률", f"{summary['profit_rate']:+,.2f}%"),
        ("CAGR", f"{metrics.get('cagr', 0):,.2f}%"),
        ("종가 MDD", f"{metrics.get('close_mdd', 0):,.2f}%"),
        ("최대 SOXL 비중", f"{strategy_metrics.get('max_soxl_weight', 0):,.2f}%"),
        ("최대 실질 레버리지", f"{strategy_metrics.get('max_effective_leverage', 0):,.3f}×"),
    ]
    card_html = "".join(
        f"<article><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></article>"
        for label, value in cards
    )
    warning_html = "".join(f"<li>{html.escape(item)}</li>" for item in data.get("warnings", [])) or "<li>경고 없음</li>"
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>전고점매매법 백테스트 리포트</title><style>
:root{{--bg:#f4f7f5;--panel:#fff;--ink:#15251d;--muted:#617068;--line:#dce5df;--green:#08775b;--red:#c43e45}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 Arial,"Malgun Gothic",sans-serif}}header{{padding:28px max(24px,calc((100vw - 1380px)/2));background:#10271f;color:#fff}}h1{{margin:0 0 6px;font-size:27px}}header p{{margin:0;color:#c9d7d1}}main{{max-width:1380px;margin:auto;padding:22px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}article,.panel{{background:#fff;border:1px solid var(--line);border-radius:11px;padding:15px}}article span{{display:block;color:var(--muted)}}article strong{{display:block;font-size:21px;margin-top:5px}}.panel{{margin-top:14px}}h2{{font-size:17px;margin:0 0 11px}}canvas{{display:block;width:100%;height:360px}}.table{{overflow:auto;max-height:560px}}table{{border-collapse:collapse;width:100%;min-width:940px}}th,td{{padding:8px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th{{background:#eef3f0}}thead th{{position:sticky;top:0}}th:first-child,td:first-child{{text-align:left}}ul{{margin:0;padding-left:20px}}
</style></head><body><header><h1>전고점매매법 백테스트</h1><p>{period['start']} ~ {period['end']} · {period['trading_days']:,} 공통 거래일 · {config['trigger_interval_pct']:g}% 간격 × {config['divisions']}분할 · {price_basis_copy}</p></header><main>
<section class="cards">{card_html}</section>
<section class="panel"><h2>전고점매매법 자산곡선</h2><canvas id="equity" width="1300" height="360"></canvas></section>
<section class="panel"><h2>SOXL 비중과 실질 레버리지</h2><canvas id="exposure" width="1300" height="360"></canvas></section>
<section class="panel"><h2>낙폭별 포트폴리오 구조</h2><div class="table"><table id="buckets"></table></div></section>
<section class="panel"><h2>전고점 라운드</h2><div class="table"><table id="rounds"></table></div></section>
<section class="panel"><h2>전환 매매 로그</h2><div class="table"><table id="executions"></table></div></section>
<section class="panel"><h2>가정과 주의사항</h2><ul>{warning_html}</ul></section></main>
<script>const DATA={payload};
function table(id,rows,keys){{const el=document.getElementById(id);if(!rows.length){{el.innerHTML='<tr><td>데이터 없음</td></tr>';return}}el.innerHTML='<thead><tr>'+keys.map(k=>`<th>${{k}}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+keys.map(k=>`<td>${{Array.isArray(r[k])?r[k].join(', '):(r[k]??'')}}</td>`).join('')+'</tr>').join('')+'</tbody>'}}
table('rounds',DATA.rounds,['round_id','start_date','end_date','duration_trading_days','recovery_trading_days','start_peak','start_portfolio_value','end_portfolio_value','return_pct','max_soxx_drawdown','max_portfolio_drawdown','max_loss_from_start','max_soxl_weight','max_effective_leverage','number_of_conversion_steps']);
table('executions',DATA.executions,['sequence','date','round_id','action','trigger_steps','execution_type','soxx_price','soxx_shares_before','soxx_shares_after','soxl_price','soxl_shares_before','soxl_shares_after','cash','fees']);
table('buckets',DATA.drawdown_buckets,['bucket','trading_days','avg_soxx_weight','avg_soxl_weight','avg_cash_weight','avg_effective_leverage','avg_portfolio_return']);
const rows=DATA.equity_curve;
function chart(id,series){{const c=document.getElementById(id),x=c.getContext('2d'),pad=40,values=rows.flatMap(r=>series.map(s=>Number(r[s[0]]))),lo=Math.min(0,...values),hi=Math.max(...values,1);x.clearRect(0,0,c.width,c.height);x.strokeStyle='#dce5df';for(let i=0;i<5;i++){{const y=pad+(c.height-pad*2)*i/4;x.beginPath();x.moveTo(pad,y);x.lineTo(c.width-pad,y);x.stroke()}}series.forEach(([key,color])=>{{x.strokeStyle=color;x.lineWidth=2;x.beginPath();rows.forEach((r,i)=>{{const px=pad+(c.width-pad*2)*i/Math.max(rows.length-1,1),py=c.height-pad-(Number(r[key])-lo)/Math.max(hi-lo,1)*(c.height-pad*2);i?x.lineTo(px,py):x.moveTo(px,py)}});x.stroke()}})}}
chart('equity',[['equity','#08775b']]);chart('exposure',[['soxl_weight','#c43e45'],['effective_leverage','#08775b']]);
</script></body></html>"""


def _render_previous_high_comparison_html_report(result: object) -> str:
    data = to_primitive(result)
    summary = data["summary"]
    metrics = data["metrics"]
    strategy_metrics = data["strategy_metrics"]
    period = data["period"]
    comparison = data["comparison"]
    comparison_name = "4전략 + QLD 거치식" if "qld_buy_hold" in comparison["strategy_order"] else "4전략"
    price_basis_copy = html.escape(_price_basis_copy(data))
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")

    def money(value: float) -> str:
        return f"${value:,.2f}"

    cards = [
        ("전고점 전략 최종 자산", money(summary["ending_equity"])),
        ("총수익률", f"{summary['profit_rate']:+,.2f}%"),
        ("CAGR", f"{metrics.get('cagr', 0):,.2f}%"),
        ("종가 MDD", f"{metrics.get('close_mdd', 0):,.2f}%"),
        ("최대 SOXL 비중", f"{strategy_metrics.get('max_soxl_weight', 0):,.2f}%"),
        ("최대 실질 레버리지", f"{strategy_metrics.get('max_effective_leverage', 0):,.3f}×"),
    ]
    card_html = "".join(
        f"<article><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></article>"
        for label, value in cards
    )
    strategy_headers = "".join(
        f"<th>{html.escape(comparison['strategies'][key]['label'])}</th>"
        for key in comparison["strategy_order"]
    )
    metric_rows = []
    for key, label, suffix in (
        ("ending_equity", "최종 평가금액", "$"),
        ("total_return", "총수익률", "%"),
        ("cagr", "CAGR", "%"),
        ("close_mdd", "MDD", "%"),
        ("calmar_ratio", "CAGR / |MDD|", ""),
        ("annual_volatility", "연환산 변동성", "%"),
        ("sharpe_ratio", "Sharpe", ""),
        ("sortino_ratio", "Sortino", ""),
    ):
        values = []
        for strategy_key in comparison["strategy_order"]:
            strategy = comparison["strategies"][strategy_key]
            value = strategy["summary"].get(key) if key == "ending_equity" else strategy["metrics"].get(key)
            if suffix == "$":
                values.append(f"<td>{money(value)}</td>")
            else:
                values.append(f"<td>{value:,.3f}{suffix}</td>")
        metric_rows.append(f"<tr><th>{html.escape(label)}</th>{''.join(values)}</tr>")
    warning_html = "".join(f"<li>{html.escape(item)}</li>" for item in data.get("warnings", []))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>전고점매매법 · {comparison_name} 비교 리포트</title><style>
:root{{--bg:#f4f7f5;--panel:#fff;--ink:#15251d;--muted:#617068;--line:#dce5df;--green:#08775b}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 Arial,"Malgun Gothic",sans-serif}}header{{padding:28px max(24px,calc((100vw - 1380px)/2));background:#10271f;color:#fff}}h1{{margin:0 0 6px;font-size:27px}}header p{{margin:0;color:#c9d7d1}}main{{max-width:1380px;margin:auto;padding:22px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}article,.panel{{background:#fff;border:1px solid var(--line);border-radius:11px;padding:15px}}article span{{display:block;color:var(--muted)}}article strong{{display:block;font-size:21px;margin-top:5px}}.panel{{margin-top:14px}}h2{{font-size:17px;margin:0 0 11px}}canvas{{display:block;width:100%;height:360px}}.table{{overflow:auto;max-height:560px}}table{{border-collapse:collapse;width:100%;min-width:940px}}th,td{{padding:8px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th{{background:#eef3f0}}thead th{{position:sticky;top:0}}th:first-child,td:first-child{{text-align:left}}ul{{margin:0;padding-left:20px}}.legend{{display:flex;gap:16px;margin-bottom:8px;color:var(--muted)}}.legend i{{display:inline-block;width:14px;height:3px;margin-right:5px;vertical-align:middle}}
</style></head><body><header><h1>전고점매매법 · {comparison_name} 비교</h1><p>{period['start']} ~ {period['end']} · {period['trading_days']:,} 공통 거래일 · {price_basis_copy}</p></header><main>
<section class="cards">{card_html}</section>
<section class="panel"><h2>핵심 성과 비교</h2><div class="table"><table><thead><tr><th>지표</th>{strategy_headers}</tr></thead><tbody>{''.join(metric_rows)}</tbody></table></div></section>
<section class="panel"><h2>{comparison_name} 자산곡선</h2><div class="legend" id="legend"></div><canvas id="equity" width="1300" height="360"></canvas></section>
<section class="panel"><h2>{comparison_name} 종가 낙폭</h2><canvas id="drawdown" width="1300" height="360"></canvas></section>
<section class="panel"><h2>SOXL 비중과 실질 레버리지</h2><canvas id="exposure" width="1300" height="360"></canvas></section>
<section class="panel"><h2>낙폭별 포트폴리오 구조</h2><div class="table"><table id="buckets"></table></div></section>
<section class="panel"><h2>전고점 라운드</h2><div class="table"><table id="rounds"></table></div></section>
<section class="panel"><h2>전환 매매 로그</h2><div class="table"><table id="executions"></table></div></section>
<section class="panel"><h2>가정과 주의사항</h2><ul>{warning_html}</ul></section></main>
<script>const DATA={payload};
function table(id,rows,keys){{const el=document.getElementById(id);if(!rows.length){{el.innerHTML='<tr><td>데이터 없음</td></tr>';return}}el.innerHTML='<thead><tr>'+keys.map(k=>`<th>${{k}}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+keys.map(k=>`<td>${{Array.isArray(r[k])?r[k].join(', '):(r[k]??'')}}</td>`).join('')+'</tr>').join('')+'</tbody>'}}
table('rounds',DATA.rounds,['round_id','start_date','end_date','duration_trading_days','recovery_trading_days','start_peak','start_portfolio_value','end_portfolio_value','return_pct','max_soxx_drawdown','max_portfolio_drawdown','max_loss_from_start','max_soxl_weight','max_effective_leverage','number_of_conversion_steps']);
table('executions',DATA.executions,['sequence','date','round_id','action','trigger_steps','execution_type','soxx_price','soxx_shares_before','soxx_shares_after','soxl_price','soxl_shares_before','soxl_shares_after','cash','fees']);
table('buckets',DATA.drawdown_buckets,['bucket','trading_days','avg_soxx_weight','avg_soxl_weight','avg_cash_weight','avg_effective_leverage','avg_portfolio_return']);
const order=DATA.comparison.strategy_order,strategies=DATA.comparison.strategies,rows=DATA.comparison.equity_curve;
document.getElementById('legend').innerHTML=order.map(k=>`<span><i style="background:${{strategies[k].color}}"></i>${{strategies[k].label}}</span>`).join('');
function chart(id,keys,valueKey){{const c=document.getElementById(id),x=c.getContext('2d'),pad=40,values=rows.flatMap(r=>keys.map(k=>Number(r[valueKey(k)]))),lo=Math.min(...values),hi=Math.max(...values);x.clearRect(0,0,c.width,c.height);x.strokeStyle='#dce5df';for(let i=0;i<5;i++){{const y=pad+(c.height-pad*2)*i/4;x.beginPath();x.moveTo(pad,y);x.lineTo(c.width-pad,y);x.stroke()}}keys.forEach(k=>{{x.strokeStyle=strategies[k].color;x.lineWidth=2;x.beginPath();rows.forEach((r,i)=>{{const px=pad+(c.width-pad*2)*i/Math.max(rows.length-1,1),py=c.height-pad-(Number(r[valueKey(k)])-lo)/Math.max(hi-lo,1)*(c.height-pad*2);i?x.lineTo(px,py):x.moveTo(px,py)}});x.stroke()}})}}
chart('equity',order,k=>k);chart('drawdown',order,k=>k+'_drawdown');
const exposureRows=DATA.equity_curve;function exposure(){{const c=document.getElementById('exposure'),x=c.getContext('2d'),pad=40,series=[['soxl_weight','#c43e45'],['effective_leverage','#08775b']];x.clearRect(0,0,c.width,c.height);series.forEach(([k,color])=>{{const vals=exposureRows.map(r=>Number(r[k])),lo=Math.min(0,...vals),hi=Math.max(...vals,1);x.strokeStyle=color;x.lineWidth=2;x.beginPath();exposureRows.forEach((r,i)=>{{const px=pad+(c.width-pad*2)*i/Math.max(exposureRows.length-1,1),py=c.height-pad-(Number(r[k])-lo)/Math.max(hi-lo,1)*(c.height-pad*2);i?x.lineTo(px,py):x.moveTo(px,py)}});x.stroke()}})}}exposure();
</script></body></html>"""


def render_html_report(result: object) -> str:
    data = to_primitive(result)
    if data.get("result_type") == "comparison" or data.get("comparison"):
        return _render_previous_high_comparison_html_report(data)
    if data.get("result_type") == "previous_high":
        return _render_previous_high_single_html_report(data)
    return _render_lth_html_report(data)


def write_html_report(result: object, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html_report(result), encoding="utf-8")
    return path


def render_random_html_report(result: object) -> str:
    data = to_primitive(result)
    config = data["config"]
    cards = "".join(
        f"""<article><h2>{html.escape(item['symbol'])} · {item['split_count']}분할</h2>
        <strong class="{'positive' if item['avg_strategy_profit_rate'] >= 0 else 'negative'}">{item['avg_strategy_profit_rate']:+,.2f}%</strong>
        <dl><div><dt>거치식 대비</dt><dd>{item['avg_excess_vs_hold']:+,.2f}%p</dd></div>
        <div><dt>QLD 대비</dt><dd>{item['avg_excess_vs_qld']:+,.2f}%p</dd></div>
        <div><dt>승률</dt><dd>{item['strategy_win_rate']:,.1f}%</dd></div>
        <div><dt>최악 MDD</dt><dd>{item['worst_close_mdd']:,.2f}%</dd></div></dl></article>"""
        for item in data["summary"]
    )
    rows = "".join(
        f"""<tr><td>{html.escape(row['symbol'])}</td><td>{row['split_count']}</td><td>{row['sample']}</td>
        <td>{row['start_date']}</td><td>{row['end_date']}</td><td>{row['trading_days']}</td>
        <td>{row['strategy_profit_rate']:+,.2f}%</td><td>{row['hold_profit_rate']:+,.2f}%</td>
        <td>{row['qld_profit_rate']:+,.2f}%</td><td>{row['strategy_minus_hold']:+,.2f}%p</td>
        <td>{row['close_mdd']:,.2f}%</td><td>{row['intraday_high_only_fills']}</td></tr>"""
        for row in data["rows"]
    )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BackTest version3 랜덤 비교</title><style>
:root{{--bg:#f1f5f2;--panel:#fff;--ink:#15251d;--muted:#637168;--line:#dce5df;--green:#08775b;--red:#c43e45}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 Arial,"Malgun Gothic",sans-serif}}header{{padding:26px 4vw;background:#102a21;color:#fff}}header h1{{margin:0}}header p{{margin:5px 0 0;color:#bcd0c8}}main{{padding:20px 4vw}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}article,.table{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}article h2{{font-size:15px;margin:0}}article>strong{{display:block;font-size:25px;margin:8px 0}}dl{{margin:0}}dl div{{display:flex;justify-content:space-between;padding:3px 0;color:var(--muted)}}dd{{margin:0;color:var(--ink);font-weight:bold}}.positive{{color:var(--green)}}.negative{{color:var(--red)}}.table{{margin-top:12px;overflow:auto;max-height:70vh;padding:0}}table{{border-collapse:collapse;width:100%;min-width:1050px}}th,td{{padding:8px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th{{position:sticky;top:0;background:#edf3ef}}td:first-child,th:first-child{{text-align:left}}
</style></head><body><header><h1>랜덤 기간 견고성 비교</h1><p>{config['start_date']} ~ {config['end_date']} · 조합별 {config['count']}개 · {html.escape(config['fill_model'])}</p></header>
<main><section class="cards">{cards}</section><section class="table"><table><thead><tr><th>종목</th><th>분할</th><th>#</th><th>시작</th><th>종료</th><th>일수</th><th>전략</th><th>종목</th><th>QLD</th><th>초과</th><th>MDD</th><th>고가체결</th></tr></thead><tbody>{rows}</tbody></table></section></main></body></html>"""


def write_random_html_report(result: object, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_random_html_report(result), encoding="utf-8")
    return path
