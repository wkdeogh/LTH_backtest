from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from .precision import ZERO, decimal


Symbol = Literal["TQQQ", "SOXL"]
CompoundingType = Literal["compound", "simple"]
FillModel = Literal["intraday_high", "close_only"]


@dataclass(frozen=True)
class PriceBar:
    date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal
    volume: int = 0


@dataclass
class BacktestConfig:
    symbol: str
    split_count: int
    principal: Decimal
    compounding_type: CompoundingType = "compound"
    sell_percent: Decimal | None = None
    fill_model: FillModel = "intraday_high"
    initial_entry: Literal["moc", "web_loc"] = "web_loc"
    first_buy_buffer_percent: Decimal = Decimal("12")
    slippage_bps: Decimal = ZERO
    commission: Decimal = ZERO
    sell_fee_bps: Decimal = ZERO
    annual_risk_free_rate: Decimal = ZERO

    def __post_init__(self) -> None:
        self.symbol = self.symbol.upper()
        self.principal = decimal(self.principal)
        self.sell_percent = decimal(self.sell_percent) if self.sell_percent is not None else None
        self.first_buy_buffer_percent = decimal(self.first_buy_buffer_percent)
        self.slippage_bps = decimal(self.slippage_bps)
        self.commission = decimal(self.commission)
        self.sell_fee_bps = decimal(self.sell_fee_bps)
        self.annual_risk_free_rate = decimal(self.annual_risk_free_rate)
        self.validate()

    def validate(self) -> None:
        if self.symbol not in {"TQQQ", "SOXL"}:
            raise ValueError("지원 종목은 TQQQ와 SOXL입니다.")
        if self.split_count not in {20, 30, 40}:
            raise ValueError("분할 수는 20, 30, 40 중 하나여야 합니다.")
        if self.principal <= ZERO:
            raise ValueError("원금은 0보다 커야 합니다.")
        if self.compounding_type not in {"compound", "simple"}:
            raise ValueError("운용 방식은 compound 또는 simple이어야 합니다.")
        if self.fill_model not in {"intraday_high", "close_only"}:
            raise ValueError("체결 모델은 intraday_high 또는 close_only여야 합니다.")
        if self.initial_entry not in {"moc", "web_loc"}:
            raise ValueError("첫 매수 방식은 moc 또는 web_loc이어야 합니다.")
        for label, value in {
            "첫 매수 버퍼": self.first_buy_buffer_percent,
            "슬리피지": self.slippage_bps,
            "고정 수수료": self.commission,
            "매도 비용": self.sell_fee_bps,
        }.items():
            if value < ZERO:
                raise ValueError(f"{label}은 음수일 수 없습니다.")
        if self.effective_sell_percent <= ZERO:
            raise ValueError("최종 매도 수익률은 0보다 커야 합니다.")

    @property
    def effective_sell_percent(self) -> Decimal:
        if self.sell_percent is not None:
            return self.sell_percent
        return Decimal("15") if self.symbol == "TQQQ" else Decimal("20")


@dataclass
class Execution:
    sequence: int
    round_number: int
    date: str
    mode: str
    side: str
    order_type: str
    label: str
    order_price: Decimal | None
    fill_price: Decimal
    quantity: int
    gross_amount: Decimal
    fees: Decimal
    net_cash_flow: Decimal
    t_before: Decimal
    t_after: Decimal
    t_effect: str
    intraday_triggered: bool = False
    close_below_order_price: bool = False
    realized_profit: Decimal = ZERO


@dataclass
class RoundResult:
    round_number: int
    started_at: str
    ended_at: str
    allocation_principal: Decimal
    starting_equity: Decimal
    ending_equity: Decimal
    profit_amount: Decimal
    profit_rate: Decimal
    calendar_days: int
    trading_days: int
    execution_count: int
    buy_count: int
    sell_count: int
    total_buy_amount: Decimal
    total_sell_amount: Decimal
    total_fees: Decimal
    ending_t_value: Decimal
    close_mdd: Decimal = ZERO
    benchmark_profit_rate: Decimal = ZERO
    mdd_peak_date: str | None = None
    mdd_trough_date: str | None = None


@dataclass
class State:
    allocation_principal: Decimal
    cash_balance: Decimal
    position_qty: int = 0
    avg_price: Decimal = ZERO
    t_value: Decimal = ZERO
    mode: str = "normal"
    reverse_first_sell_done: bool = False
    round_number: int = 1
    round_started_at: str | None = None
    round_start_equity: Decimal = ZERO
    round_trading_days: int = 0
    realized_profit: Decimal = ZERO


@dataclass
class BacktestResult:
    config: dict
    period: dict
    summary: dict
    metrics: dict
    state: dict
    rounds: list[RoundResult]
    executions: list[Execution]
    equity_curve: list[dict]
    monthly_returns: list[dict]
    yearly_returns: list[dict]
    diagnostics: dict
    warnings: list[str] = field(default_factory=list)
