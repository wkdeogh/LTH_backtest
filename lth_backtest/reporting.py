from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Iterable

from .precision import to_primitive


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
    return [
        _write_csv(data.get("executions", []), directory / "executions.csv"),
        _write_csv(data.get("rounds", []), directory / "rounds.csv"),
        _write_csv(data.get("equity_curve", []), directory / "equity_curve.csv"),
        _write_csv(data.get("monthly_returns", []), directory / "monthly_returns.csv"),
    ]


def render_html_report(result: object) -> str:
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
<title>{html.escape(config['symbol'])} BackTest version2</title>
<style>
:root{{--bg:#f4f7f5;--panel:#fff;--ink:#15251d;--muted:#617068;--line:#dce5df;--green:#08775b;--red:#c73e3e;--blue:#2463d4}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Arial,"Malgun Gothic",sans-serif}}
header{{padding:28px max(24px,calc((100vw - 1280px)/2));background:#10271f;color:#fff}}h1{{margin:0 0 6px;font-size:28px}}header p{{margin:0;color:#c9d7d1}}
main{{max-width:1280px;margin:auto;padding:22px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}article,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}article span{{display:block;color:var(--muted)}}article strong{{display:block;font-size:23px;margin-top:5px}}.panel{{margin-top:14px}}h2{{font-size:18px;margin:0 0 12px}}canvas{{width:100%;height:340px}}.table{{overflow:auto;max-height:520px}}table{{border-collapse:collapse;width:100%;min-width:920px}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th{{position:sticky;top:0;background:#eef3f0}}td:first-child,th:first-child{{text-align:left}}ul{{margin:0;padding-left:20px}}
</style></head><body>
<header><h1>BackTest version2 · {html.escape(config['symbol'])} {config['split_count']}분할</h1><p>{period['start']} ~ {period['end']} · {period['trading_days']:,}거래일 · {html.escape(config['fill_model'])}</p></header>
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
<title>BackTest version2 랜덤 비교</title><style>
:root{{--bg:#f1f5f2;--panel:#fff;--ink:#15251d;--muted:#637168;--line:#dce5df;--green:#08775b;--red:#c43e45}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 Arial,"Malgun Gothic",sans-serif}}header{{padding:26px 4vw;background:#102a21;color:#fff}}header h1{{margin:0}}header p{{margin:5px 0 0;color:#bcd0c8}}main{{padding:20px 4vw}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}article,.table{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}article h2{{font-size:15px;margin:0}}article>strong{{display:block;font-size:25px;margin:8px 0}}dl{{margin:0}}dl div{{display:flex;justify-content:space-between;padding:3px 0;color:var(--muted)}}dd{{margin:0;color:var(--ink);font-weight:bold}}.positive{{color:var(--green)}}.negative{{color:var(--red)}}.table{{margin-top:12px;overflow:auto;max-height:70vh;padding:0}}table{{border-collapse:collapse;width:100%;min-width:1050px}}th,td{{padding:8px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th{{position:sticky;top:0;background:#edf3ef}}td:first-child,th:first-child{{text-align:left}}
</style></head><body><header><h1>랜덤 기간 견고성 비교</h1><p>{config['start_date']} ~ {config['end_date']} · 조합별 {config['count']}개 · {html.escape(config['fill_model'])}</p></header>
<main><section class="cards">{cards}</section><section class="table"><table><thead><tr><th>종목</th><th>분할</th><th>#</th><th>시작</th><th>종료</th><th>일수</th><th>전략</th><th>종목</th><th>QLD</th><th>초과</th><th>MDD</th><th>고가체결</th></tr></thead><tbody>{rows}</tbody></table></section></main></body></html>"""


def write_random_html_report(result: object, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_random_html_report(result), encoding="utf-8")
    return path
