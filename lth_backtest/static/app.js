"use strict";

const app = {
  meta: null,
  result: null,
  executionLimit: 100,
  chartPoints: [],
  randomResult: null,
  roundStartResult: null,
  roundStartLimit: 200,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const money = value => value == null ? "-" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);
const number = (value, digits = 2) => value == null ? "-" : Number(value).toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const percent = (value, digits = 2, sign = false) => value == null ? "-" : `${sign && Number(value) > 0 ? "+" : ""}${number(value, digits)}%`;
const cls = value => Number(value) > 0 ? "positive" : Number(value) < 0 ? "negative" : "";
const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
  if (!response.ok) throw new Error(data.error || `요청 실패 (${response.status})`);
  return data;
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.add("hidden"), error ? 6000 : 3000);
}

function setLoading(active, message = "정밀 계산 중입니다") {
  $("#loading strong").textContent = message;
  $("#loading").classList.toggle("hidden", !active);
  $("#backtestForm button[type=submit]").disabled = active;
  $("#runRoundStarts").disabled = active;
}

function selectedSymbol() {
  return $("input[name=symbol]:checked").value;
}

function matchingDatasets(symbol) {
  return (app.meta?.datasets || []).filter(item => item.name.toUpperCase().startsWith(symbol));
}

function refreshDatasetChoices(force = false) {
  const symbol = selectedSymbol();
  const matches = matchingDatasets(symbol);
  $("#csvOptions").innerHTML = matches.map(item => `<option value="${escapeHtml(item.path)}">${item.start} ~ ${item.end} · ${item.rows.toLocaleString()}행</option>`).join("");
  const input = $("#csvPath");
  if (force || !input.value) input.value = matches[0]?.path || `BackTest/data/${symbol}.csv`;
  const current = matches.find(item => item.path === input.value) || matches[0];
  $("#datasetInfo").textContent = current
    ? `${current.start} ~ ${current.end} · ${current.rows.toLocaleString()}거래일 · OHLC 고가 포함`
    : "CSV 경로를 직접 입력하거나 데이터를 다운로드하세요.";
}

function resetForm() {
  const form = $("#backtestForm");
  form.reset();
  form.elements.end_date.value = app.meta?.today || new Date().toISOString().slice(0, 10);
  refreshDatasetChoices(true);
  toast("기본 설정으로 복원했습니다.");
}

function formPayload() {
  const form = $("#backtestForm");
  const raw = Object.fromEntries(new FormData(form));
  return {
    symbol: raw.symbol,
    split_count: Number(raw.split_count),
    principal: raw.principal,
    compounding_type: raw.compounding_type,
    sell_percent: raw.sell_percent || null,
    csv_path: raw.csv_path,
    start_date: raw.start_date,
    end_date: raw.end_date,
    fill_model: raw.fill_model,
    initial_entry: raw.initial_entry,
    first_buy_buffer_percent: raw.first_buy_buffer_percent,
    annual_risk_free_rate: raw.annual_risk_free_rate,
    slippage_bps: raw.slippage_bps,
    commission: raw.commission,
    sell_fee_bps: raw.sell_fee_bps,
    compare_close_only: form.elements.compare_close_only.checked,
  };
}

function activateTab(name) {
  $$(".tab").forEach(button => button.classList.toggle("active", button.dataset.tab === name));
  $$(".tab-page").forEach(page => page.classList.toggle("active", page.id === `tab-${name}`));
  if (name === "overview" && app.result) requestAnimationFrame(renderCharts);
}

function summaryCard(label, value, detail = "", valueClass = "") {
  return `<article class="summary-card"><span>${escapeHtml(label)}</span><strong class="${valueClass}">${escapeHtml(value)}</strong>${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</article>`;
}

function renderMetricList(element, items) {
  element.innerHTML = items.map(([label, value, valueClass = ""]) => `<div><dt>${escapeHtml(label)}</dt><dd class="${valueClass}">${escapeHtml(value)}</dd></div>`).join("");
}

function renderOverview(result) {
  $("#emptyState").classList.add("hidden");
  $("#resultsContent").classList.remove("hidden");
  const { config, period, summary, metrics, diagnostics } = result;
  $("#resultTitle").textContent = `${config.symbol} · ${config.split_count}분할 결과`;
  $("#resultPeriod").textContent = `${period.start} — ${period.end} · ${period.trading_days.toLocaleString()}거래일`;
  $("#fillBadge").textContent = config.fill_model === "intraday_high" ? "장중 고가 지정가" : "종가 전용 비교";
  $("#modeBadge").textContent = config.compounding_type === "compound" ? "복리" : "단리";
  $("#summaryCards").innerHTML = [
    summaryCard("최종 자산", money(summary.ending_equity), `손익 ${money(summary.profit_amount)}`, cls(summary.profit_amount)),
    summaryCard("총수익률", percent(summary.profit_rate, 2, true), `종목 ${percent(summary.benchmark_profit_rate, 2, true)} · QLD ${percent(summary.qld_benchmark_profit_rate, 2, true)}`, cls(summary.profit_rate)),
    summaryCard("초과수익", `${percent(summary.excess_return_rate, 2, true)}p`, "전략 − 종목 거치식", cls(summary.excess_return_rate)),
    summaryCard("CAGR", percent(metrics.cagr, 2, true), `${period.calendar_days.toLocaleString()}일`, cls(metrics.cagr)),
    summaryCard("종가 기준 MDD", percent(metrics.close_mdd), `${metrics.mdd_peak_date} → ${metrics.mdd_trough_date}`, "negative"),
    summaryCard("완료 라운드", summary.completed_rounds.toLocaleString(), `체결 ${summary.execution_count.toLocaleString()}건`),
  ].join("");

  const comparison = result.fill_model_comparison;
  const comparisonElement = $("#fillComparison");
  if (comparison) {
    const delta = comparison.intraday_minus_close_equity;
    comparisonElement.innerHTML = `장중 고가를 반영하면 종가 전용 계산보다 최종 자산이 <strong>${escapeHtml(money(delta))}</strong> (${escapeHtml(percent(comparison.intraday_minus_close_profit_rate, 4, true))}p) 달라집니다. 종가 전용 최종 자산: ${escapeHtml(money(comparison.close_only_ending_equity))}`;
    comparisonElement.classList.remove("hidden");
  } else comparisonElement.classList.add("hidden");

  $("#mddValue").textContent = percent(metrics.close_mdd);
  $("#mddValue").className = "negative";
  renderMetricList($("#riskMetrics"), [
    ["연환산 변동성", percent(metrics.annual_volatility)],
    ["Sharpe", number(metrics.sharpe_ratio, 3), cls(metrics.sharpe_ratio)],
    ["Sortino", number(metrics.sortino_ratio, 3), cls(metrics.sortino_ratio)],
    ["Calmar", number(metrics.calmar_ratio, 3), cls(metrics.calmar_ratio)],
    ["시장 노출 비율", percent(metrics.market_exposure_rate)],
    ["라운드 승률", percent(metrics.round_win_rate)],
    ["총 거래비용", money(metrics.total_fees)],
  ]);
  renderMetricList($("#executionDiagnostics"), [
    ["최종 지정가 시도", `${diagnostics.limit_sell_attempts.toLocaleString()}건`],
    ["최종 지정가 체결", `${diagnostics.limit_sell_fills.toLocaleString()}건`],
    ["고가만 도달한 체결", `${diagnostics.intraday_high_only_fills.toLocaleString()}건`, diagnostics.intraday_high_only_fills ? "positive" : ""],
    ["LOC 매수 체결", `${diagnostics.loc_buy_fills.toLocaleString()}건`],
    ["LOC 매도 체결", `${diagnostics.loc_sell_fills.toLocaleString()}건`],
    ["리버스 진입 / 복귀", `${diagnostics.reverse_entries.toLocaleString()} / ${diagnostics.reverse_returns.toLocaleString()}`],
    ["장기 데이터 공백", `${diagnostics.long_gap_count || 0}구간`],
  ]);
  const standardWarnings = [
    "일봉에는 프리장·본장·애프터장의 순서 정보가 없어, 고가가 목표가 이상이면 지정가가 체결된 것으로 봅니다.",
    "Yahoo 일봉 고가는 보통 정규장 기준입니다. 프리장·애프터장 체결까지 분석하려면 해당 세션을 합친 사용자 CSV가 필요합니다.",
    "MDD와 Sharpe는 일별 종가 평가자산 기준이며 장중 최저 낙폭을 뜻하지 않습니다.",
  ];
  $("#warningList").innerHTML = [...(result.warnings || []), ...standardWarnings].map(item => `<li>${escapeHtml(item)}</li>`).join("");
  app.chartPoints = result.equity_curve || [];
  requestAnimationFrame(renderCharts);
}

function renderExecutions() {
  const source = app.result?.executions || [];
  const query = $("#executionSearch").value.trim().toLowerCase();
  const side = $("#executionSide").value;
  const filtered = source.filter(item => (!side || item.side === side) && (!query || `${item.date} ${item.label} ${item.order_type}`.toLowerCase().includes(query)));
  const shown = filtered.slice(0, app.executionLimit);
  $("#executionRows").innerHTML = shown.length ? shown.map(item => `<tr>
    <td>${item.sequence}</td><td>${item.date}</td><td>${item.mode === "normal" ? "일반" : "리버스"}</td>
    <td><span class="side-pill ${item.side}">${item.side === "buy" ? "매수" : "매도"}</span></td><td>${item.order_type}</td><td>${escapeHtml(item.label)}</td>
    <td>${item.order_price == null ? "-" : money(item.order_price)}</td><td>${money(item.fill_price)}</td><td>${item.quantity.toLocaleString()}</td>
    <td>${money(item.gross_amount)}</td><td>${money(item.fees)}</td><td>${number(item.t_before, 6)}</td><td>${number(item.t_after, 6)}</td></tr>`).join("") : `<tr><td colspan="13">조건에 맞는 체결이 없습니다.</td></tr>`;
  $("#executionMore").classList.toggle("hidden", shown.length >= filtered.length);
}

function renderRounds() {
  const rows = app.result?.rounds || [];
  $("#roundRows").innerHTML = rows.length ? rows.map(item => `<tr><td>${item.round_number}</td><td>${item.started_at}</td><td>${item.ended_at}</td><td>${item.trading_days}</td><td>${money(item.allocation_principal)}</td><td>${money(item.starting_equity)}</td><td>${money(item.ending_equity)}</td><td class="${cls(item.profit_amount)}">${money(item.profit_amount)}</td><td class="${cls(item.profit_rate)}">${percent(item.profit_rate, 3, true)}</td><td>${item.execution_count}</td><td>${money(item.total_fees)}</td></tr>`).join("") : `<tr><td colspan="11">완료된 라운드가 없습니다.</td></tr>`;
}

function renderRoundStartRows() {
  const source = app.roundStartResult?.rows || [];
  const query = $("#roundStartSearch").value.trim().toLowerCase();
  const status = $("#roundStartStatus").value;
  const reverse = $("#roundStartReverse").value;
  const sort = $("#roundStartSort").value;
  const filtered = source.filter(item => {
    const matchesQuery = !query || `${item.start_date} ${item.end_date || ""} ${item.last_observed_at}`.toLowerCase().includes(query);
    const matchesStatus = !status || item.status === status;
    const matchesReverse = !reverse || (reverse === "yes" ? item.reverse_entered : !item.reverse_entered);
    return matchesQuery && matchesStatus && matchesReverse;
  });
  const comparisons = {
    "start-asc": (a, b) => a.start_date.localeCompare(b.start_date),
    "start-desc": (a, b) => b.start_date.localeCompare(a.start_date),
    "profit-desc": (a, b) => b.profit_rate - a.profit_rate,
    "profit-asc": (a, b) => a.profit_rate - b.profit_rate,
    "mdd-asc": (a, b) => a.close_mdd - b.close_mdd,
    "duration-desc": (a, b) => b.calendar_days - a.calendar_days,
    "t-desc": (a, b) => b.max_t_value - a.max_t_value,
  };
  filtered.sort(comparisons[sort] || comparisons["start-asc"]);
  const shown = filtered.slice(0, app.roundStartLimit);
  $("#roundStartRows").innerHTML = shown.length ? shown.map(item => {
    const observedDate = item.completed ? item.end_date : item.last_observed_at;
    const statusLabel = item.completed ? "완료" : "미종료";
    const modeLabel = item.ending_mode === "reverse" ? "리버스" : "일반";
    return `<tr>
      <td>${item.start_date}</td><td><span class="status-pill ${item.status}">${statusLabel}</span></td><td>${observedDate}${item.completed ? "" : " *"}</td>
      <td>${item.calendar_days.toLocaleString()}</td><td>${item.trading_days.toLocaleString()}</td><td class="${cls(item.profit_rate)}">${percent(item.profit_rate, 3, true)}${item.completed ? "" : " *"}</td>
      <td class="${cls(item.profit_amount)}">${money(item.profit_amount)}</td><td class="negative">${percent(item.close_mdd, 2)}</td><td>${number(item.max_t_value, 4)}</td><td>${number(item.ending_t_value, 4)} · ${modeLabel}</td>
      <td>${item.reverse_entries.toLocaleString()} / ${item.reverse_returns.toLocaleString()}</td><td>${item.buy_count.toLocaleString()}</td><td>${item.sell_count.toLocaleString()}</td><td>${item.execution_count.toLocaleString()}</td>
      <td>${item.intraday_high_only_fills.toLocaleString()}</td><td>${item.max_position_qty.toLocaleString()}주</td><td>${item.ending_position_qty.toLocaleString()}주</td><td>${money(item.total_fees)}</td>
    </tr>`;
  }).join("") : `<tr><td colspan="18">조건에 맞는 시작일 결과가 없습니다.</td></tr>`;
  $("#roundStartMore").classList.toggle("hidden", shown.length >= filtered.length);
}

function renderRoundStartAnalysis(result) {
  app.roundStartResult = result;
  app.roundStartLimit = 200;
  const summary = result.summary;
  $("#roundStartCount").textContent = summary.sample_count.toLocaleString();
  $("#roundStartEmpty").classList.add("hidden");
  $("#roundStartResults").classList.remove("hidden");
  $("#downloadRoundStartsJson").disabled = false;
  $("#downloadRoundStartsCsv").disabled = false;
  $("#roundStartSummary").innerHTML = [
    summaryCard("분석 시작일", `${summary.sample_count.toLocaleString()}개`, `${result.period.start} — ${result.period.end}`),
    summaryCard("라운드 완료", `${summary.completed_count.toLocaleString()}개`, `완료율 ${percent(summary.completion_rate, 1)} · 미종료 ${summary.incomplete_count.toLocaleString()}개`),
    summaryCard("완료 평균 수익률", percent(summary.avg_profit_rate_completed, 3, true), `중앙값 ${percent(summary.median_profit_rate_completed, 3, true)}`, cls(summary.avg_profit_rate_completed)),
    summaryCard("완료 수익률 범위", `${percent(summary.worst_profit_rate_completed, 2)} — ${percent(summary.best_profit_rate_completed, 2, true)}`, `수익 표본 ${percent(summary.completed_win_rate, 1)}`),
    summaryCard("완료 평균 기간", `${number(summary.avg_calendar_days_completed, 1)}일`, `중앙값 ${number(summary.median_calendar_days_completed, 1)}일 · ${number(summary.avg_trading_days_completed, 1)}거래일`),
    summaryCard("종가 MDD", percent(summary.avg_close_mdd_all, 2), `전체 평균 · 최악 ${percent(summary.worst_close_mdd_all, 2)}`, "negative"),
    summaryCard("최대 T값", number(summary.avg_max_t_value_all, 3), `전체 평균 · 최고 ${number(summary.highest_max_t_value, 3)}`),
    summaryCard("리버스 진입", `${summary.reverse_sample_count.toLocaleString()}개`, `전체 시작일의 ${percent(summary.reverse_entry_rate, 1)}`),
    summaryCard("평균 체결 횟수", number(summary.avg_execution_count_all, 1), `매수 ${number(summary.avg_buy_count_all, 1)} · 매도 ${number(summary.avg_sell_count_all, 1)}`),
  ].join("");
  $("#roundStartNote").textContent = `각 표본은 시작일 종가에 첫 1회분을 MOC 매수합니다. 미종료 ${summary.incomplete_count.toLocaleString()}개는 ${result.period.end} 종가 평가이며 완료 수익률·기간 평균에서 제외했습니다. MDD는 일별 종가 평가자산 기준입니다.`;
  renderRoundStartRows();
}

function renderPeriods() {
  const render = (selector, rows) => {
    $(selector).innerHTML = rows.length ? [...rows].reverse().map(item => `<tr><td>${item.period}</td><td>${money(item.ending_equity)}</td><td class="${cls(item.return_rate)}">${percent(item.return_rate, 3, true)}</td></tr>`).join("") : `<tr><td colspan="3">데이터 없음</td></tr>`;
  };
  render("#yearRows", app.result?.yearly_returns || []);
  render("#monthRows", app.result?.monthly_returns || []);
}

function fitCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(Math.round(rect.width * ratio), 1);
  const height = Math.max(Math.round(rect.height * ratio), 1);
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { context, width: rect.width, height: rect.height };
}

function drawEquity() {
  const canvas = $("#equityChart");
  if (!canvas || !app.chartPoints.length || !canvas.offsetParent) return;
  const { context: ctx, width, height } = fitCanvas(canvas);
  const padding = { left: 56, right: 15, top: 12, bottom: 25 };
  const hasQld = app.chartPoints.some(point => point.qld_benchmark_equity != null);
  const values = app.chartPoints.flatMap(point => hasQld ? [point.equity, point.benchmark_equity, point.qld_benchmark_equity] : [point.equity, point.benchmark_equity]);
  let low = Math.min(...values), high = Math.max(...values);
  const range = Math.max(high - low, 1); low -= range * .04; high += range * .04;
  ctx.clearRect(0, 0, width, height);
  ctx.font = "10px -apple-system, sans-serif"; ctx.fillStyle = "#77827c"; ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let index = 0; index < 5; index++) {
    const y = padding.top + (height - padding.top - padding.bottom) * index / 4;
    const value = high - (high - low) * index / 4;
    ctx.strokeStyle = "#e5ebe7"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    ctx.fillText(`$${Math.round(value).toLocaleString()}`, padding.left - 7, y);
  }
  const pointX = index => padding.left + (width - padding.left - padding.right) * index / Math.max(app.chartPoints.length - 1, 1);
  const pointY = value => padding.top + (high - value) / (high - low) * (height - padding.top - padding.bottom);
  const line = (key, color) => {
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.beginPath();
    app.chartPoints.forEach((point, index) => { const x = pointX(index), y = pointY(point[key]); index ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
  };
  if (hasQld) line("qld_benchmark_equity", "#d18a18"); line("benchmark_equity", "#2865d5"); line("equity", "#08775b");
  ctx.fillStyle = "#77827c"; ctx.textAlign = "left"; ctx.textBaseline = "bottom"; ctx.fillText(app.chartPoints[0].date, padding.left, height - 2); ctx.textAlign = "right"; ctx.fillText(app.chartPoints.at(-1).date, width - padding.right, height - 2);
  canvas._chart = { pointX, pointY, padding, width, height };
}

function drawDrawdown() {
  const canvas = $("#drawdownChart");
  if (!canvas || !app.chartPoints.length || !canvas.offsetParent) return;
  const { context: ctx, width, height } = fitCanvas(canvas);
  const pad = 12, bottom = 22, minimum = Math.min(...app.chartPoints.map(point => point.drawdown || 0), -1);
  const x = index => pad + (width - pad * 2) * index / Math.max(app.chartPoints.length - 1, 1);
  const y = value => pad + (0 - value) / (0 - minimum) * (height - pad - bottom);
  ctx.clearRect(0, 0, width, height); ctx.strokeStyle = "#e5ebe7"; ctx.beginPath(); ctx.moveTo(pad, pad); ctx.lineTo(width - pad, pad); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x(0), pad); app.chartPoints.forEach((point, index) => ctx.lineTo(x(index), y(point.drawdown || 0))); ctx.lineTo(x(app.chartPoints.length - 1), pad); ctx.closePath();
  const gradient = ctx.createLinearGradient(0, pad, 0, height - bottom); gradient.addColorStop(0, "rgba(196,62,69,.08)"); gradient.addColorStop(1, "rgba(196,62,69,.28)"); ctx.fillStyle = gradient; ctx.fill();
  ctx.strokeStyle = "#c43e45"; ctx.lineWidth = 1.5; ctx.beginPath(); app.chartPoints.forEach((point, index) => index ? ctx.lineTo(x(index), y(point.drawdown || 0)) : ctx.moveTo(x(index), y(point.drawdown || 0))); ctx.stroke();
  ctx.fillStyle = "#7b8580"; ctx.font = "10px sans-serif"; ctx.textAlign = "left"; ctx.fillText("0%", pad, 10); ctx.fillText(`${number(minimum, 1)}%`, pad, height - 5);
}

function renderCharts() { drawEquity(); drawDrawdown(); }

function renderAll(result) {
  app.result = result;
  app.executionLimit = 100;
  $("#executionCount").textContent = result.executions.length.toLocaleString();
  $("#roundCount").textContent = result.rounds.length.toLocaleString();
  ["#downloadJson", "#downloadCsv", "#downloadReport"].forEach(selector => $(selector).disabled = false);
  renderOverview(result); renderExecutions(); renderRounds(); renderPeriods(); activateTab("overview");
}

async function runBacktest(event) {
  event?.preventDefault();
  const payload = formPayload();
  if (payload.start_date > payload.end_date) return toast("시작일이 종료일보다 늦습니다.", true);
  setLoading(true);
  try { renderAll(await api("/api/run", payload)); toast("백테스트가 완료되었습니다."); }
  catch (error) { toast(error.message, true); }
  finally { setLoading(false); }
}

async function runRoundStarts() {
  const payload = formPayload();
  if (payload.start_date > payload.end_date) return toast("시작일이 종료일보다 늦습니다.", true);
  setLoading(true, "모든 시작 거래일의 1라운드를 계산 중입니다");
  try {
    const result = await api("/api/round-starts", payload);
    renderRoundStartAnalysis(result);
    activateTab("round-starts");
    toast(`${result.summary.sample_count.toLocaleString()}개 시작일 분석이 완료되었습니다.`);
  } catch (error) { toast(error.message, true); }
  finally { setLoading(false); }
}

function downloadBlob(content, type, filename) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = Object.assign(document.createElement("a"), { href: url, download: filename });
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvText(rows) {
  if (!rows.length) return "";
  const keys = Object.keys(rows[0]);
  const cell = value => `"${String(value ?? "").replaceAll('"', '""')}"`;
  return `\ufeff${keys.map(cell).join(",")}\n${rows.map(row => keys.map(key => cell(row[key])).join(",")).join("\n")}`;
}

async function downloadReport() {
  if (!app.result) return;
  try {
    const response = await fetch("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ result: app.result }) });
    if (!response.ok) throw new Error("리포트를 생성하지 못했습니다.");
    const url = URL.createObjectURL(await response.blob()); const anchor = Object.assign(document.createElement("a"), { href: url, download: `${app.result.config.symbol}-backtest-v2.html` }); anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { toast(error.message, true); }
}

async function refreshPrices() {
  setLoading(true, "TQQQ · SOXL · QLD 전체 이력을 다운로드 중입니다");
  try {
    const result = await api("/api/download", { scope: "all" });
    const downloaded = result.datasets.filter(Boolean);
    const paths = new Set(downloaded.map(item => item.path));
    app.meta.datasets = app.meta.datasets.filter(item => !paths.has(item.path));
    app.meta.datasets.push(...downloaded);
    refreshDatasetChoices(true);
    const summary = downloaded.map(item => `${item.name.replace(".csv", "")} ${item.start}~${item.end}`).join(" · ");
    toast(`전체 데이터 저장 완료 · ${summary}`);
  } catch (error) { toast(error.message, true); }
  finally { setLoading(false); }
}

async function runRandom(event) {
  event.preventDefault();
  const main = formPayload(), raw = new FormData(event.currentTarget);
  const symbols = raw.getAll("symbols"), splits = raw.getAll("splits").map(Number);
  if (!symbols.length || !splits.length) return toast("랜덤 비교 종목과 분할 수를 선택하세요.", true);
  const body = { ...main, symbols, splits, count: Number(raw.get("count")), min_days: Number(raw.get("min_days")), max_days: raw.get("max_days") || null, seed: raw.get("seed") || null };
  setLoading(true, "랜덤 기간을 반복 계산 중입니다");
  try { app.randomResult = await api("/api/random", body); renderRandom(app.randomResult); toast("랜덤 비교가 완료되었습니다."); }
  catch (error) { toast(error.message, true); }
  finally { setLoading(false); }
}

function renderRandom(result) {
  $("#randomResults").innerHTML = `<div class="random-summary-grid">${result.summary.map(item => `<article class="random-card"><h3>${item.symbol} · ${item.split_count}분할</h3><span class="big ${cls(item.avg_strategy_profit_rate)}">${percent(item.avg_strategy_profit_rate, 2, true)}</span><dl><div><dt>거치식 대비</dt><dd class="${cls(item.avg_excess_vs_hold)}">${percent(item.avg_excess_vs_hold, 2, true)}p</dd></div><div><dt>QLD 대비</dt><dd class="${cls(item.avg_excess_vs_qld)}">${percent(item.avg_excess_vs_qld, 2, true)}p</dd></div><div><dt>전략 승률</dt><dd>${percent(item.strategy_win_rate, 1)}</dd></div><div><dt>최악 / 최고</dt><dd>${percent(item.worst_return, 1)} / ${percent(item.best_return, 1, true)}</dd></div><div><dt>최악 MDD</dt><dd class="negative">${percent(item.worst_close_mdd, 1)}</dd></div><div><dt>고가 전용 체결</dt><dd>${item.intraday_high_only_fills.toLocaleString()}건</dd></div></dl></article>`).join("")}</div>`;
}

async function init() {
  $("#backtestForm").elements.end_date.value = new Date().toISOString().slice(0, 10);
  try {
    app.meta = await api("/api/meta"); $("#serverStatus").textContent = `엔진 ${app.meta.version}`; $("#serverStatus").classList.add("ready");
    $("#backtestForm").elements.end_date.value = app.meta.today; refreshDatasetChoices(true);
  } catch (error) { $("#serverStatus").textContent = "연결 실패"; toast(error.message, true); }
}

$("#backtestForm").addEventListener("submit", runBacktest);
$("#randomForm").addEventListener("submit", runRandom);
$("#runRoundStarts").addEventListener("click", runRoundStarts);
$("#resetForm").addEventListener("click", resetForm);
$("#refreshPrices").addEventListener("click", refreshPrices);
$$("input[name=symbol]").forEach(input => input.addEventListener("change", () => refreshDatasetChoices(true)));
$("#csvPath").addEventListener("change", () => refreshDatasetChoices(false));
$$('.tab').forEach(button => button.addEventListener("click", () => activateTab(button.dataset.tab)));
$("#executionSearch").addEventListener("input", () => { app.executionLimit = 100; renderExecutions(); });
$("#executionSide").addEventListener("change", () => { app.executionLimit = 100; renderExecutions(); });
$("#executionMore").addEventListener("click", () => { app.executionLimit += 100; renderExecutions(); });
$("#roundStartSearch").addEventListener("input", () => { app.roundStartLimit = 200; renderRoundStartRows(); });
$("#roundStartStatus").addEventListener("change", () => { app.roundStartLimit = 200; renderRoundStartRows(); });
$("#roundStartReverse").addEventListener("change", () => { app.roundStartLimit = 200; renderRoundStartRows(); });
$("#roundStartSort").addEventListener("change", () => { app.roundStartLimit = 200; renderRoundStartRows(); });
$("#roundStartMore").addEventListener("click", () => { app.roundStartLimit += 200; renderRoundStartRows(); });
$("#downloadJson").addEventListener("click", () => app.result && downloadBlob(JSON.stringify(app.result, null, 2), "application/json", `${app.result.config.symbol}-backtest-v2.json`));
$("#downloadCsv").addEventListener("click", () => app.result && downloadBlob(csvText(app.result.executions), "text/csv;charset=utf-8", `${app.result.config.symbol}-executions.csv`));
$("#downloadReport").addEventListener("click", downloadReport);
$("#downloadRoundStartsJson").addEventListener("click", () => app.roundStartResult && downloadBlob(JSON.stringify(app.roundStartResult, null, 2), "application/json", `${app.roundStartResult.config.symbol}-round-start-analysis.json`));
$("#downloadRoundStartsCsv").addEventListener("click", () => app.roundStartResult && downloadBlob(csvText(app.roundStartResult.rows), "text/csv;charset=utf-8", `${app.roundStartResult.config.symbol}-round-start-analysis.csv`));
document.addEventListener("keydown", event => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") runBacktest(event); });
window.addEventListener("resize", () => { clearTimeout(app.resizeTimer); app.resizeTimer = setTimeout(renderCharts, 100); });
$("#equityChart").addEventListener("mousemove", event => {
  if (!app.chartPoints.length) return;
  const canvas = event.currentTarget, info = canvas._chart, rect = canvas.getBoundingClientRect(); if (!info) return;
  const localX = event.clientX - rect.left; const ratio = (localX - info.padding.left) / Math.max(info.width - info.padding.left - info.padding.right, 1); const index = Math.max(0, Math.min(app.chartPoints.length - 1, Math.round(ratio * (app.chartPoints.length - 1)))); const point = app.chartPoints[index];
  const tip = $("#equityTooltip"); tip.innerHTML = `<strong>${point.date}</strong><br>전략 ${money(point.equity)}<br>종목 ${money(point.benchmark_equity)}${point.qld_benchmark_equity == null ? "" : `<br>QLD ${money(point.qld_benchmark_equity)}`}<br>낙폭 ${percent(point.drawdown)}`; tip.style.left = `${Math.min(localX + 12, rect.width - 160)}px`; tip.style.top = `${Math.max(event.clientY - rect.top - 32, 6)}px`; tip.classList.remove("hidden");
});
$("#equityChart").addEventListener("mouseleave", () => $("#equityTooltip").classList.add("hidden"));

init();
