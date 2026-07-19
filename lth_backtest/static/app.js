"use strict";

const app = {
  meta: null,
  result: null,
  analysisMode: "lth_v4",
  executionLimit: 100,
  chartPoints: [],
  equityPoints: [],
  equitySeries: [],
  candleBars: [],
  candleSymbol: "SOXX",
  comparisonPoints: [],
  sweepResult: null,
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
const STRATEGY_SERIES = Object.freeze({
  previous_high: { key: "previous_high", label: "전고점 매매법", color: "#08775b" },
  infinite_v4: { key: "infinite_v4", label: "무한매수법 V4", color: "#7651b8" },
  soxx_buy_hold: { key: "soxx_buy_hold", label: "SOXX", color: "#2865d5" },
  soxl_buy_hold: { key: "soxl_buy_hold", label: "SOXL", color: "#c43e45" },
});

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
  if ($("#runParameterSweep")) $("#runParameterSweep").disabled = active;
}

function selectedAnalysisMode() {
  return $("input[name=analysis_mode]:checked")?.value || "lth_v4";
}

function isPreviousHighResult(result = app.result) {
  return result?.result_type === "previous_high" || result?.result_type === "comparison" || result?.config?.strategy === "previous_high";
}

function resultSlug(result = app.result) {
  if (!result) return "backtest";
  if (result.result_type === "comparison") return "four-strategy-comparison";
  if (isPreviousHighResult(result)) return "previous-high";
  return `${result.config?.symbol || "strategy"}-v4`;
}

function selectedSymbol() {
  return $("input[name=symbol]:checked")?.value || "SOXL";
}

function matchingDatasets(symbol) {
  return (app.meta?.datasets || []).filter(item => item.name.toUpperCase().startsWith(symbol));
}

function datasetByPath(path) {
  return (app.meta?.datasets || []).find(item => item.path === path) || null;
}

function intersectTradingDates(left, right) {
  if (!Array.isArray(left) || !Array.isArray(right)) return [];
  const rightDates = new Set(right);
  return left.filter(dateValue => rightDates.has(dateValue));
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

function datasetOptionHtml(item) {
  return `<option value="${escapeHtml(item.path)}">${item.start} ~ ${item.end} · ${item.rows.toLocaleString()}행 · ${item.price_basis === "actual_split_adjusted" ? "실거래가" : "갱신 필요"}</option>`;
}

function refreshPreviousHighDatasetChoices(force = false) {
  const configure = (symbol, inputSelector, listSelector) => {
    const matches = matchingDatasets(symbol);
    $(listSelector).innerHTML = matches.map(datasetOptionHtml).join("");
    const input = $(inputSelector);
    if (force || !input.value) input.value = matches[0]?.path || `data/${symbol}.csv`;
    return matches.find(item => item.path === input.value) || datasetByPath(input.value);
  };
  const soxx = configure("SOXX", "#soxxCsvPath", "#soxxCsvOptions");
  const soxl = configure("SOXL", "#soxlCsvPath", "#soxlCsvOptions");
  const commonDates = intersectTradingDates(soxx?.dates, soxl?.dates);
  const missing = Math.max((soxx?.dates?.length || 0) + (soxl?.dates?.length || 0) - commonDates.length * 2, 0);
  $("#sharedDatasetInfo").textContent = commonDates.length
    ? `${commonDates[0]} ~ ${commonDates.at(-1)} · 공통 거래일 ${commonDates.length.toLocaleString()}개 · 비공통 행 ${missing.toLocaleString()}개 제외 · 전일 가격 채움 없음`
    : "SOXX와 SOXL 데이터의 공통 거래일을 확인할 수 없습니다. CSV 경로와 전체 데이터 갱신 상태를 확인하세요.";
  return { dates: commonDates };
}

function refreshDatasetChoices(force = false) {
  const symbol = selectedSymbol();
  const matches = matchingDatasets(symbol);
  $("#csvOptions").innerHTML = matches.map(datasetOptionHtml).join("");
  const input = $("#csvPath");
  if (force || !input.value) input.value = matches[0]?.path || `data/${symbol}.csv`;
  const current = matches.find(item => item.path === input.value) || datasetByPath(input.value);
  $("#datasetInfo").textContent = current
    ? current.price_basis === "actual_split_adjusted"
      ? `${current.start} ~ ${current.end} · ${current.rows.toLocaleString()}거래일 · 실제 OHLC · 배당 미보정`
      : `${current.start} ~ ${current.end} · 기존 조정 데이터 · 아래에서 전체 데이터 갱신 필요`
    : "CSV 경로를 직접 입력하거나 데이터를 다운로드하세요.";
  const mode = selectedAnalysisMode();
  if (mode === "lth_v4") configureDateRange(current);
  else configureDateRange(refreshPreviousHighDatasetChoices(force));
}

function setConditionalGroup(element, visible) {
  element.classList.toggle("hidden", !visible);
  if (!element.matches(".tab,.tab-page")) {
    $$('input,select,textarea,button', element).forEach(control => {
      control.disabled = !visible;
      if (control.id === "csvPath" || control.id === "soxxCsvPath" || control.id === "soxlCsvPath") control.required = visible;
    });
  } else if (element.matches(".tab")) element.disabled = !visible;
}

function syncAnalysisMode(refreshDatasets = true) {
  const mode = selectedAnalysisMode();
  app.analysisMode = mode;
  $$('[data-analysis-modes]').forEach(element => {
    const visible = (element.dataset.analysisModes || "").split(/\s+/).includes(mode);
    setConditionalGroup(element, visible);
  });
  if (mode === "compare") {
    const soxl = $('input[name=symbol][value="SOXL"]');
    if (soxl) soxl.checked = true;
  }
  const descriptions = {
    lth_v4: "기존 무한매수법 V4를 단독으로 정밀 분석합니다.",
    previous_high: "SOXX 하락 단계마다 SOXL로 전환하고 전고점 회복 시 SOXX로 복귀합니다.",
    compare: "SOXX·SOXL 거치식, 전고점 매매법, 무한매수법 V4를 동일 조건으로 비교합니다.",
  };
  $("#analysisModeHelp").textContent = descriptions[mode];
  $("#backtestForm button[type=submit] span").textContent = mode === "compare" ? "4전략 비교 실행" : "백테스트 실행";
  if ($(".tab.active")?.classList.contains("hidden")) activateTab("overview");
  ensureCandleSymbolControl();
  if (refreshDatasets) refreshDatasetChoices(true);
}

function resetForm() {
  const form = $("#backtestForm");
  form.reset();
  form.elements.end_date.value = app.meta?.today || new Date().toISOString().slice(0, 10);
  syncAnalysisMode(true);
  toast("기본 설정으로 복원했습니다.");
}

function formPayload() {
  const form = $("#backtestForm");
  const raw = Object.fromEntries(new FormData(form));
  return {
    analysis_mode: raw.analysis_mode || selectedAnalysisMode(),
    // Mode-specific controls are disabled while hidden and therefore absent
    // from FormData.  Keep deterministic V4 defaults so previous-high-only
    // requests never serialize NaN as JSON null.
    symbol: raw.symbol || "SOXL",
    split_count: Number(raw.split_count || 20),
    principal: raw.principal,
    compounding_type: raw.compounding_type || "compound",
    sell_percent: raw.sell_percent || null,
    csv_path: raw.csv_path,
    soxx_csv_path: raw.soxx_csv_path,
    soxl_csv_path: raw.soxl_csv_path,
    trigger_interval_pct: raw.trigger_interval_pct || "5",
    divisions: Number(raw.divisions || 20),
    fractional_shares: Boolean(form.elements.fractional_shares?.checked),
    liquidation_offset_pct: raw.liquidation_offset_pct || "0",
    start_date: raw.start_date,
    end_date: raw.end_date,
    fill_model: raw.fill_model || "intraday_high",
    initial_entry: raw.initial_entry || "web_loc",
    first_buy_buffer_percent: raw.first_buy_buffer_percent || "12",
    annual_risk_free_rate: raw.annual_risk_free_rate,
    slippage_bps: raw.slippage_bps,
    commission: raw.commission,
    sell_fee_bps: raw.sell_fee_bps,
    compare_close_only: Boolean(form.elements.compare_close_only?.checked),
  };
}

function activateTab(name) {
  $$(".tab").forEach(button => button.classList.toggle("active", button.dataset.tab === name));
  $$(".tab-page").forEach(page => page.classList.toggle("active", page.id === `tab-${name}`));
  if (name === "overview" && app.result) requestAnimationFrame(renderCharts);
  if (name === "candles" && app.result) requestAnimationFrame(drawCandlestick);
  if (name === "round-starts" && app.roundStartResult) requestAnimationFrame(drawRoundStartCharts);
  if (name === "comparison" && app.result?.comparison) requestAnimationFrame(drawComparisonCharts);
  if (name === "previous-high" && isPreviousHighResult()) requestAnimationFrame(drawPreviousHighCharts);
  if (name === "sweep" && app.sweepResult) requestAnimationFrame(renderSweepCharts);
}

function summaryCard(label, value, detail = "", valueClass = "") {
  return `<article class="summary-card"><span>${escapeHtml(label)}</span><strong class="${valueClass}">${escapeHtml(value)}</strong>${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</article>`;
}

function renderMetricList(element, items) {
  element.innerHTML = items.map(([label, value, valueClass = ""]) => `<div><dt>${escapeHtml(label)}</dt><dd class="${valueClass}">${escapeHtml(value)}</dd></div>`).join("");
}

function renderPreviousHighOverview(result) {
  $("#emptyState").classList.add("hidden");
  $("#resultsContent").classList.remove("hidden");
  const { config, period, summary, metrics, strategy_metrics: strategy, diagnostics } = result;
  $("#resultTitle").textContent = result.result_type === "comparison" ? "4전략 비교 · 전고점 매매법" : "전고점 매매법 결과";
  $("#resultPeriod").textContent = `${period.start} — ${period.end} · ${Number(period.trading_days).toLocaleString()}거래일`;
  $("#fillBadge").textContent = "시가·종가 확인형";
  $("#modeBadge").textContent = `${number(config.trigger_interval_pct, 2)}% · ${config.divisions}분할`;
  $("#summaryCards").innerHTML = [
    summaryCard("최종 자산", money(summary.ending_equity), `손익 ${money(summary.profit_amount)}`, cls(summary.profit_amount)),
    summaryCard("총수익률", percent(summary.profit_rate, 2, true), `CAGR ${percent(metrics.cagr, 2, true)}`, cls(summary.profit_rate)),
    summaryCard("종가 기준 MDD", percent(metrics.close_mdd), `${metrics.mdd_peak_date} → ${metrics.mdd_trough_date}`, "negative"),
    summaryCard("CAGR / |MDD|", number(metrics.calmar_ratio, 3), `Sharpe ${number(metrics.sharpe_ratio, 3)}`, cls(metrics.calmar_ratio)),
    summaryCard("완료 라운드", Number(summary.completed_rounds || 0).toLocaleString(), `하락 전환 ${Number(strategy.conversion_event_count || 0).toLocaleString()}회`),
    summaryCard("최대 SOXL 비중", percent(strategy.max_soxl_weight), `최대 레버리지 ${number(strategy.max_effective_leverage, 3)}배`),
  ].join("");
  $("#fillComparison").classList.add("hidden");
  $("#mddValue").textContent = percent(metrics.close_mdd);
  $("#mddValue").className = "negative";
  renderMetricList($("#riskMetrics"), [
    ["연환산 변동성", percent(metrics.annual_volatility)],
    ["Sharpe", number(metrics.sharpe_ratio, 3), cls(metrics.sharpe_ratio)],
    ["Sortino", number(metrics.sortino_ratio, 3), cls(metrics.sortino_ratio)],
    ["Calmar", number(metrics.calmar_ratio, 3), cls(metrics.calmar_ratio)],
    ["최고 / 최악 연도", `${percent(metrics.best_yearly_return, 1, true)} / ${percent(metrics.worst_yearly_return, 1, true)}`],
    ["플러스 연도", percent(metrics.positive_year_ratio, 1)],
    ["MDD 회복", metrics.mdd_recovered ? `${metrics.mdd_recovery_date} · ${metrics.mdd_recovery_trading_days}거래일` : "미회복"],
  ]);
  const alignment = diagnostics.alignment || diagnostics.comparison_alignment || {};
  renderMetricList($("#executionDiagnostics"), [
    ["전환 이벤트", `${Number(strategy.conversion_event_count || 0).toLocaleString()}회`],
    ["실행 단계", `${Number(strategy.executed_step_count || 0).toLocaleString()}단계`],
    ["회복 전환", `${Number(diagnostics.recovery_events || 0).toLocaleString()}회`],
    ["주문 수", `${Number(strategy.order_count || summary.order_count || 0).toLocaleString()}건`],
    ["SOXX 완전 소진", strategy.soxx_exhausted ? `있음 · ${percent(strategy.first_exhaustion_drawdown)}` : "없음"],
    ["공통 거래일", `${Number(alignment.common_row_count || period.trading_days || 0).toLocaleString()}일`],
    ["누락 제외", `${Number((alignment.left_only_count || 0) + (alignment.right_only_count || 0)).toLocaleString()}행`],
  ]);
  $("#warningList").innerHTML = (result.warnings || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  app.equityPoints = result.equity_curve || [];
  app.chartPoints = app.equityPoints;
  app.equitySeries = [{ key: "equity", label: "전고점 매매법", color: "#08775b" }];
  $("#equityChartDescription").textContent = "전고점 매매법의 일별 종가 평가액입니다. 네 전략의 동시 비교는 전략 비교 탭에서 확인할 수 있습니다.";
  $("#equityLegend").innerHTML = '<span class="series previous-high">전고점 매매법</span>';
  requestAnimationFrame(renderCharts);
}

function renderOverview(result) {
  if (isPreviousHighResult(result)) return renderPreviousHighOverview(result);
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
  app.equityPoints = app.chartPoints;
  app.equitySeries = [
    ...(app.chartPoints.some(point => point.qld_benchmark_equity != null) ? [{ key: "qld_benchmark_equity", label: "QLD", color: "#d18a18" }] : []),
    { key: "benchmark_equity", label: config.symbol, color: "#2865d5" },
    { key: "equity", label: "무한매수법 V4", color: "#08775b" },
  ];
  $("#equityChartDescription").textContent = "전략·종목 거치식·QLD 거치식의 일별 종가 평가액";
  $("#equityLegend").innerHTML = `<span class="strategy">전략</span><span class="benchmark">${escapeHtml(config.symbol)}</span>${app.chartPoints.some(point => point.qld_benchmark_equity != null) ? '<span class="qld">QLD</span>' : ""}`;
  requestAnimationFrame(renderCharts);
}

function renderExecutions() {
  const source = app.result?.executions || [];
  const query = $("#executionSearch").value.trim().toLowerCase();
  const side = $("#executionSide").value;
  const previousHigh = isPreviousHighResult();
  if (previousHigh) {
    $("#executionHead").innerHTML = "<th>#</th><th>날짜</th><th>라운드</th><th>행동</th><th>트리거</th><th>단계</th><th>체결시점</th><th>SOXX 신호가</th><th>SOXX 체결가</th><th>SOXX 수량 전→후</th><th>SOXL 체결가</th><th>SOXL 수량 전→후</th><th>현금</th><th>평가액</th><th>비용</th><th>주문</th>";
  } else {
    $("#executionHead").innerHTML = "<th>#</th><th>날짜</th><th>모드</th><th>매매</th><th>주문</th><th>구분</th><th>주문가</th><th>체결가</th><th>수량</th><th>거래금액</th><th>비용</th><th>T 전</th><th>T 후</th>";
  }
  const filtered = source.filter(item => {
    const text = previousHigh
      ? `${item.date} ${item.action} ${item.execution_type} ${(item.trigger_steps || []).join(" ")}`
      : `${item.date} ${item.label} ${item.order_type}`;
    const matchesSide = previousHigh || !side || item.side === side;
    return matchesSide && (!query || text.toLowerCase().includes(query));
  });
  const shown = filtered.slice(0, app.executionLimit);
  $("#executionRows").innerHTML = shown.length ? shown.map(item => previousHigh ? `<tr>
    <td>${item.sequence}</td><td>${item.date}</td><td>${item.round_id}</td><td>${escapeHtml(item.action)}</td><td>${item.trigger_level == null ? "-" : price(item.trigger_level)}</td>
    <td>${(item.trigger_steps || []).join(", ") || "-"}</td><td>${item.execution_type === "open" ? "시가" : "종가"}</td><td>${price(item.signal_soxx_price)}</td><td>${price(item.soxx_price)}</td>
    <td>${number(item.soxx_shares_before, 8)} → ${number(item.soxx_shares_after, 8)}</td><td>${price(item.soxl_price)}</td><td>${number(item.soxl_shares_before, 8)} → ${number(item.soxl_shares_after, 8)}</td>
    <td>${money(item.cash)}</td><td>${money(item.total_portfolio_value)}</td><td>${money(item.fees)}</td><td>${Number(item.order_count || 0).toLocaleString()}</td></tr>` : `<tr>
    <td>${item.sequence}</td><td>${item.date}</td><td>${item.mode === "normal" ? "일반" : "리버스"}</td>
    <td><span class="side-pill ${item.side}">${item.side === "buy" ? "매수" : "매도"}</span></td><td>${item.order_type}</td><td>${escapeHtml(item.label)}</td>
    <td>${item.order_price == null ? "-" : money(item.order_price)}</td><td>${money(item.fill_price)}</td><td>${Number(item.quantity).toLocaleString()}</td>
    <td>${money(item.gross_amount)}</td><td>${money(item.fees)}</td><td>${number(item.t_before, 6)}</td><td>${number(item.t_after, 6)}</td></tr>`).join("") : `<tr><td colspan="${previousHigh ? 16 : 13}">조건에 맞는 체결이 없습니다.</td></tr>`;
  $("#executionMore").classList.toggle("hidden", shown.length >= filtered.length);
}

function renderRounds() {
  const rows = app.result?.rounds || [];
  const previousHigh = isPreviousHighResult();
  if (previousHigh) {
    $("#roundHead").innerHTML = "<th>회차</th><th>시작</th><th>첫 전환</th><th>종료</th><th>종료시점</th><th>달력일</th><th>거래일</th><th>회복 거래일</th><th>시작 전고점</th><th>기준금액</th><th>시작자산</th><th>종료자산</th><th>수익률</th><th>SOXX 최대낙폭</th><th>시가·종가 MDD</th><th>시작대비 최대손실</th><th>최대 SOXL 비중</th><th>최대 레버리지</th><th>실행 단계</th><th>전환 이벤트</th><th>SOXX 소진</th><th>비용</th>";
    $("#roundRows").innerHTML = rows.length ? rows.map(item => `<tr><td>${item.round_id}</td><td>${item.start_date}</td><td>${item.first_conversion_date}</td><td>${item.end_date}</td><td>${item.end_phase === "open" ? "시가" : "종가"}</td><td>${item.duration_days}</td><td>${item.duration_trading_days}</td><td>${item.recovery_trading_days}</td><td>${price(item.start_peak)}</td><td>${money(item.basis_amount)}</td><td>${money(item.start_portfolio_value)}</td><td>${money(item.end_portfolio_value)}</td><td class="${cls(item.return_pct)}">${percent(item.return_pct, 3, true)}</td><td class="negative">${percent(item.max_soxx_drawdown, 2)}</td><td class="negative"><strong>${percent(item.max_portfolio_drawdown, 2)}</strong><small class="cell-sub">${item.mdd_peak_date} → ${item.mdd_trough_date}</small></td><td class="negative">${percent(item.max_loss_from_start, 2)}</td><td>${percent(item.max_soxl_weight, 2)}</td><td>${number(item.max_effective_leverage, 3)}배</td><td>${item.number_of_conversion_steps}</td><td>${item.conversion_events}</td><td>${item.soxx_exhausted ? `예 · ${percent(item.exhaustion_drawdown)}` : "아니오"}</td><td>${money(item.total_fees)}</td></tr>`).join("") : '<tr><td colspan="22">완료된 라운드가 없습니다.</td></tr>';
  } else {
    $("#roundHead").innerHTML = "<th>회차</th><th>시작</th><th>종료</th><th>거래일</th><th>운용원금</th><th>시작자산</th><th>종료자산</th><th>손익</th><th>수익률</th><th>종가 MDD</th><th>종목 거치식</th><th>체결</th><th>비용</th>";
    $("#roundRows").innerHTML = rows.length ? rows.map(item => `<tr><td>${item.round_number}</td><td>${item.started_at}</td><td>${item.ended_at}</td><td>${item.trading_days}</td><td>${money(item.allocation_principal)}</td><td>${money(item.starting_equity)}</td><td>${money(item.ending_equity)}</td><td class="${cls(item.profit_amount)}">${money(item.profit_amount)}</td><td class="${cls(item.profit_rate)}">${percent(item.profit_rate, 3, true)}</td><td class="negative"><strong>${percent(item.close_mdd, 2)}</strong><small class="cell-sub">${item.mdd_peak_date} → ${item.mdd_trough_date}</small></td><td class="${cls(item.benchmark_profit_rate)}">${percent(item.benchmark_profit_rate, 3, true)}</td><td>${item.execution_count}</td><td>${money(item.total_fees)}</td></tr>`).join("") : '<tr><td colspan="13">완료된 라운드가 없습니다.</td></tr>';
  }
}

function comparisonStrategy(result, key) {
  return result?.comparison?.strategies?.[key] || null;
}

function hypothesisPoints(value) {
  if (value == null) return "-";
  const numeric = Number(value);
  return `${numeric > 0 ? "+" : ""}${number(numeric, 2)}%p`;
}

function hypothesisPresentation(item) {
  const id = Number(item.id);
  const observed = Boolean(item.passed);
  const status = {
    1: observed ? "V4 대비 초과수익 관찰" : "V4 대비 초과수익 미관찰",
    2: observed ? "SOXX 대비 초과수익 관찰" : "SOXX 대비 초과수익 미관찰",
    3: observed ? "SOXL 대비 MDD 완화 관찰" : "SOXL 대비 MDD 완화 미관찰",
    4: observed ? "약세장 MDD 증가 관찰" : "약세장 MDD 증가 미관찰",
    5: observed ? "완료 라운드 양(+) 평균 관찰" : "완료 라운드 양(+) 평균 미관찰",
  }[id] || (observed ? "조건 관찰" : "조건 미관찰");
  const scope = id === 4
    ? `${item.scope || "분석 구간 미기록"}${item.scope_start && item.scope_end ? ` · ${item.scope_start} ~ ${item.scope_end}` : ""}`
    : id === 5 ? "회복 청산으로 완료된 라운드" : "전체 분석 기간";
  const evidence = {
    1: [["전고점 − V4 총수익률", hypothesisPoints(item.difference_pct_points)]],
    2: [["전고점 − SOXX 총수익률", hypothesisPoints(item.difference_pct_points)]],
    3: [["SOXL 대비 MDD 완화폭", hypothesisPoints(item.difference_pct_points)]],
    4: [
      ["전고점 MDD", percent(item.previous_high_mdd, 2)],
      ["SOXX MDD", percent(item.soxx_mdd, 2)],
      ["MDD 절대값 차이", hypothesisPoints(item.difference_pct_points)],
    ],
    5: [
      ["완료 / 양수 라운드", `${Number(item.completed_rounds || 0).toLocaleString()} / ${Number(item.positive_completed_rounds || 0).toLocaleString()}회`],
      ["양수 라운드 비율", percent(item.positive_completed_round_rate, 1)],
      ["평균 / 최악 수익률", `${percent(item.average_round_return, 2, true)} / ${percent(item.worst_round_return, 2, true)}`],
      ["회복 전환", `${Number(item.recovery_conversion_count || 0).toLocaleString()}회`],
    ],
  }[id] || [["관찰 차이", hypothesisPoints(item.difference_pct_points)]];
  const interpretation = {
    1: "동일 기간 총수익률 차이를 본 결과이며, 상승장 자금 효율의 원인을 단독으로 증명하지 않습니다.",
    2: "SOXX 거치식 대비 총수익률 차이를 본 결과이며, 초과수익의 원인을 단독으로 증명하지 않습니다.",
    3: "SOXL 거치식 대비 종가 MDD 절대값 차이를 본 위험 관찰입니다.",
    4: "표시된 약세장 구간에서 레버리지 위험 증가 여부를 확인한 값이며 다른 국면으로 일반화할 수 없습니다.",
    5: item.interpretation || "완료 라운드의 관찰 성과이며 회복 청산 구조의 인과 효과를 증명하지 않습니다.",
  }[id] || "백테스트 표본에서 계산한 관찰값이며 인과관계를 증명하지 않습니다.";
  const tone = id === 4 && observed ? "caution" : observed ? "observed" : "neutral";
  return { id, status, scope, evidence, interpretation, tone };
}

function renderHypothesisChecks(comparison) {
  const element = $("#comparisonHypothesisGrid");
  if (!element) return;
  const checks = (comparison.hypothesis_checks || [])
    .filter(item => Number(item.id) >= 1 && Number(item.id) <= 5)
    .sort((left, right) => Number(left.id) - Number(right.id));
  if (!checks.length) {
    element.innerHTML = '<div class="hypothesis-empty">가설 관찰 데이터가 없습니다.</div>';
    return;
  }
  element.innerHTML = checks.map(item => {
    const view = hypothesisPresentation(item);
    const evidence = view.evidence.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
    return `<article class="hypothesis-card ${view.tone}">
      <div class="hypothesis-card-head"><span class="hypothesis-id">가설 ${view.id}</span><span class="observation-badge ${view.tone}">${escapeHtml(view.status)}</span></div>
      <h4>${escapeHtml(item.label || `가설 ${view.id}`)}</h4>
      <p class="hypothesis-scope"><strong>관찰 범위</strong>${escapeHtml(view.scope)}</p>
      <dl class="hypothesis-evidence">${evidence}</dl>
      <p class="hypothesis-interpretation">${escapeHtml(view.interpretation)}</p>
    </article>`;
  }).join("");
}

function renderComparison(result) {
  const comparison = result.comparison;
  if (!comparison) return;
  $("#comparisonEmpty").classList.add("hidden");
  $("#comparisonResults").classList.remove("hidden");
  const order = comparison.strategy_order || Object.keys(STRATEGY_SERIES);
  $("#comparisonSummary").innerHTML = order.map(key => {
    const item = comparison.strategies[key];
    return summaryCard(item.label, money(item.summary.ending_equity), `${percent(item.summary.profit_rate, 2, true)} · MDD ${percent(item.metrics.close_mdd, 1)}`, cls(item.summary.profit_rate));
  }).join("");
  renderHypothesisChecks(comparison);
  const metricRows = [
    ["최종 평가금액", item => money(item.summary.ending_equity)],
    ["총수익률", item => percent(item.metrics.total_return, 2, true)],
    ["CAGR", item => percent(item.metrics.cagr, 2, true)],
    ["종가 MDD", item => percent(item.metrics.close_mdd, 2)],
    ["CAGR / |MDD|", item => number(item.metrics.calmar_ratio, 3)],
    ["연환산 변동성", item => percent(item.metrics.annual_volatility, 2)],
    ["Sharpe", item => number(item.metrics.sharpe_ratio, 3)],
    ["Sortino", item => number(item.metrics.sortino_ratio, 3)],
    ["최고 연도", item => `${item.metrics.best_year} · ${percent(item.metrics.best_yearly_return, 1, true)}`],
    ["최악 연도", item => `${item.metrics.worst_year} · ${percent(item.metrics.worst_yearly_return, 1, true)}`],
    ["플러스 연도", item => percent(item.metrics.positive_year_ratio, 1)],
    ["MDD 구간", item => `${item.metrics.mdd_peak_date} → ${item.metrics.mdd_trough_date}`],
    ["MDD 회복", item => item.metrics.mdd_recovered ? `${item.metrics.mdd_recovery_date} · ${item.metrics.mdd_recovery_trading_days}일` : "미회복"],
  ];
  $("#comparisonMetricRows").innerHTML = metricRows.map(([label, format]) => `<tr><td>${label}</td>${order.map(key => `<td>${escapeHtml(format(comparison.strategies[key]))}</td>`).join("")}</tr>`).join("");
  const yearly = comparison.yearly_returns || [];
  $("#comparisonYearRows").innerHTML = yearly.length ? yearly.map(row => `<tr><td>${row.year}</td><td class="${cls(row.soxx_buy_hold)}">${percent(row.soxx_buy_hold, 2, true)}</td><td class="${cls(row.soxl_buy_hold)}">${percent(row.soxl_buy_hold, 2, true)}</td><td class="${cls(row.previous_high)}">${percent(row.previous_high, 2, true)}</td><td class="${cls(row.infinite_v4)}">${percent(row.infinite_v4, 2, true)}</td></tr>`).join("") : '<tr><td colspan="5">연도별 데이터가 없습니다.</td></tr>';
  const annual = comparison.annual_outperformance || {};
  $("#comparisonYearSummary").innerHTML = [
    summaryCard("SOXX보다 우세한 연도", percent(annual.previous_high_over_soxx_rate, 1), `${Number(annual.previous_high_over_soxx_years || 0).toLocaleString()} / ${Number(annual.comparable_years || 0).toLocaleString()}년`),
    summaryCard("V4보다 우세한 연도", percent(annual.previous_high_over_v4_rate, 1), `${Number(annual.previous_high_over_v4_years || 0).toLocaleString()} / ${Number(annual.comparable_years || 0).toLocaleString()}년`),
    summaryCard("SOXX 대비 최대 우위", hypothesisPoints(annual.best_year_vs_soxx_pct_points), annual.best_year_vs_soxx || "-", cls(annual.best_year_vs_soxx_pct_points)),
    summaryCard("SOXX 대비 최대 열위", hypothesisPoints(annual.worst_year_vs_soxx_pct_points), annual.worst_year_vs_soxx || "-", cls(annual.worst_year_vs_soxx_pct_points)),
  ].join("");
  const periods = comparison.period_analysis || [];
  $("#comparisonRegimeRows").innerHTML = periods.length ? periods.map(row => `<tr><td>${escapeHtml(row.period)}</td><td>${row.start}</td><td>${row.end}</td><td>${percent(row.soxx_buy_hold?.total_return, 2, true)}</td><td>${percent(row.soxl_buy_hold?.total_return, 2, true)}</td><td>${percent(row.previous_high?.total_return, 2, true)}</td><td>${percent(row.infinite_v4?.total_return, 2, true)}</td></tr>`).join("") : '<tr><td colspan="7">분석 가능한 하위 구간이 없습니다.</td></tr>';
  app.comparisonPoints = comparison.equity_curve || [];
  requestAnimationFrame(drawComparisonCharts);
}

function renderPreviousHighAnalytics(result) {
  if (!isPreviousHighResult(result)) return;
  $("#previousHighAnalyticsEmpty").classList.add("hidden");
  $("#previousHighAnalyticsResults").classList.remove("hidden");
  const strategy = result.strategy_metrics || {};
  $("#previousHighSummary").innerHTML = [
    summaryCard("완료 라운드", Number(strategy.total_rounds || 0).toLocaleString(), `평균 ${number(strategy.average_round_trading_days, 1)}거래일`),
    summaryCard("라운드 수익률", percent(strategy.average_round_return, 2, true), `최악 ${percent(strategy.worst_round_return, 2, true)}`, cls(strategy.average_round_return)),
    summaryCard("SOXL 비중", percent(strategy.max_soxl_weight, 2), `평균 ${percent(strategy.average_soxl_weight, 2)}`),
    summaryCard("실질 레버리지", `${number(strategy.max_effective_leverage, 3)}배`, `평균 ${number(strategy.average_effective_leverage, 3)}배`),
    summaryCard("최대 실행 단계", Number(strategy.max_conversion_steps_per_round || 0).toLocaleString(), `평균 ${number(strategy.average_conversion_steps_per_round, 2)} · 완료+진행 ${Number(strategy.conversion_step_round_count || 0).toLocaleString()}개`),
    summaryCard("전환 이벤트", `${Number(strategy.total_transfer_event_count || 0).toLocaleString()}회`, `하락 ${Number(strategy.conversion_event_count || 0).toLocaleString()} · 회복 ${Number(strategy.recovery_conversion_count || 0).toLocaleString()} · 주문 ${Number(strategy.order_count || 0).toLocaleString()}건`),
    summaryCard("SOXX 완전 소진", strategy.soxx_exhausted ? "있음" : "없음", strategy.soxx_exhausted ? `최초 ${percent(strategy.first_exhaustion_drawdown, 2)}` : "관찰 기간 내 없음", strategy.soxx_exhausted ? "negative" : ""),
    summaryCard("가장 긴 라운드", `${strategy.longest_round_trading_days == null ? "-" : Number(strategy.longest_round_trading_days).toLocaleString()}거래일`, `중앙값 ${number(strategy.median_round_trading_days, 1)}일`),
  ].join("");
  $("#previousHighAnalysisNote").textContent = `매매 간격 ${number(result.config.trigger_interval_pct, 2)}% · ${result.config.divisions}분할 · ${result.config.fractional_shares ? "소수점 수량" : "정수 수량"} · 청산 오프셋 ${percent(result.config.liquidation_offset_pct, 2, true)}`;
  $("#maxSoxlWeightValue").textContent = percent(strategy.max_soxl_weight, 2);
  $("#maxEffectiveLeverageValue").textContent = `${number(strategy.max_effective_leverage, 3)}배`;
  const buckets = result.drawdown_buckets || [];
  $("#drawdownBucketRows").innerHTML = buckets.map(row => `<tr><td>${row.bucket}</td><td>${Number(row.trading_days || 0).toLocaleString()}</td><td>${percent(row.avg_soxx_weight, 2)}</td><td>${percent(row.avg_soxl_weight, 2)}</td><td>${percent(row.avg_cash_weight, 2)}</td><td>${row.avg_effective_leverage == null ? "-" : `${number(row.avg_effective_leverage, 3)}배`}</td><td class="${cls(row.avg_portfolio_return)}">${percent(row.avg_portfolio_return, 2, true)}</td></tr>`).join("");
  const alignment = result.diagnostics?.alignment || result.comparison?.alignment || {};
  renderMetricList($("#previousHighDiagnostics"), [
    ["공통 거래일", `${Number(alignment.common_row_count || result.period.trading_days || 0).toLocaleString()}일`],
    ["SOXX 전용 행 제외", `${Number(alignment.left_only_count || 0).toLocaleString()}행`],
    ["SOXL 전용 행 제외", `${Number(alignment.right_only_count || 0).toLocaleString()}행`],
    ["최대 도달 단계", `${Number(strategy.max_reached_stage || 0).toLocaleString()}단계`],
    ["실행 단계 합계", `${Number(strategy.executed_step_count || 0).toLocaleString()}단계`],
    ["0주 주문 방지", `${Number(result.diagnostics?.zero_share_attempts || 0).toLocaleString()}회`],
  ]);
  requestAnimationFrame(drawPreviousHighCharts);
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
  if (app.result?.comparison) {
    $("#yearHead").innerHTML = "<th>연도</th><th>SOXX</th><th>SOXL</th><th>전고점 매매법</th><th>무한매수법 V4</th>";
    const rows = app.result.comparison.yearly_returns || [];
    $("#yearRows").innerHTML = rows.length ? [...rows].reverse().map(item => `<tr><td>${item.year}</td><td class="${cls(item.soxx_buy_hold)}">${percent(item.soxx_buy_hold, 3, true)}</td><td class="${cls(item.soxl_buy_hold)}">${percent(item.soxl_buy_hold, 3, true)}</td><td class="${cls(item.previous_high)}">${percent(item.previous_high, 3, true)}</td><td class="${cls(item.infinite_v4)}">${percent(item.infinite_v4, 3, true)}</td></tr>`).join("") : '<tr><td colspan="5">데이터 없음</td></tr>';
  } else {
    $("#yearHead").innerHTML = "<th>연도</th><th>종료자산</th><th>수익률</th>";
    const rows = app.result?.yearly_returns || [];
    $("#yearRows").innerHTML = rows.length ? [...rows].reverse().map(item => `<tr><td>${item.period}</td><td>${money(item.ending_equity)}</td><td class="${cls(item.return_rate)}">${percent(item.return_rate, 3, true)}</td></tr>`).join("") : '<tr><td colspan="3">데이터 없음</td></tr>';
  }
  $("#monthHead").innerHTML = "<th>월</th><th>종료자산</th><th>수익률</th>";
  const render = (selector, rows) => {
    $(selector).innerHTML = rows.length ? [...rows].reverse().map(item => `<tr><td>${item.period}</td><td>${money(item.ending_equity)}</td><td class="${cls(item.return_rate)}">${percent(item.return_rate, 3, true)}</td></tr>`).join("") : `<tr><td colspan="3">데이터 없음</td></tr>`;
  };
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

function drawLineSeriesChart(canvas, points, series, options = {}) {
  if (!canvas || !points.length || !series.length || !canvas.offsetParent) return;
  const { context: ctx, width, height } = fitCanvas(canvas);
  const padding = options.padding || { left: 58, right: 16, top: 15, bottom: 28 };
  const rawValues = points.flatMap(point => series.map(item => Number(point[item.key]))).filter(Number.isFinite);
  if (!rawValues.length) return;
  const useLog = Boolean(options.logScale) && rawValues.every(value => value > 0);
  const transform = value => useLog ? Math.log(Number(value)) : Number(value);
  const inverse = value => useLog ? Math.exp(value) : value;
  let low = Math.min(...rawValues.map(transform));
  let high = Math.max(...rawValues.map(transform));
  if (options.includeZero) { low = Math.min(low, 0); high = Math.max(high, 0); }
  const range = Math.max(high - low, .000001);
  low -= range * .04; high += range * .04;
  const plotWidth = Math.max(width - padding.left - padding.right, 1);
  const plotHeight = Math.max(height - padding.top - padding.bottom, 1);
  const pointX = index => padding.left + plotWidth * index / Math.max(points.length - 1, 1);
  const pointY = value => padding.top + (high - transform(value)) / (high - low) * plotHeight;
  const axisLabel = options.axisLabel || (value => options.percentAxis ? `${number(value, 1)}%` : `$${Math.round(value).toLocaleString()}`);
  ctx.clearRect(0, 0, width, height);
  ctx.font = "10px -apple-system, sans-serif"; ctx.textBaseline = "middle";
  for (let index = 0; index < 5; index++) {
    const y = padding.top + plotHeight * index / 4;
    const transformedValue = high - (high - low) * index / 4;
    ctx.strokeStyle = "#e5ebe7"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    ctx.fillStyle = "#77827c"; ctx.textAlign = "right"; ctx.fillText(axisLabel(inverse(transformedValue)), padding.left - 7, y);
  }
  series.forEach(item => {
    ctx.strokeStyle = item.color; ctx.lineWidth = item.lineWidth || 2; ctx.lineJoin = "round"; ctx.beginPath();
    let started = false;
    points.forEach((point, index) => {
      const value = Number(point[item.key]);
      if (!Number.isFinite(value) || (useLog && value <= 0)) return;
      const x = pointX(index), y = pointY(value);
      if (started) ctx.lineTo(x, y); else { ctx.moveTo(x, y); started = true; }
    });
    ctx.stroke();
  });
  ctx.fillStyle = "#77827c"; ctx.textBaseline = "bottom"; ctx.textAlign = "left"; ctx.fillText(points[0].date, padding.left, height - 2); ctx.textAlign = "right"; ctx.fillText(points.at(-1).date, width - padding.right, height - 2);
  canvas._seriesChart = { points, series, pointX, padding, width, height, useLog };
  canvas._chart = canvas._seriesChart;
}

function drawEquity() {
  drawLineSeriesChart($("#equityChart"), app.equityPoints, app.equitySeries, { logScale: $("#equityLogScale")?.checked });
}

function drawDrawdown() {
  drawLineSeriesChart($("#drawdownChart"), app.equityPoints, [{ key: "drawdown", label: "낙폭", color: "#c43e45" }], { percentAxis: true, includeZero: true, padding: { left: 45, right: 12, top: 12, bottom: 22 } });
}

function drawComparisonCharts() {
  if (!app.comparisonPoints.length) return;
  const series = (app.result?.comparison?.strategy_order || Object.keys(STRATEGY_SERIES)).map(key => ({ ...STRATEGY_SERIES[key], ...(app.result?.comparison?.strategies?.[key] || {}) }));
  drawLineSeriesChart($("#comparisonEquityChart"), app.comparisonPoints, series, { logScale: $("#comparisonEquityLogScale")?.checked });
  drawLineSeriesChart($("#comparisonDrawdownChart"), app.comparisonPoints, series.map(item => ({ ...item, key: `${item.key}_drawdown` })), { percentAxis: true, includeZero: true });
}

function drawPreviousHighCharts() {
  if (!isPreviousHighResult() || !app.result?.equity_curve?.length) return;
  const points = app.result.equity_curve;
  drawLineSeriesChart($("#previousHighSoxlWeightChart"), points, [{ key: "soxl_weight", label: "SOXL 비중", color: "#c43e45" }], { percentAxis: true, includeZero: true });
  drawLineSeriesChart($("#previousHighLeverageChart"), points, [{ key: "effective_leverage", label: "실질 레버리지", color: "#7651b8" }], { includeZero: true, axisLabel: value => `${number(value, 2)}배` });
  drawPreviousHighScatter();
}

function drawPreviousHighScatter() {
  const canvas = $("#previousHighDrawdownWeightChart"), points = app.result?.equity_curve || [];
  if (!canvas || !points.length || !canvas.offsetParent) return;
  const { context: ctx, width, height } = fitCanvas(canvas);
  const padding = { left: 52, right: 18, top: 18, bottom: 34 };
  const minX = Math.min(...points.map(item => Number(item.soxx_drawdown)), -1), maxX = 0;
  const minY = 0, maxY = Math.max(...points.map(item => Number(item.soxl_weight)), 1);
  const x = value => padding.left + (Number(value) - minX) / Math.max(maxX - minX, 1) * (width - padding.left - padding.right);
  const y = value => padding.top + (maxY - Number(value)) / Math.max(maxY - minY, 1) * (height - padding.top - padding.bottom);
  ctx.clearRect(0, 0, width, height); ctx.font = "10px sans-serif"; ctx.fillStyle = "#77827c";
  for (let index = 0; index < 5; index++) {
    const ratio = index / 4, gy = padding.top + (height - padding.top - padding.bottom) * ratio;
    ctx.strokeStyle = "#e5ebe7"; ctx.beginPath(); ctx.moveTo(padding.left, gy); ctx.lineTo(width - padding.right, gy); ctx.stroke();
    ctx.textAlign = "right"; ctx.fillText(`${number(maxY * (1 - ratio), 0)}%`, padding.left - 6, gy + 3);
  }
  points.forEach(point => { ctx.fillStyle = "rgba(8,119,91,.35)"; ctx.beginPath(); ctx.arc(x(point.soxx_drawdown), y(point.soxl_weight), 2.7, 0, Math.PI * 2); ctx.fill(); });
  ctx.fillStyle = "#77827c"; ctx.textAlign = "left"; ctx.fillText(`${number(minX, 1)}%`, padding.left, height - 8); ctx.textAlign = "right"; ctx.fillText("0%", width - padding.right, height - 8);
  canvas._scatter = { points, x, y, padding, width, height };
}

function candleWindow() {
  const total = app.candleBars.length;
  const requested = Number($("#candleRange").value);
  const size = requested === 0 ? total : Math.min(requested, total);
  if (!app.candleEnd || app.candleEnd > total) app.candleEnd = total;
  app.candleEnd = Math.max(Math.min(app.candleEnd, total), size);
  const end = requested === 0 ? total : app.candleEnd;
  const start = Math.max(0, end - size);
  return { start, end, size, total, bars: app.candleBars.slice(start, end), showAll: requested === 0 };
}

function drawCandlestick() {
  const canvas = $("#candlestickChart");
  if (!canvas || !app.candleBars.length || !canvas.offsetParent) return;
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

function ensureCandleSymbolControl() {
  let control = $("#candleSymbolControl");
  if (!control) {
    control = document.createElement("label");
    control.id = "candleSymbolControl";
    control.innerHTML = '<span>차트 종목</span><select id="candleSymbol"><option value="SOXX">SOXX</option><option value="SOXL">SOXL</option></select>';
    $("#candleRange").closest("label").before(control);
    $("#candleSymbol").addEventListener("change", event => {
      app.candleSymbol = event.currentTarget.value;
      configureCandleBars(app.result);
      drawCandlestick();
    });
  }
  control.classList.toggle("hidden", selectedAnalysisMode() === "lth_v4");
}

function normalizedMarketBars(result, symbol) {
  const supplied = result?.market_data?.[symbol];
  if (Array.isArray(supplied) && supplied.length) return supplied;
  if (!isPreviousHighResult(result)) return result?.equity_curve || [];
  const prefix = symbol.toLowerCase();
  return (result?.equity_curve || []).map(point => ({
    date: point.date,
    open: point[`${prefix}_open`], high: point[`${prefix}_high`], low: point[`${prefix}_low`], close: point[`${prefix}_close`], volume: 0,
  })).filter(point => [point.open, point.high, point.low, point.close].every(value => value != null));
}

function configureCandleBars(result) {
  const previousHigh = isPreviousHighResult(result);
  app.candleSymbol = previousHigh ? ($("#candleSymbol")?.value || app.candleSymbol || "SOXX") : (result?.config?.symbol || "SOXL");
  app.candleBars = normalizedMarketBars(result, app.candleSymbol);
  app.candleEnd = app.candleBars.length;
  app.candleHoverIndex = null;
  $("#candleTitle").textContent = `${app.candleSymbol} 캔들 차트`;
  const basis = result?.config?.price_basis
    || result?.diagnostics?.resolved_price_basis
    || result?.diagnostics?.price_basis
    || "unknown";
  const actual = basis === "actual_split_adjusted";
  $("#candleBasisEyebrow").textContent = actual ? "ACTUAL OHLCV" : "INPUT OHLCV";
  $("#candleBasisDescription").textContent = actual
    ? "분할은 반영하지만 배당은 소급 보정하지 않은 실제 시가, 고가, 저가, 종가입니다."
    : `입력 CSV OHLC입니다. 가격 기준: ${basis} · 분할·배당 조정 여부 미확인`;
  $("#candleBasisNote").textContent = actual
    ? "가격축과 캔들은 증권사 가격 차트와 비교 가능한 분할 반영·배당 미보정 OHLC 기준입니다. 종가가 시가보다 높으면 빨강, 낮으면 파랑으로 표시합니다. 거래량은 CSV의 일별 원자료이며, 긴 기간의 전체 기간 보기는 흐름 확인용입니다."
    : `가격 기준은 ${basis}입니다. 엔진이 사용자 CSV의 분할·배당 조정 여부를 확인할 수 없으므로 실제 거래가격으로 단정하지 않습니다. 종가가 시가보다 높으면 빨강, 낮으면 파랑으로 표시합니다.`;
}

function renderCharts() {
  drawEquity(); drawDrawdown(); drawCandlestick(); drawRoundStartCharts();
  drawComparisonCharts(); drawPreviousHighCharts();
  if (app.sweepResult) renderSweepCharts();
}

function renderAll(result) {
  app.result = result;
  app.executionLimit = 100;
  app.analysisMode = result.result_type === "comparison" ? "compare" : isPreviousHighResult(result) ? "previous_high" : "lth_v4";
  configureCandleBars(result);
  $("#executionCount").textContent = Number(result.executions?.length || 0).toLocaleString();
  $("#roundCount").textContent = Number(result.rounds?.length || 0).toLocaleString();
  ["#downloadJson", "#downloadCsv", "#downloadReport"].forEach(selector => $(selector).disabled = false);
  $("#candleEmpty").classList.add("hidden");
  $("#candleContent").classList.remove("hidden");
  renderOverview(result); renderExecutions(); renderRounds(); renderPeriods();
  if (isPreviousHighResult(result)) renderPreviousHighAnalytics(result);
  if (result.comparison) renderComparison(result);
  activateTab("overview");
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

function sweepCandidateValues(name, numeric = false) {
  return $$(`input[name=${name}]:checked`).map(input => numeric ? Number(input.value) : input.value);
}

async function runParameterSweep(event) {
  event?.preventDefault();
  const intervals = sweepCandidateValues("sweep_trigger_intervals");
  const divisions = sweepCandidateValues("sweep_divisions", true);
  if (!intervals.length || !divisions.length) return toast("매매 간격과 분할 수 후보를 각각 하나 이상 선택하세요.", true);
  const payload = { ...formPayload(), analysis_mode: "previous_high", intervals, divisions, subperiod_validation: Boolean($("input[name=sweep_subperiod_validation]")?.checked) };
  setLoading(true, `${(intervals.length * divisions.length).toLocaleString()}개 파라미터 조합을 검증 중입니다`);
  try {
    app.sweepResult = await api("/api/parameter-sweep", payload);
    renderParameterSweep(app.sweepResult);
    activateTab("sweep");
    toast(`${app.sweepResult.rows.length.toLocaleString()}개 파라미터 조합 분석이 완료되었습니다.`);
  } catch (error) { toast(error.message, true); }
  finally { setLoading(false); }
}

function subperiodMinimum(row) {
  const values = Object.entries(row.period_metrics || {}).filter(([name]) => name !== "전체").map(([, value]) => Number(value.cagr)).filter(Number.isFinite);
  return values.length ? Math.min(...values) : null;
}

function renderParameterSweep(result) {
  $("#parameterSweepEmpty").classList.add("hidden");
  $("#parameterSweepResults").classList.remove("hidden");
  $("#downloadSweepCsv").disabled = false;
  const stable = result.stable_regions?.[0];
  const baseline = result.baseline;
  $("#sweepStabilitySummary").innerHTML = [
    summaryCard("분석 조합", `${Number(result.rows.length).toLocaleString()}개`, `${result.axes.intervals.length}간격 × ${result.axes.divisions.length}분할`),
    summaryCard("최고 안정성 조합", stable ? `${number(stable.trigger_interval_pct, 1)}% × ${stable.divisions}` : "-", stable ? `점수 ${number(stable.stability_score, 2)}` : ""),
    summaryCard("안정 조합 CAGR", stable ? percent(stable.cagr, 2, true) : "-", stable ? `MDD ${percent(stable.close_mdd, 2)}` : "", stable ? cls(stable.cagr) : ""),
    summaryCard("기본 5% × 20", baseline ? percent(baseline.cagr, 2, true) : "후보 미포함", baseline ? `MDD ${percent(baseline.close_mdd, 2)} · 안정성 ${number(baseline.stability_score, 1)}` : ""),
  ].join("");
  $("#sweepStabilityNote").textContent = result.methodology?.warning || "단일 최고값보다 인접 조합과 하위 기간에서 성과가 유지되는지 확인하세요.";
  $("#sweepResultRows").innerHTML = result.rows.map(row => `<tr><td>${number(row.trigger_interval_pct, 2)}%</td><td>${row.divisions}</td><td>${money(row.ending_equity)}</td><td class="${cls(row.cagr)}">${percent(row.cagr, 2, true)}</td><td class="negative">${percent(row.close_mdd, 2)}</td><td>${number(row.calmar_ratio, 3)}</td><td>${number(row.sharpe_ratio, 3)}</td><td>${percent(row.max_soxl_weight, 2)}</td><td>${number(row.max_effective_leverage, 3)}배</td><td class="${cls(subperiodMinimum(row))}">${percent(subperiodMinimum(row), 2, true)}</td><td>${number(row.stability_score, 2)}</td></tr>`).join("");
  requestAnimationFrame(renderSweepCharts);
}

function drawHeatmap(canvas, matrix, axes, options = {}) {
  if (!canvas || !canvas.offsetParent || !matrix?.length || !axes?.intervals?.length || !axes?.divisions?.length) return;
  const { context: ctx, width, height } = fitCanvas(canvas);
  const padding = { left: 72, right: 18, top: 24, bottom: 42 };
  const rows = axes.intervals.length, columns = axes.divisions.length;
  const cellWidth = (width - padding.left - padding.right) / columns;
  const cellHeight = (height - padding.top - padding.bottom) / rows;
  const values = matrix.flat().map(Number).filter(Number.isFinite);
  const min = Math.min(...values), max = Math.max(...values), range = Math.max(max - min, .000001);
  const cells = [];
  ctx.clearRect(0, 0, width, height); ctx.font = "10px -apple-system, sans-serif"; ctx.textBaseline = "middle";
  for (let row = 0; row < rows; row++) {
    for (let column = 0; column < columns; column++) {
      const value = Number(matrix[row][column]), ratio = (value - min) / range;
      const x = padding.left + column * cellWidth, y = padding.top + row * cellHeight;
      ctx.fillStyle = `hsl(${8 + ratio * 142} 55% ${88 - ratio * 38}%)`; ctx.fillRect(x + 1, y + 1, Math.max(cellWidth - 2, 1), Math.max(cellHeight - 2, 1));
      if (cellWidth > 46 && cellHeight > 24) { ctx.fillStyle = ratio > .6 ? "#fff" : "#263b31"; ctx.textAlign = "center"; ctx.fillText(options.format(value), x + cellWidth / 2, y + cellHeight / 2); }
      cells.push({ row, column, x, y, width: cellWidth, height: cellHeight, value });
    }
    ctx.fillStyle = "#64716a"; ctx.textAlign = "right"; ctx.fillText(`${number(axes.intervals[row], 2)}%`, padding.left - 8, padding.top + row * cellHeight + cellHeight / 2);
  }
  axes.divisions.forEach((division, column) => { ctx.fillStyle = "#64716a"; ctx.textAlign = "center"; ctx.fillText(String(division), padding.left + column * cellWidth + cellWidth / 2, height - 16); });
  ctx.textAlign = "left"; ctx.fillText("매매 간격", 4, 11); ctx.textAlign = "right"; ctx.fillText("분할 수", width - padding.right, height - 2);
  canvas._heatmap = { cells, axes, options };
}

function renderSweepCharts() {
  const result = app.sweepResult;
  if (!result) return;
  drawHeatmap($("#sweepCagrChart"), result.heatmaps.cagr, result.axes, { format: value => percent(value, 1, true) });
  drawHeatmap($("#sweepMddChart"), result.heatmaps.close_mdd, result.axes, { format: value => percent(value, 1) });
  drawHeatmap($("#sweepCalmarChart"), result.heatmaps.calmar_ratio, result.axes, { format: value => number(value, 2) });
}

function showHeatmapTooltip(event, tooltipSelector) {
  const canvas = event.currentTarget, info = canvas._heatmap;
  if (!info) return;
  const rect = canvas.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
  const cell = info.cells.find(item => x >= item.x && x <= item.x + item.width && y >= item.y && y <= item.y + item.height);
  const tooltip = $(tooltipSelector);
  if (!cell) { tooltip.classList.add("hidden"); return; }
  tooltip.innerHTML = `<strong>${number(info.axes.intervals[cell.row], 2)}% × ${info.axes.divisions[cell.column]}분할</strong><br>${info.options.format(cell.value)}`;
  tooltip.style.left = `${Math.max(6, Math.min(x + 12, rect.width - 180))}px`; tooltip.style.top = `${Math.max(6, y - 48)}px`; tooltip.classList.remove("hidden");
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
    const url = URL.createObjectURL(await response.blob()); const anchor = Object.assign(document.createElement("a"), { href: url, download: `${resultSlug()}-backtest.html` }); anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { toast(error.message, true); }
}

async function refreshPrices() {
  setLoading(true, "SOXX · TQQQ · SOXL · QLD 전체 이력을 다운로드 중입니다");
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
  if (!app.candleBars.length) return;
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
  const point = app.candleBars[globalIndex];
  const previous = app.candleBars[globalIndex - 1];
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

function showSeriesTooltip(event, tooltipSelector, options = {}) {
  const canvas = event.currentTarget, info = canvas._seriesChart;
  if (!info?.points?.length) return;
  const rect = canvas.getBoundingClientRect(), localX = event.clientX - rect.left;
  const ratio = (localX - info.padding.left) / Math.max(info.width - info.padding.left - info.padding.right, 1);
  const index = Math.max(0, Math.min(info.points.length - 1, Math.round(ratio * (info.points.length - 1))));
  const point = info.points[index], principal = Number(app.result?.config?.principal || 0);
  const rows = info.series.map(series => {
    const value = point[series.key];
    const formatted = options.format ? options.format(value) : money(value);
    const returnText = options.includeReturn && principal > 0 && value != null ? ` (${percent((Number(value) / principal - 1) * 100, 2, true)})` : "";
    return `<span style="color:${series.color}">${escapeHtml(series.label)}</span> ${escapeHtml(formatted)}${escapeHtml(returnText)}`;
  }).join("<br>");
  const tip = $(tooltipSelector); tip.innerHTML = `<strong>${point.date}</strong><br>${rows}`;
  tip.style.left = `${Math.max(6, Math.min(localX + 12, rect.width - 235))}px`; tip.style.top = `${Math.max(6, event.clientY - rect.top - 44)}px`; tip.classList.remove("hidden");
}

function showPreviousHighScatterTooltip(event) {
  const canvas = event.currentTarget, info = canvas._scatter;
  if (!info) return;
  const rect = canvas.getBoundingClientRect(), localX = event.clientX - rect.left, localY = event.clientY - rect.top;
  let selected = null, distance = Infinity;
  info.points.forEach(point => {
    const dx = info.x(point.soxx_drawdown) - localX, dy = info.y(point.soxl_weight) - localY, candidate = dx * dx + dy * dy;
    if (candidate < distance) { distance = candidate; selected = point; }
  });
  const tip = $("#previousHighDrawdownWeightTooltip");
  if (!selected || distance > 225) { tip.classList.add("hidden"); return; }
  tip.innerHTML = `<strong>${selected.date}</strong><br>SOXX 낙폭 ${percent(selected.soxx_drawdown, 2)}<br>SOXL 비중 ${percent(selected.soxl_weight, 2)}<br>실질 레버리지 ${number(selected.effective_leverage, 3)}배`;
  tip.style.left = `${Math.max(6, Math.min(localX + 12, rect.width - 210))}px`; tip.style.top = `${Math.max(6, localY - 64)}px`; tip.classList.remove("hidden");
}

async function init() {
  $("#backtestForm").elements.end_date.value = new Date().toISOString().slice(0, 10);
  try {
    app.meta = await api("/api/meta"); $("#serverStatus").textContent = `엔진 ${app.meta.version}`; $("#serverStatus").classList.add("ready");
    $("#backtestForm").elements.end_date.value = app.meta.today; syncAnalysisMode(true);
  } catch (error) { $("#serverStatus").textContent = "연결 실패"; toast(error.message, true); }
}

$("#backtestForm").addEventListener("submit", runBacktest);
$("#randomForm").addEventListener("submit", runRandom);
$("#parameterSweepForm").addEventListener("submit", runParameterSweep);
$("#runRoundStarts").addEventListener("click", runRoundStarts);
$("#resetForm").addEventListener("click", resetForm);
$("#refreshPrices").addEventListener("click", refreshPrices);
$$('input[name=analysis_mode]').forEach(input => input.addEventListener("change", () => syncAnalysisMode(true)));
$$("input[name=symbol]").forEach(input => input.addEventListener("change", () => refreshDatasetChoices(true)));
$("#csvPath").addEventListener("change", () => refreshDatasetChoices(false));
$("#soxxCsvPath").addEventListener("change", () => configureDateRange(refreshPreviousHighDatasetChoices(false)));
$("#soxlCsvPath").addEventListener("change", () => configureDateRange(refreshPreviousHighDatasetChoices(false)));
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
$("#candleRange").addEventListener("change", () => { app.candleEnd = app.candleBars.length; app.candleHoverIndex = null; $("#candleTooltip").classList.add("hidden"); drawCandlestick(); });
$("#candlePrev").addEventListener("click", () => moveCandleWindow(-1));
$("#candleNext").addEventListener("click", () => moveCandleWindow(1));
$("#downloadJson").addEventListener("click", () => app.result && downloadBlob(JSON.stringify(app.result, null, 2), "application/json", `${resultSlug()}-backtest.json`));
$("#downloadCsv").addEventListener("click", () => app.result && downloadBlob(csvText(app.result.executions || []), "text/csv;charset=utf-8", `${resultSlug()}-executions.csv`));
$("#downloadReport").addEventListener("click", downloadReport);
$("#downloadSweepCsv").addEventListener("click", () => {
  if (!app.sweepResult) return;
  const rows = app.sweepResult.rows.map(row => ({ ...row, period_metrics: JSON.stringify(row.period_metrics) }));
  downloadBlob(csvText(rows), "text/csv;charset=utf-8", "previous-high-parameter-sweep.csv");
});
$("#downloadRoundStartsJson").addEventListener("click", () => app.roundStartResult && downloadBlob(JSON.stringify(app.roundStartResult, null, 2), "application/json", `${app.roundStartResult.config.symbol}-round-start-analysis.json`));
$("#downloadRoundStartsCsv").addEventListener("click", () => app.roundStartResult && downloadBlob(csvText(app.roundStartResult.rows), "text/csv;charset=utf-8", `${app.roundStartResult.config.symbol}-round-start-analysis.csv`));
document.addEventListener("keydown", event => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") runBacktest(event); });
window.addEventListener("resize", () => { clearTimeout(app.resizeTimer); app.resizeTimer = setTimeout(renderCharts, 100); });
$("#equityChart").addEventListener("mousemove", event => showSeriesTooltip(event, "#equityTooltip", { includeReturn: true }));
$("#equityChart").addEventListener("mouseleave", () => $("#equityTooltip").classList.add("hidden"));
$("#equityLogScale").addEventListener("change", drawEquity);
$("#comparisonEquityLogScale").addEventListener("change", drawComparisonCharts);
$("#comparisonEquityChart").addEventListener("pointermove", event => showSeriesTooltip(event, "#comparisonEquityTooltip", { includeReturn: true }));
$("#comparisonEquityChart").addEventListener("pointerleave", () => $("#comparisonEquityTooltip").classList.add("hidden"));
$("#comparisonDrawdownChart").addEventListener("pointermove", event => showSeriesTooltip(event, "#comparisonDrawdownTooltip", { format: value => percent(value, 2) }));
$("#comparisonDrawdownChart").addEventListener("pointerleave", () => $("#comparisonDrawdownTooltip").classList.add("hidden"));
$("#previousHighSoxlWeightChart").addEventListener("pointermove", event => showSeriesTooltip(event, "#previousHighSoxlWeightTooltip", { format: value => percent(value, 2) }));
$("#previousHighSoxlWeightChart").addEventListener("pointerleave", () => $("#previousHighSoxlWeightTooltip").classList.add("hidden"));
$("#previousHighLeverageChart").addEventListener("pointermove", event => showSeriesTooltip(event, "#previousHighLeverageTooltip", { format: value => `${number(value, 3)}배` }));
$("#previousHighLeverageChart").addEventListener("pointerleave", () => $("#previousHighLeverageTooltip").classList.add("hidden"));
$("#previousHighDrawdownWeightChart").addEventListener("pointermove", showPreviousHighScatterTooltip);
$("#previousHighDrawdownWeightChart").addEventListener("pointerleave", () => $("#previousHighDrawdownWeightTooltip").classList.add("hidden"));
[["#sweepCagrChart", "#sweepCagrTooltip"], ["#sweepMddChart", "#sweepMddTooltip"], ["#sweepCalmarChart", "#sweepCalmarTooltip"]].forEach(([canvas, tooltip]) => {
  $(canvas).addEventListener("pointermove", event => showHeatmapTooltip(event, tooltip));
  $(canvas).addEventListener("pointerleave", () => $(tooltip).classList.add("hidden"));
});
$("#candlestickChart").addEventListener("pointermove", showCandleTooltip);
$("#candlestickChart").addEventListener("pointerleave", () => { app.candleHoverIndex = null; $("#candleTooltip").classList.add("hidden"); drawCandlestick(); });
$("#roundStartTimelineChart").addEventListener("pointermove", showRoundStartTimelineTooltip);
$("#roundStartTimelineChart").addEventListener("pointerleave", () => { app.roundStartTimelineHover = null; $("#roundStartTimelineTooltip").classList.add("hidden"); drawRoundStartTimelineChart(); });
$("#roundStartScatterChart").addEventListener("pointermove", showRoundStartScatterTooltip);
$("#roundStartScatterChart").addEventListener("pointerleave", () => { app.roundStartScatterHover = null; $("#roundStartScatterTooltip").classList.add("hidden"); drawRoundStartScatterChart(); });

init();
