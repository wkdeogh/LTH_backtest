from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext

from .models import Execution, RoundResult
from .precision import ZERO, decimal, round_money, round_rate


def _period_returns(equity_curve: list[dict], key_length: int, starting_equity: Decimal) -> list[dict]:
    endings: dict[str, tuple[str, Decimal]] = {}
    for point in equity_curve:
        key = point["date"][:key_length]
        endings[key] = (point["date"], decimal(point["equity"]))
    rows: list[dict] = []
    previous = starting_equity
    for key, (date_value, ending) in sorted(endings.items()):
        rate = ((ending / previous) - Decimal("1")) * Decimal("100") if previous > ZERO else ZERO
        rows.append({"period": key, "end_date": date_value, "ending_equity": round_money(ending), "return_rate": round_rate(rate)})
        previous = ending
    return rows


def calculate_metrics(
    equity_curve: list[dict],
    executions: list[Execution],
    rounds: list[RoundResult],
    starting_principal: Decimal,
    annual_risk_free_rate: Decimal,
) -> tuple[dict, list[dict], list[dict]]:
    if not equity_curve:
        return {}, [], []

    peak = decimal(equity_curve[0]["equity"])
    peak_date = equity_curve[0]["date"]
    max_drawdown = ZERO
    max_drawdown_peak = peak_date
    max_drawdown_trough = peak_date
    longest_underwater = 0
    underwater_days = 0
    daily_returns: list[Decimal] = []

    previous_equity: Decimal | None = None
    for point in equity_curve:
        equity = decimal(point["equity"])
        if equity >= peak:
            peak = equity
            peak_date = point["date"]
            underwater_days = 0
        else:
            underwater_days += 1
            longest_underwater = max(longest_underwater, underwater_days)
        drawdown = ((equity / peak) - Decimal("1")) * Decimal("100") if peak > ZERO else ZERO
        point["drawdown"] = round_rate(drawdown)
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            max_drawdown_peak = peak_date
            max_drawdown_trough = point["date"]
        if previous_equity and previous_equity > ZERO:
            daily_returns.append((equity / previous_equity) - Decimal("1"))
        previous_equity = equity

    ending_equity = decimal(equity_curve[-1]["equity"])
    total_return = ((ending_equity / starting_principal) - Decimal("1")) * Decimal("100")
    first_date = datetime.strptime(equity_curve[0]["date"], "%Y-%m-%d")
    last_date = datetime.strptime(equity_curve[-1]["date"], "%Y-%m-%d")
    calendar_days = max((last_date - first_date).days, 1)
    with localcontext() as context:
        context.prec = 34
        years = Decimal(calendar_days) / Decimal("365.2425")
        ratio = ending_equity / starting_principal
        cagr = ((ratio.ln() / years).exp() - Decimal("1")) * Decimal("100") if years > ZERO and ratio > ZERO else total_return
        mean_daily = sum(daily_returns, ZERO) / Decimal(len(daily_returns)) if daily_returns else ZERO
        if len(daily_returns) >= 2:
            variance = sum(((value - mean_daily) ** 2 for value in daily_returns), ZERO) / Decimal(len(daily_returns) - 1)
            volatility_daily = variance.sqrt()
        else:
            volatility_daily = ZERO
        annualizer = Decimal("252").sqrt()
        annual_volatility = volatility_daily * annualizer * Decimal("100")
        risk_free_daily = annual_risk_free_rate / Decimal("100") / Decimal("252")
        sharpe = ((mean_daily - risk_free_daily) / volatility_daily) * annualizer if volatility_daily > ZERO else ZERO
        downside = [min(value - risk_free_daily, ZERO) for value in daily_returns]
        downside_variance = sum((value * value for value in downside), ZERO) / Decimal(len(downside)) if downside else ZERO
        downside_deviation = downside_variance.sqrt() if downside_variance > ZERO else ZERO
        sortino = ((mean_daily - risk_free_daily) / downside_deviation) * annualizer if downside_deviation > ZERO else ZERO
        calmar = cagr / abs(max_drawdown) if max_drawdown < ZERO else ZERO

    positive_rounds = [item.profit_amount for item in rounds if item.profit_amount > ZERO]
    negative_rounds = [item.profit_amount for item in rounds if item.profit_amount < ZERO]
    gross_profit = sum(positive_rounds, ZERO)
    gross_loss = abs(sum(negative_rounds, ZERO))
    profit_factor = gross_profit / gross_loss if gross_loss > ZERO else None
    completed_round_count = len(rounds)
    round_win_rate = (len(positive_rounds) / completed_round_count * 100) if completed_round_count else 0.0
    gross_turnover = sum((item.gross_amount for item in executions), ZERO)
    average_equity = sum((decimal(point["equity"]) for point in equity_curve), ZERO) / Decimal(len(equity_curve))
    exposure_rate = Decimal(sum(1 for point in equity_curve if int(point["position_qty"]) > 0)) / Decimal(len(equity_curve)) * Decimal("100")
    total_fees = sum((item.fees for item in executions), ZERO)
    realized_profit = sum((item.realized_profit for item in executions), ZERO)

    metrics = {
        "total_return": round_rate(total_return),
        "cagr": round_rate(cagr),
        "close_mdd": round_rate(max_drawdown),
        "mdd_peak_date": max_drawdown_peak,
        "mdd_trough_date": max_drawdown_trough,
        "longest_underwater_trading_days": longest_underwater,
        "annual_volatility": round_rate(annual_volatility),
        "sharpe_ratio": round_rate(sharpe),
        "sortino_ratio": round_rate(sortino),
        "calmar_ratio": round_rate(calmar),
        "round_win_rate": round_rate(decimal(round_win_rate)),
        "profit_factor": round_rate(profit_factor) if profit_factor is not None else None,
        "gross_profit": round_money(gross_profit),
        "gross_loss": round_money(gross_loss),
        "realized_profit_before_open_position": round_money(realized_profit),
        "total_fees": round_money(total_fees),
        "turnover": round_money(gross_turnover),
        "turnover_ratio": round_rate((gross_turnover / average_equity) * Decimal("100")) if average_equity > ZERO else ZERO,
        "market_exposure_rate": round_rate(exposure_rate),
    }
    return metrics, _period_returns(equity_curve, 7, starting_principal), _period_returns(equity_curve, 4, starting_principal)
