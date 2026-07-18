"use strict";

const app = {
  meta: null,
  result: null,
  executionLimit: 100,
  chartPoints: [],
  randomResult: null,
  roundStartResult: null,
  roundStartLimit: 200,
  roundStartTimelineHover: null,
  roundStartScatterHover: null,
  candleEnd: 0,
  candleHoverIndex: null,
  dateRangeDates: [],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const money = value => value == null ? "-" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);
const price = value => value == null ? "-" : `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
const volumeNumber = value => value == null ? "-" : Number(value).toLocaleString("ko-KR");
const number = (value, digits = 2) => value == null ? "-" : Number(value).toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const percent = (value, digits = 2, sign = false) => value == null ? "-" : `${sign && Number(value) > 0 ? "+" : ""}${number(value, digits)}%`;
const cls = value => Number(value) > 0 ? "positive" : Number(value) < 0 ? "negative" : "";
const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const CANDLE_COLORS = Object.freeze({ rise: "#e43f45", fall: "#1976d2", flat: "#78837d" });

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
  $("#refreshPrices").disabled = active;
}

function selectedSymbol() {
  return $("input[name=symbol]:checked").value;
}

function matchingDatasets(symbol) {
  return (app.meta?.datasets || []).filter(item => item.name.toUpperCase().startsWith(symbol));
}

function lowerBound(dates, target) {
  let low = 0, high = dates.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (dates[middle] < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

function upperBound(dates, target) {
  let low = 0, high = dates.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (dates[middle] <= target) low = middle + 1;
    else high = middle;
  }
  return low - 1;
}

function renderDateRange(startIndex, endIndex) {
  const dates = app.dateRangeDates;
  if (dates.length < 2) return;
  const lastIndex = dates.length - 1;
  startIndex = Math.max(0, Math.min(startIndex, lastIndex - 1));
  endIndex = Math.max(startIndex + 1, Math.min(endIndex, lastIndex));

  const startRange = $("#dateRangeStart"), endRange = $("#dateRangeEnd");
  startRange.value = String(startIndex);
  endRange.value = String(endIndex);
  $("#startDate").value = dates[startIndex];
  $("#endDate").value = dates[endIndex];
  $("#dateRangeStartLabel").textContent = dates[startIndex];
  $("#dateRangeEndLabel").textContent = dates[endIndex];
  $("#dateRangeTradingDays").textContent = `${(endIndex - startIndex + 1).toLocaleString()}거래일`;

  const left = startIndex / lastIndex * 100;
  const right = endIndex / lastIndex * 100;
  const selected = $("#dateRangeSelected");
  selected.style.left = `${left}%`;
  selected.style.width = `${right - left}%`;
}

function syncDateRangeFromSlider(changed) {
  const dates = app.dateRangeDates;
  if (dates.length < 2) return;
  const lastIndex = dates.length - 1;
  let startIndex = Number($("#dateRangeStart").value);
  let endIndex = Number($("#dateRangeEnd").value);
  if (startIndex >= endIndex) {
    if (changed === "start") startIndex = Math.max(0, endIndex - 1);
    else endIndex = Math.min(lastIndex, startIndex + 1);
  }
  renderDateRange(startIndex, endIndex);
}

function syncDateRangeFromInputs(changed) {
  const dates = app.dateRangeDates;
  if (dates.length < 2) return;
  const lastIndex = dates.length - 1;
  let startIndex = Math.max(0, Math.min(lowerBound(dates, $("#startDate").value || dates[0]), lastIndex));
  let endIndex = Math.max(0, Math.min(upperBound(dates, $("#endDate").value || dates[lastIndex]), lastIndex));
  if (startIndex >= endIndex) {
    if (changed === "start") startIndex = Math.max(0, endIndex - 1);
    else endIndex = Math.min(lastIndex, startIndex + 1);
  }
  renderDateRange(startIndex, endIndex);
}

function configureDateRange(dataset) {
  const dates = Array.isArray(dataset?.dates) ? dataset.dates : [];
  app.dateRangeDates = dates;
  const control = $("#dateRangeControl");
  const startRange = $("#dateRangeStart"), endRange = $("#dateRangeEnd");
  const startDate = $("#startDate"), endDate = $("#endDate");
  const disabled = dates.length < 2;
  control.classList.toggle("disabled", disabled);
  startRange.disabled = disabled;
  endRange.disabled = disabled;

  if (disabled) {
    startDate.removeAttribute("min"); startDate.removeAttribute("max");
    endDate.removeAttribute("min"); endDate.removeAttribute("max");
    $("#dateRangeBounds").textContent = "사용자 CSV · 날짜 직접 입력";
    $("#dateRangeStartLabel").textContent = "-";
    $("#dateRangeEndLabel").textContent = "-";
    $("#dateRangeTradingDays").textContent = "슬라이더 사용 불가";
    $("#dateRangeSelected").style.width = "0";
    return;
  }

  const lastIndex = dates.length - 1;
  startRange.min = "0"; startRange.max = String(lastIndex);
  endRange.min = "0"; endRange.max = String(lastIndex);
  startDate.min = dates[0]; startDate.max = dates[lastIndex];
  endDate.min = dates[0]; endDate.max = dates[lastIndex];
  $("#dateRangeBounds").textContent = `${dates[0]} ~ ${dates[lastIndex]}`;

  let startIndex = Math.max(0, Math.min(lowerBound(dates, startDate.value || dates[0]), lastIndex));
  let endIndex = Math.max(0, Math.min(upperBound(dates, endDate.value || dates[lastIndex]), lastIndex));
  if (startIndex >= endIndex) {
    startIndex = Math.min(startIndex, lastIndex - 1);
    endIndex = Math.max(endIndex, startIndex + 1);
  }
  renderDateRange(startIndex, endIndex);
}

function refreshDatasetChoices(force = false) {
  const symbol = selectedSymbol();
  const matches = matchingDatasets(symbol);
  $("#csvOptions").innerHTML = matches.map(item => `<option value="${escapeHtml(item.path)}">${item.start} ~ ${item.end} · ${item.rows.toLocaleString()}행 · ${item.price_basis === "actual_split_adjusted" ? "실거래가" : "갱신 필요"}</option>`).join("");
  const input = $("#csvPath");
  if (force || !input.value) input.value = matches[0]?.path || `data/${symbol}.csv`;
  const current = matches.find(item => item.path === input.value);
  $("#datasetInfo").textContent = current
    ? current.price_basis === "actual_split_adjusted"
      ? `${current.start} ~ ${current.end} · ${current.rows.toLocaleString()}거래일 · 실제 OHLC · 배당 미보정`
      : `${current.start} ~ ${current.end} · 기존 조정 데이터 · 아래에서 전체 데이터 갱신 필요`
    : "CSV 경로를 직접 입력하거나 데이터를 다운로드하세요.";
  configureDateRange(current);
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
  if (name === "candles" && app.result) requestAnimationFrame(drawCandlestick);
  if (name === "round-starts" && app.roundStartResult) requestAnimationFrame(drawRoundStartCharts);
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
  $("#roundRows").innerHTML = rows.length ? rows.map(item => `<tr><td>${item.round_number}</td><td>${item.started_at}</td><td>${item.ended_at}</td><td>${item.trading_days}</td><td>${money(item.allocation_principal)}</td><td>${money(item.starting_equity)}</td><td>${money(item.ending_equity)}</td><td class="${cls(item.profit_amount)}">${money(item.profit_amount)}</td><td class="${cls(item.profit_rate)}">${percent(item.profit_rate, 3, true)}</td><td class="negative"><strong>${percent(item.close_mdd, 2)}</strong><small class="cell-sub">${item.mdd_peak_date} → ${item.mdd_trough_date}</small></td><td class="${cls(item.benchmark_profit_rate)}">${percent(item.benchmark_profit_rate, 3, true)}</td><td>${item.execution_count}</td><td>${money(item.total_fees)}</td></tr>`).join("") : `<tr><td colspan="13">완료된 라운드가 없습니다.</td></tr>`;
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
  app.roundStartTimelineHover = null;
  app.roundStartScatterHover = null;
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
  requestAnimationFrame(drawRoundStartCharts);
}

function roundChartColors() {
  const styles = getComputedStyle(document.documentElement);
  const color = (name, fallback) => styles.getPropertyValue(name).trim() || fallback;
  return {
    brand: color("--brand", "#08775b"),
    amber: color("--amber", "#9a6300"),
    red: color("--red", "#c43e45"),
    blue: color("--blue", "#2865d5"),
    line: color("--line", "#dce4df"),
    muted: color("--muted", "#64716a"),
    ink: color("--ink", "#14231c"),
  };
}

function orderedRoundStartRows() {
  return [...(app.roundStartResult?.rows || [])].sort((a, b) => a.start_date.localeCompare(b.start_date));
}

function drawRoundStartTimelineChart() {
  const canvas = $("#roundStartTimelineChart");
  const rows = orderedRoundStartRows();
  if (!canvas || !rows.length || !canvas.offsetParent) return;
  const { context: ctx, width, height } = fitCanvas(canvas);
  const colors = roundChartColors();
  const padding = { left: 55, right: 15, top: 15, bottom: 28 };
  const values = rows.flatMap(item => [Number(item.profit_rate), Number(item.close_mdd)]).filter(Number.isFinite);
  let low = Math.min(0, ...values), high = Math.max(0, ...values);
  let range = Math.max(high - low, 1);
  low -= range * .08; high += range * .08; range = high - low;
  const pointX = index => padding.left + (width - padding.left - padding.right) * index / Math.max(rows.length - 1, 1);
  const pointY = value => padding.top + (high - Number(value)) / range * (height - padding.top - padding.bottom);

  ctx.clearRect(0, 0, width, height);
  ctx.font = "10px -apple-system, sans-serif";
  ctx.textBaseline = "middle";
  for (let index = 0; index < 5; index++) {
    const ratio = index / 4, value = high - range * ratio;
    const y = padding.top + (height - padding.top - padding.bottom) * ratio;
    ctx.strokeStyle = colors.line; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    ctx.fillStyle = colors.muted; ctx.textAlign = "right"; ctx.fillText(`${number(value, 1)}%`, padding.left - 7, y);
  }
  if (low < 0 && high > 0) {
    const zeroY = pointY(0);
    ctx.strokeStyle = colors.ink; ctx.globalAlpha = .32; ctx.beginPath(); ctx.moveTo(padding.left, zeroY); ctx.lineTo(width - padding.right, zeroY); ctx.stroke(); ctx.globalAlpha = 1;
  }
  const drawLine = (key, stroke, alpha, widthValue) => {
    ctx.strokeStyle = stroke; ctx.globalAlpha = alpha; ctx.lineWidth = widthValue; ctx.lineJoin = "round"; ctx.beginPath();
    rows.forEach((item, index) => { const x = pointX(index), y = pointY(item[key]); index ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke(); ctx.globalAlpha = 1;
  };
  drawLine("profit_rate", colors.brand, .35, 1);
  drawLine("close_mdd", colors.red, .9, 1.5);

  const radius = rows.length > 700 ? 1 : rows.length > 250 ? 1.5 : 2.25;
  rows.forEach((item, index) => {
    const x = pointX(index), y = pointY(item.profit_rate);
    ctx.fillStyle = item.completed ? colors.brand : colors.amber;
    ctx.globalAlpha = rows.length > 700 ? .68 : .82;
    if (item.completed) { ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill(); }
    else ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
  });
  ctx.globalAlpha = 1;

  const tickCount = Math.min(4, rows.length);
  for (let index = 0; index < tickCount; index++) {
    const rowIndex = tickCount === 1 ? 0 : Math.round((rows.length - 1) * index / (tickCount - 1));
    ctx.fillStyle = colors.muted; ctx.textBaseline = "bottom";
    ctx.textAlign = index === 0 ? "left" : index === tickCount - 1 ? "right" : "center";
    ctx.fillText(rows[rowIndex].start_date, pointX(rowIndex), height - 3);
  }

  if (app.roundStartTimelineHover != null) {
    const index = Math.max(0, Math.min(rows.length - 1, app.roundStartTimelineHover));
    const x = pointX(index), profitY = pointY(rows[index].profit_rate), mddY = pointY(rows[index].close_mdd);
    ctx.strokeStyle = colors.ink; ctx.globalAlpha = .45; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(x, padding.top); ctx.lineTo(x, height - padding.bottom); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
    [[profitY, rows[index].completed ? colors.brand : colors.amber], [mddY, colors.red]].forEach(([y, color]) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill(); ctx.strokeStyle = colors.ink; ctx.lineWidth = 1; ctx.stroke(); });
  } else {
    const summary = app.roundStartResult.summary;
    $("#roundStartTimelineDetail").textContent = `${rows.length.toLocaleString()}개 시작일 · 완료 ${summary.completed_count.toLocaleString()}개 · 평균 MDD ${percent(summary.avg_close_mdd_all, 2)}`;
  }
  canvas._roundTimeline = { rows, padding, pointX, pointY, width, height };
}

function drawRoundStartScatterChart() {
  const canvas = $("#roundStartScatterChart");
  const rows = orderedRoundStartRows();
  if (!canvas || !rows.length || !canvas.offsetParent) return;
  const { context: ctx, width, height } = fitCanvas(canvas);
  const colors = roundChartColors();
  const padding = { left: 55, right: 15, top: 19, bottom: 32 };
  const mdds = rows.map(item => Number(item.close_mdd));
  const profits = rows.map(item => Number(item.profit_rate));
  let xLow = Math.min(-1, ...mdds), xHigh = 0;
  let xRange = Math.max(xHigh - xLow, 1); xLow -= xRange * .06; xRange = xHigh - xLow;
  let yLow = Math.min(0, ...profits), yHigh = Math.max(0, ...profits);
  let yRange = Math.max(yHigh - yLow, 1); yLow -= yRange * .08; yHigh += yRange * .08; yRange = yHigh - yLow;
  const pointX = value => padding.left + (Number(value) - xLow) / xRange * (width - padding.left - padding.right);
  const pointY = value => padding.top + (yHigh - Number(value)) / yRange * (height - padding.top - padding.bottom);

  ctx.clearRect(0, 0, width, height);
  ctx.font = "10px -apple-system, sans-serif"; ctx.textBaseline = "middle";
  for (let index = 0; index < 5; index++) {
    const ratio = index / 4;
    const yValue = yHigh - yRange * ratio, y = padding.top + (height - padding.top - padding.bottom) * ratio;
    ctx.strokeStyle = colors.line; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    ctx.fillStyle = colors.muted; ctx.textAlign = "right"; ctx.fillText(`${number(yValue, 1)}%`, padding.left - 7, y);
    const xValue = xLow + xRange * ratio, x = padding.left + (width - padding.left - padding.right) * ratio;
    ctx.textAlign = index === 0 ? "left" : index === 4 ? "right" : "center"; ctx.textBaseline = "bottom"; ctx.fillText(`${number(xValue, 1)}%`, x, height - 3); ctx.textBaseline = "middle";
  }
  ctx.fillStyle = colors.muted; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillText("수익률", padding.left, 2);
  ctx.textAlign = "right"; ctx.textBaseline = "bottom"; ctx.fillText("종가 MDD", width - padding.right, height - 15);

  const radius = rows.length > 700 ? 1.5 : rows.length > 250 ? 2 : 2.6;
  const coordinates = rows.map((item, index) => ({ item, index, x: pointX(item.close_mdd), y: pointY(item.profit_rate) }));
  coordinates.forEach(({ item, x, y }) => {
    ctx.fillStyle = item.completed ? colors.brand : colors.amber; ctx.globalAlpha = rows.length > 700 ? .42 : .62;
    if (item.completed) { ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill(); }
    else ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
    if (item.reverse_entered) { ctx.globalAlpha = .72; ctx.strokeStyle = colors.blue; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, radius + 2, 0, Math.PI * 2); ctx.stroke(); }
  });
  ctx.globalAlpha = 1;
  if (app.roundStartScatterHover != null) {
    const selected = coordinates.find(point => point.index === app.roundStartScatterHover);
    if (selected) { ctx.strokeStyle = colors.ink; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(selected.x, selected.y, radius + 4, 0, Math.PI * 2); ctx.stroke(); }
  } else {
    const summary = app.roundStartResult.summary;
    $("#roundStartScatterDetail").textContent = `리버스 진입 ${summary.reverse_sample_count.toLocaleString()}개 (${percent(summary.reverse_entry_rate, 1)}) · 최악 MDD ${percent(summary.worst_close_mdd_all, 2)}`;
  }
  canvas._roundScatter = { rows, coordinates, padding, width, height };
}

function drawRoundStartCharts() {
  drawRoundStartTimelineChart();
  drawRoundStartScatterChart();
}

function roundStartTooltipHtml(item) {
  const observed = item.completed ? item.end_date : item.last_observed_at;
  return `<strong>${item.start_date} 시작 · ${item.completed ? "완료" : "미종료"}</strong><div class="tooltip-grid"><span>종료 / 관찰</span><span>${observed}</span><span>수익률</span><span>${percent(item.profit_rate, 3, true)}</span><span>종가 MDD</span><span>${percent(item.close_mdd, 2)}</span><span>기간</span><span>${item.calendar_days.toLocaleString()}일</span><span>최대 T</span><span>${number(item.max_t_value, 3)}</span><span>리버스</span><span>${item.reverse_entered ? "진입" : "없음"}</span></div>`;
}

function showRoundStartTimelineTooltip(event) {
  const canvas = event.currentTarget, info = canvas._roundTimeline;
  if (!info?.rows.length) return;
  const rect = canvas.getBoundingClientRect();
  const localX = event.clientX - rect.left;
  const ratio = Math.max(0, Math.min(1, (localX - info.padding.left) / Math.max(info.width - info.padding.left - info.padding.right, 1)));
  const index = Math.round(ratio * Math.max(info.rows.length - 1, 0));
  if (app.roundStartTimelineHover !== index) { app.roundStartTimelineHover = index; drawRoundStartTimelineChart(); }
  const item = info.rows[index], x = info.pointX(index), y = info.pointY(item.profit_rate);
  const tip = $("#roundStartTimelineTooltip"); tip.innerHTML = roundStartTooltipHtml(item);
  tip.style.left = `${Math.max(6, Math.min(x + 12, rect.width - 225))}px`; tip.style.top = `${Math.max(6, Math.min(y - 55, rect.height - 155))}px`; tip.classList.remove("hidden");
  $("#roundStartTimelineDetail").textContent = `${item.start_date} 시작 · 수익률 ${percent(item.profit_rate, 3, true)} · MDD ${percent(item.close_mdd, 2)} · ${item.calendar_days.toLocaleString()}일`;
}

function showRoundStartScatterTooltip(event) {
  const canvas = event.currentTarget, info = canvas._roundScatter;
  if (!info?.coordinates.length) return;
  const rect = canvas.getBoundingClientRect(), localX = event.clientX - rect.left, localY = event.clientY - rect.top;
  let selected = null, distance = Infinity;
  info.coordinates.forEach(point => { const next = (point.x - localX) ** 2 + (point.y - localY) ** 2; if (next < distance) { selected = point; distance = next; } });
  if (!selected || distance > 225) {
    $("#roundStartScatterTooltip").classList.add("hidden");
    if (app.roundStartScatterHover != null) { app.roundStartScatterHover = null; drawRoundStartScatterChart(); }
    return;
  }
  if (app.roundStartScatterHover !== selected.index) { app.roundStartScatterHover = selected.index; drawRoundStartScatterChart(); }
  const tip = $("#roundStartScatterTooltip"); tip.innerHTML = roundStartTooltipHtml(selected.item);
  tip.style.left = `${Math.max(6, Math.min(selected.x + 12, rect.width - 225))}px`; tip.style.top = `${Math.max(6, Math.min(selected.y - 55, rect.height - 155))}px`; tip.classList.remove("hidden");
  $("#roundStartScatterDetail").textContent = `${selected.item.start_date} · MDD ${percent(selected.item.close_mdd, 2)} → 수익률 ${percent(selected.item.profit_rate, 3, true)}${selected.item.reverse_entered ? " · 리버스 진입" : ""}`;
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

function candleWindow() {
  const total = app.chartPoints.length;
  const requested = Number($("#candleRange").value);
  const size = requested === 0 ? total : Math.min(requested, total);
  if (!app.candleEnd || app.candleEnd > total) app.candleEnd = total;
  app.candleEnd = Math.max(Math.min(app.candleEnd, total), size);
  const end = requested === 0 ? total : app.candleEnd;
  const start = Math.max(0, end - size);
  return { start, end, size, total, bars: app.chartPoints.slice(start, end), showAll: requested === 0 };
}

function drawCandlestick() {
  const canvas = $("#candlestickChart");
  if (!canvas || !app.chartPoints.length || !canvas.offsetParent) return;
  const windowData = candleWindow();
  const bars = windowData.bars;
  if (!bars.length) return;
  const { context: ctx, width, height } = fitCanvas(canvas);
  const padding = { left: 14, right: 74, top: 14, bottom: 28 };
  const volumeHeight = Math.min(86, height * .2);
  const sectionGap = 16;
  const priceBottom = height - padding.bottom - volumeHeight - sectionGap;
  const plotWidth = Math.max(width - padding.left - padding.right, 1);
  const priceHeight = Math.max(priceBottom - padding.top, 1);
  let low = Math.min(...bars.map(item => Number(item.low)));
  let high = Math.max(...bars.map(item => Number(item.high)));
  const rawRange = Math.max(high - low, Math.abs(high) * .005, .01);
  low -= rawRange * .04;
  high += rawRange * .04;
  const priceY = value => padding.top + (high - Number(value)) / (high - low) * priceHeight;
  const slot = plotWidth / bars.length;
  const candleX = index => padding.left + slot * (index + .5);
  const bodyWidth = slot < 2 ? Math.max(slot * .82, .7) : Math.max(3, Math.min(slot * .72, 14));
  const volumeTop = priceBottom + sectionGap;
  const volumeBottom = height - padding.bottom;
  const maxVolume = Math.max(...bars.map(item => Number(item.volume || 0)), 1);

  ctx.clearRect(0, 0, width, height);
  ctx.globalAlpha = 1;
  ctx.lineCap = "butt";
  ctx.font = "10px -apple-system, sans-serif";
  ctx.textBaseline = "middle";
  for (let index = 0; index < 5; index++) {
    const ratio = index / 4;
    const y = padding.top + priceHeight * ratio;
    const value = high - (high - low) * ratio;
    ctx.strokeStyle = "#e5ebe7"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    ctx.fillStyle = "#77827c"; ctx.textAlign = "left"; ctx.fillText(price(value), width - padding.right + 7, y);
  }

  ctx.strokeStyle = "#dce4df"; ctx.beginPath(); ctx.moveTo(padding.left, priceBottom + sectionGap / 2); ctx.lineTo(width - padding.right, priceBottom + sectionGap / 2); ctx.stroke();
  ctx.fillStyle = "#87918c"; ctx.textAlign = "left"; ctx.fillText("거래량", padding.left, volumeTop + 5);

  bars.forEach((item, index) => {
    const x = candleX(index);
    const open = Number(item.open), close = Number(item.close);
    const direction = close > open ? "rise" : close < open ? "fall" : "flat";
    const color = CANDLE_COLORS[direction];
    const volumeValue = Number(item.volume || 0);
    const volumeBarHeight = volumeValue / maxVolume * Math.max(volumeBottom - volumeTop - 6, 1);
    ctx.fillStyle = direction === "rise" ? "rgba(228,63,69,.22)" : direction === "fall" ? "rgba(25,118,210,.20)" : "rgba(120,131,125,.20)";
    ctx.fillRect(x - bodyWidth / 2, volumeBottom - volumeBarHeight, bodyWidth, volumeBarHeight);

    ctx.strokeStyle = color;
    ctx.lineWidth = slot < 2 ? Math.max(slot * .55, .45) : 1.2;
    ctx.beginPath(); ctx.moveTo(x, priceY(item.high)); ctx.lineTo(x, priceY(item.low)); ctx.stroke();

    const openY = priceY(open), closeY = priceY(close);
    const rawBodyHeight = Math.abs(closeY - openY);
    const minimumBodyHeight = slot < 2 ? 1 : 3;
    const bodyHeight = Math.max(rawBodyHeight, minimumBodyHeight);
    const bodyTop = (openY + closeY) / 2 - bodyHeight / 2;
    ctx.fillStyle = color;
    ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
  });

  const tickCount = Math.min(5, bars.length);
  for (let index = 0; index < tickCount; index++) {
    const localIndex = tickCount === 1 ? 0 : Math.round((bars.length - 1) * index / (tickCount - 1));
    const x = candleX(localIndex);
    ctx.fillStyle = "#77827c"; ctx.textBaseline = "bottom";
    ctx.textAlign = index === 0 ? "left" : index === tickCount - 1 ? "right" : "center";
    ctx.fillText(bars[localIndex].date, x, height - 3);
  }

  if (app.candleHoverIndex != null && app.candleHoverIndex >= windowData.start && app.candleHoverIndex < windowData.end) {
    const localIndex = app.candleHoverIndex - windowData.start;
    const x = candleX(localIndex);
    ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = "rgba(20,35,28,.38)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, padding.top); ctx.lineTo(x, volumeBottom); ctx.stroke(); ctx.restore();
  }

  const first = bars[0], last = bars.at(-1);
  $("#candleWindowInfo").textContent = `${first.date} — ${last.date} · ${bars.length.toLocaleString()}거래일`;
  $("#candlePrev").disabled = windowData.showAll || windowData.start === 0;
  $("#candleNext").disabled = windowData.showAll || windowData.end === windowData.total;
  canvas._candles = { ...windowData, slot, padding, plotWidth, width, height };
}

function renderCharts() { drawEquity(); drawDrawdown(); drawCandlestick(); drawRoundStartCharts(); }

function renderAll(result) {
  app.result = result;
  app.executionLimit = 100;
  app.candleEnd = result.equity_curve.length;
  app.candleHoverIndex = null;
  $("#executionCount").textContent = result.executions.length.toLocaleString();
  $("#roundCount").textContent = result.rounds.length.toLocaleString();
  ["#downloadJson", "#downloadCsv", "#downloadReport"].forEach(selector => $(selector).disabled = false);
  $("#candleEmpty").classList.add("hidden");
  $("#candleContent").classList.remove("hidden");
  $("#candleTitle").textContent = `${result.config.symbol} 캔들 차트`;
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
    toast(`실제 거래가격 저장 완료 · ${summary}`);
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

function moveCandleWindow(direction) {
  if (!app.chartPoints.length) return;
  const view = candleWindow();
  if (view.showAll) return;
  app.candleEnd = direction < 0
    ? Math.max(view.size, view.start)
    : Math.min(view.total, view.end + view.size);
  app.candleHoverIndex = null;
  $("#candleTooltip").classList.add("hidden");
  drawCandlestick();
}

function showCandleTooltip(event) {
  const canvas = event.currentTarget;
  const info = canvas._candles;
  if (!info || !info.bars.length) return;
  const rect = canvas.getBoundingClientRect();
  const localX = event.clientX - rect.left;
  if (localX < info.padding.left || localX > info.width - info.padding.right) {
    $("#candleTooltip").classList.add("hidden");
    return;
  }
  const localIndex = Math.max(0, Math.min(info.bars.length - 1, Math.floor((localX - info.padding.left) / info.slot)));
  const globalIndex = info.start + localIndex;
  const point = app.chartPoints[globalIndex];
  const previous = app.chartPoints[globalIndex - 1];
  const change = previous && Number(previous.close) !== 0 ? (Number(point.close) / Number(previous.close) - 1) * 100 : null;
  const intradayChange = Number(point.open) !== 0 ? (Number(point.close) / Number(point.open) - 1) * 100 : null;
  if (app.candleHoverIndex !== globalIndex) {
    app.candleHoverIndex = globalIndex;
    drawCandlestick();
  }
  const tip = $("#candleTooltip");
  tip.innerHTML = `<strong>${point.date}</strong><div class="tooltip-grid"><span>시가</span><span>${price(point.open)}</span><span>고가</span><span>${price(point.high)}</span><span>저가</span><span>${price(point.low)}</span><span>종가</span><span>${price(point.close)}</span><span>시가 대비</span><span class="${intradayChange > 0 ? "candle-rise-text" : intradayChange < 0 ? "candle-fall-text" : ""}">${percent(intradayChange, 3, true)}</span><span>전일 대비</span><span class="${cls(change)}">${percent(change, 3, true)}</span><span>거래량</span><span>${volumeNumber(point.volume)}</span></div>`;
  tip.style.left = `${Math.max(6, Math.min(localX + 14, rect.width - 210))}px`;
  tip.style.top = `${Math.max(6, Math.min(event.clientY - rect.top - 58, rect.height - 190))}px`;
  tip.classList.remove("hidden");
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
$("#dateRangeStart").addEventListener("input", () => syncDateRangeFromSlider("start"));
$("#dateRangeEnd").addEventListener("input", () => syncDateRangeFromSlider("end"));
$("#startDate").addEventListener("change", () => syncDateRangeFromInputs("start"));
$("#endDate").addEventListener("change", () => syncDateRangeFromInputs("end"));
$$('.tab').forEach(button => button.addEventListener("click", () => activateTab(button.dataset.tab)));
$("#executionSearch").addEventListener("input", () => { app.executionLimit = 100; renderExecutions(); });
$("#executionSide").addEventListener("change", () => { app.executionLimit = 100; renderExecutions(); });
$("#executionMore").addEventListener("click", () => { app.executionLimit += 100; renderExecutions(); });
$("#roundStartSearch").addEventListener("input", () => { app.roundStartLimit = 200; renderRoundStartRows(); });
$("#roundStartStatus").addEventListener("change", () => { app.roundStartLimit = 200; renderRoundStartRows(); });
$("#roundStartReverse").addEventListener("change", () => { app.roundStartLimit = 200; renderRoundStartRows(); });
$("#roundStartSort").addEventListener("change", () => { app.roundStartLimit = 200; renderRoundStartRows(); });
$("#roundStartMore").addEventListener("click", () => { app.roundStartLimit += 200; renderRoundStartRows(); });
$("#candleRange").addEventListener("change", () => { app.candleEnd = app.chartPoints.length; app.candleHoverIndex = null; $("#candleTooltip").classList.add("hidden"); drawCandlestick(); });
$("#candlePrev").addEventListener("click", () => moveCandleWindow(-1));
$("#candleNext").addEventListener("click", () => moveCandleWindow(1));
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
  const initialEquity = Number(app.result?.config?.principal || 0);
  const returnRate = value => initialEquity > 0 && value != null ? (Number(value) / initialEquity - 1) * 100 : null;
  const tip = $("#equityTooltip"); tip.innerHTML = `<strong>${point.date}</strong><br>전략 ${money(point.equity)} (${percent(returnRate(point.equity), 2, true)})<br>종목 ${money(point.benchmark_equity)} (${percent(returnRate(point.benchmark_equity), 2, true)})${point.qld_benchmark_equity == null ? "" : `<br>QLD ${money(point.qld_benchmark_equity)} (${percent(returnRate(point.qld_benchmark_equity), 2, true)})`}`; tip.style.left = `${Math.min(localX + 12, rect.width - 220)}px`; tip.style.top = `${Math.max(event.clientY - rect.top - 32, 6)}px`; tip.classList.remove("hidden");
});
$("#equityChart").addEventListener("mouseleave", () => $("#equityTooltip").classList.add("hidden"));
$("#candlestickChart").addEventListener("pointermove", showCandleTooltip);
$("#candlestickChart").addEventListener("pointerleave", () => { app.candleHoverIndex = null; $("#candleTooltip").classList.add("hidden"); drawCandlestick(); });
$("#roundStartTimelineChart").addEventListener("pointermove", showRoundStartTimelineTooltip);
$("#roundStartTimelineChart").addEventListener("pointerleave", () => { app.roundStartTimelineHover = null; $("#roundStartTimelineTooltip").classList.add("hidden"); drawRoundStartTimelineChart(); });
$("#roundStartScatterChart").addEventListener("pointermove", showRoundStartScatterTooltip);
$("#roundStartScatterChart").addEventListener("pointerleave", () => { app.roundStartScatterHover = null; $("#roundStartScatterTooltip").classList.add("hidden"); drawRoundStartScatterChart(); });

init();
