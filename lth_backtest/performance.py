from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext

from .precision import ONE, ZERO, decimal, round_money, round_rate


def _period_returns(
    equity_curve: list[dict],
    key_length: int,
    starting_principal: Decimal,
    equity_key: str,
) -> list[dict]:
    endings: dict[str, tuple[str, Decimal]] = {}
    for point in equity_curve:
        period = str(point["date"])[:key_length]
        endings[period] = (str(point["date"]), decimal(point[equity_key]))

    rows: list[dict] = []
    previous = starting_principal
    for period, (end_date, ending_equity) in sorted(endings.items()):
        return_rate = (
            ((ending_equity / previous) - ONE) * Decimal("100")
            if previous > ZERO
            else ZERO
        )
        rows.append({
            "period": period,
            "end_date": end_date,
            "ending_equity": round_money(ending_equity),
            "return_rate": round_rate(return_rate),
        })
        previous = ending_equity
    return rows


def calculate_equity_performance(
    equity_curve: list[dict],
    principal: Decimal,
    annual_risk_free_rate: Decimal,
    equity_key: str = "equity",
) -> tuple[dict, list[dict], list[dict]]:
    """Calculate deterministic close-to-close performance for any equity series.

    All arithmetic stays in ``Decimal``. The supplied curve must be in strict
    ascending date order and each row is mutated with a percentage
    ``drawdown`` value based on ``equity_key``.
    """
    if not equity_curve:
        return {}, [], []

    principal = decimal(principal)
    annual_risk_free_rate = decimal(annual_risk_free_rate)
    if principal <= ZERO:
        raise ValueError("성과 계산 원금은 0보다 커야 합니다.")

    parsed_dates: list[datetime] = []
    equities: list[Decimal] = []
    previous_date: datetime | None = None
    for point in equity_curve:
        if "date" not in point:
            raise ValueError("자산곡선에 date가 없습니다.")
        if equity_key not in point:
            raise ValueError(f"자산곡선에 {equity_key}가 없습니다.")
        try:
            parsed_date = datetime.strptime(str(point["date"]), "%Y-%m-%d")
        except ValueError as error:
            raise ValueError(f"자산곡선 날짜 형식이 올바르지 않습니다: {point['date']}") from error
        if previous_date is not None and parsed_date <= previous_date:
            raise ValueError("자산곡선 날짜는 중복 없이 오름차순이어야 합니다.")
        equity = decimal(point[equity_key])
        if not equity.is_finite() or equity < ZERO:
            raise ValueError("자산곡선 평가금액은 유한한 0 이상의 값이어야 합니다.")
        parsed_dates.append(parsed_date)
        equities.append(equity)
        previous_date = parsed_date

    peak_equity = equities[0]
    peak_index = 0
    max_drawdown = ZERO
    mdd_peak_index = 0
    mdd_trough_index = 0
    mdd_peak_equity = peak_equity
    longest_underwater_trading_days = 0
    longest_underwater_calendar_days = 0
    longest_underwater_start_date: str | None = None
    longest_underwater_end_date: str | None = None
    daily_returns: list[Decimal] = []

    for index, (point, equity) in enumerate(zip(equity_curve, equities)):
        if equity >= peak_equity:
            peak_equity = equity
            peak_index = index
        drawdown = ((equity / peak_equity) - ONE) * Decimal("100") if peak_equity > ZERO else ZERO
        point["drawdown"] = round_rate(drawdown)
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            mdd_peak_index = peak_index
            mdd_trough_index = index
            mdd_peak_equity = peak_equity
        if drawdown < ZERO:
            underwater_trading_days = index - peak_index
            underwater_calendar_days = (parsed_dates[index] - parsed_dates[peak_index]).days
            if (
                underwater_trading_days > longest_underwater_trading_days
                or (
                    underwater_trading_days == longest_underwater_trading_days
                    and underwater_calendar_days > longest_underwater_calendar_days
                )
            ):
                longest_underwater_trading_days = underwater_trading_days
                longest_underwater_calendar_days = underwater_calendar_days
                longest_underwater_start_date = str(equity_curve[peak_index]["date"])
                longest_underwater_end_date = str(point["date"])
        if index > 0 and equities[index - 1] > ZERO:
            daily_returns.append((equity / equities[index - 1]) - ONE)

    mdd_recovery_index: int | None = None
    if max_drawdown < ZERO:
        for index in range(mdd_trough_index + 1, len(equities)):
            if equities[index] >= mdd_peak_equity:
                mdd_recovery_index = index
                break
    else:
        mdd_recovery_index = mdd_peak_index

    mdd_peak_date = str(equity_curve[mdd_peak_index]["date"])
    mdd_trough_date = str(equity_curve[mdd_trough_index]["date"])
    mdd_recovery_date = (
        str(equity_curve[mdd_recovery_index]["date"])
        if mdd_recovery_index is not None
        else None
    )
    mdd_decline_trading_days = mdd_trough_index - mdd_peak_index
    mdd_decline_calendar_days = (
        parsed_dates[mdd_trough_index] - parsed_dates[mdd_peak_index]
    ).days
    mdd_recovery_trading_days = (
        mdd_recovery_index - mdd_trough_index
        if mdd_recovery_index is not None
        else None
    )
    mdd_recovery_calendar_days = (
        (parsed_dates[mdd_recovery_index] - parsed_dates[mdd_trough_index]).days
        if mdd_recovery_index is not None
        else None
    )
    underwater_end_index = mdd_recovery_index if mdd_recovery_index is not None else len(equity_curve) - 1
    mdd_underwater_trading_days = underwater_end_index - mdd_peak_index
    mdd_underwater_calendar_days = (
        parsed_dates[underwater_end_index] - parsed_dates[mdd_peak_index]
    ).days

    ending_equity = equities[-1]
    total_return = ((ending_equity / principal) - ONE) * Decimal("100")
    calendar_days = max((parsed_dates[-1] - parsed_dates[0]).days, 1)
    with localcontext() as context:
        context.prec = 34
        years = Decimal(calendar_days) / Decimal("365.2425")
        ending_ratio = ending_equity / principal
        cagr = (
            ((ending_ratio.ln() / years).exp() - ONE) * Decimal("100")
            if years > ZERO and ending_ratio > ZERO
            else total_return
        )
        mean_daily = (
            sum(daily_returns, ZERO) / Decimal(len(daily_returns))
            if daily_returns
            else ZERO
        )
        if len(daily_returns) >= 2:
            variance = sum(
                ((value - mean_daily) ** 2 for value in daily_returns),
                ZERO,
            ) / Decimal(len(daily_returns) - 1)
            daily_volatility = variance.sqrt()
        else:
            daily_volatility = ZERO
        annualizer = Decimal("252").sqrt()
        annual_volatility = daily_volatility * annualizer * Decimal("100")
        risk_free_daily = annual_risk_free_rate / Decimal("100") / Decimal("252")
        sharpe = (
            ((mean_daily - risk_free_daily) / daily_volatility) * annualizer
            if daily_volatility > ZERO
            else ZERO
        )
        downside_returns = [min(value - risk_free_daily, ZERO) for value in daily_returns]
        downside_variance = (
            sum((value * value for value in downside_returns), ZERO) / Decimal(len(downside_returns))
            if downside_returns
            else ZERO
        )
        downside_deviation = downside_variance.sqrt() if downside_variance > ZERO else ZERO
        sortino = (
            ((mean_daily - risk_free_daily) / downside_deviation) * annualizer
            if downside_deviation > ZERO
            else ZERO
        )
        calmar = cagr / abs(max_drawdown) if max_drawdown < ZERO else ZERO
        sharpe_status = "finite" if daily_volatility > ZERO else "undefined_zero_volatility"
        sortino_status = (
            "finite"
            if downside_deviation > ZERO
            else ("unbounded_no_downside" if mean_daily > risk_free_daily else "undefined_zero_downside")
        )
        calmar_status = (
            "finite"
            if max_drawdown < ZERO
            else ("unbounded_no_drawdown" if cagr > ZERO else "undefined_no_drawdown")
        )

    monthly_returns = _period_returns(equity_curve, 7, principal, equity_key)
    yearly_returns = _period_returns(equity_curve, 4, principal, equity_key)
    best_year_row = max(yearly_returns, key=lambda row: decimal(row["return_rate"]))
    worst_year_row = min(yearly_returns, key=lambda row: decimal(row["return_rate"]))
    positive_year_count = sum(1 for row in yearly_returns if decimal(row["return_rate"]) > ZERO)
    positive_year_ratio = (
        Decimal(positive_year_count) / Decimal(len(yearly_returns)) * Decimal("100")
        if yearly_returns
        else ZERO
    )

    metrics = {
        "ending_equity": round_money(ending_equity),
        "total_return": round_rate(total_return),
        "cagr": round_rate(cagr),
        "close_mdd": round_rate(max_drawdown),
        "mdd_peak_date": mdd_peak_date,
        "mdd_trough_date": mdd_trough_date,
        "mdd_recovery_date": mdd_recovery_date,
        "mdd_recovered": mdd_recovery_index is not None,
        "mdd_decline_calendar_days": mdd_decline_calendar_days,
        "mdd_decline_trading_days": mdd_decline_trading_days,
        "mdd_recovery_calendar_days": mdd_recovery_calendar_days,
        "mdd_recovery_trading_days": mdd_recovery_trading_days,
        "mdd_underwater_calendar_days": mdd_underwater_calendar_days,
        "mdd_underwater_trading_days": mdd_underwater_trading_days,
        "longest_underwater_calendar_days": longest_underwater_calendar_days,
        "longest_underwater_trading_days": longest_underwater_trading_days,
        "longest_underwater_start_date": longest_underwater_start_date,
        "longest_underwater_end_date": longest_underwater_end_date,
        "annual_volatility": round_rate(annual_volatility),
        "sharpe_ratio": round_rate(sharpe),
        "sharpe_ratio_status": sharpe_status,
        "sortino_ratio": round_rate(sortino),
        "sortino_ratio_status": sortino_status,
        "calmar_ratio": round_rate(calmar),
        "calmar_ratio_status": calmar_status,
        "best_year": best_year_row["period"],
        "best_yearly_return": decimal(best_year_row["return_rate"]),
        "worst_year": worst_year_row["period"],
        "worst_yearly_return": decimal(worst_year_row["return_rate"]),
        "positive_year_count": positive_year_count,
        "year_count": len(yearly_returns),
        "positive_year_ratio": round_rate(positive_year_ratio),
    }
    return metrics, monthly_returns, yearly_returns
