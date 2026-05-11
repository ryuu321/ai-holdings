"""
マルチ銘柄ポートフォリオ管理
長期・中期・短期ボット用
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
import json
from pathlib import Path

STATE_DIR = Path(__file__).parent.parent / "data"


@dataclass
class Position:
    ticker: str
    shares: float
    buy_price: float
    bought_at: str
    cost_basis: float
    peak_price: float = 0.0             # トレーリングストップ用・最高値を追跡
    ladder_hits: list = field(default_factory=list)   # 発火済みラダー段（"0.05","0.10"…）
    last_dca_date: str = ""             # 最後にDCA売却した日時（ISO文字列）

    def __post_init__(self):
        if self.peak_price == 0.0:
            self.peak_price = self.buy_price
        if not isinstance(self.ladder_hits, list):
            self.ladder_hits = []


@dataclass
class TradeRecord:
    timestamp: str
    action: str
    ticker: str
    price: float
    shares: float
    value_usd: float
    balance_after: float
    pnl: float = 0.0
    reasoning: str = ""
    confidence: float = 0.0
    risk_level: str = "MEDIUM"
    signals_json: object = None   # 発火シグナルのリスト（学習用）


class Portfolio:
    """複数銘柄を管理するポートフォリオ（利確・損切り・トレーリングストップ付き）"""

    def __init__(self,
                 initial_balance: float = 10000.0,
                 risk_per_trade: float = 0.15,
                 max_positions: int = 5,
                 state_file: str = "portfolio.json",
                 take_profit_pct: float = 0.20,      # +20%で利確
                 stop_loss_pct: float = 0.10,         # -10%で損切り
                 trailing_stop_pct: float = 0.07,     # 高値から-7%でトレーリング
                 disable_price_exits: bool = False):  # Trueにすると価格ベース出口ルールを無効化
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.max_positions = max_positions
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.disable_price_exits = disable_price_exits
        self._state_path = STATE_DIR / state_file

        self.balance = initial_balance
        self.positions: dict[str, Position] = {}
        self.short_positions: dict[str, Position] = {}  # 空売りポジション
        self.trade_history: list[TradeRecord] = []
        self._load()

    # ── 利確・損切りチェック ──────────────────────────────
    def check_exits(self, ticker: str, current_price: float) -> tuple[bool, str]:
        """
        利確・損切り・トレーリングストップの判断
        disable_price_exits=True の場合は常に (False, "") を返す（長期マクロ保有用）
        戻り値: (売るべきか, 理由)
        """
        pos = self.positions.get(ticker)
        if not pos:
            return False, ""

        # 価格ベースの出口ルールが無効な場合（マクロ予測ボット用）
        if self.disable_price_exits:
            return False, ""

        change_pct = (current_price - pos.buy_price) / pos.buy_price

        # 1. 利確
        if change_pct >= self.take_profit_pct:
            return True, f"利確: +{change_pct*100:.1f}% (閾値+{self.take_profit_pct*100:.0f}%)"

        # 2. 損切り
        if change_pct <= -self.stop_loss_pct:
            return True, f"損切り: {change_pct*100:.1f}% (閾値-{self.stop_loss_pct*100:.0f}%)"

        # 3. トレーリングストップ（高値から一定以上落ちたら売り）
        if current_price > pos.peak_price:
            pos.peak_price = current_price
            self._save()
        drop_from_peak = (current_price - pos.peak_price) / pos.peak_price
        if drop_from_peak <= -self.trailing_stop_pct:
            return True, f"トレーリングストップ: 高値${pos.peak_price:,.2f}から{drop_from_peak*100:.1f}% (閾値-{self.trailing_stop_pct*100:.0f}%)"

        return False, ""

    # ── 永続化 ────────────────────────────────────────────
    def _pos_dict(self, p: Position) -> dict:
        return {
            "ticker": p.ticker, "shares": p.shares, "buy_price": p.buy_price,
            "bought_at": p.bought_at, "cost_basis": p.cost_basis, "peak_price": p.peak_price,
            "ladder_hits": p.ladder_hits, "last_dca_date": p.last_dca_date,
        }

    def _save(self):
        from datetime import datetime, timezone
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "last_run": datetime.now(timezone.utc).isoformat(),
            "positions": {t: self._pos_dict(p) for t, p in self.positions.items()},
            "short_positions": {t: self._pos_dict(p) for t, p in self.short_positions.items()},
        }
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not self._state_path.exists():
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            self.balance = data.get("balance", self.balance)
            self.initial_balance = data.get("initial_balance", self.initial_balance)
            self.positions = {t: Position(**p) for t, p in data.get("positions", {}).items()}
            self.short_positions = {t: Position(**p) for t, p in data.get("short_positions", {}).items()}
            shorts = list(self.short_positions.keys())
            print(f"[PF] 状態ロード: 現金=${self.balance:,.2f}  保有={list(self.positions.keys())}"
                  + (f"  空売り={shorts}" if shorts else ""))
        except Exception as e:
            print(f"[PF] 状態ロード失敗（新規スタート）: {e}")

    def buy(self, ticker: str, price: float, reasoning: str = "",
            confidence: float = 0.5, risk_level: str = "MEDIUM",
            invest_usd: float = None) -> Optional[TradeRecord]:
        """
        invest_usd: Kellyなどで計算した投資額を直接指定できる（省略時はrisk_per_trade使用）
        """
        if ticker in self.positions:
            return None
        if len(self.positions) >= self.max_positions:
            return None
        invest = invest_usd if invest_usd is not None else self.balance * self.risk_per_trade
        invest = min(invest, self.balance)  # 残高を超えないよう保護
        if invest < 1:
            return None
        shares = invest / price
        self.balance -= invest
        self.positions[ticker] = Position(
            ticker=ticker, shares=shares, buy_price=price,
            bought_at=datetime.now(timezone.utc).isoformat(),
            cost_basis=invest, peak_price=price,
        )
        record = TradeRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="BUY", ticker=ticker, price=price,
            shares=shares, value_usd=invest, balance_after=self.balance,
            reasoning=reasoning, confidence=confidence, risk_level=risk_level,
        )
        self.trade_history.append(record)
        self._save()
        return record

    def sell(self, ticker: str, price: float, reasoning: str = "",
             confidence: float = 0.5, risk_level: str = "MEDIUM") -> Optional[TradeRecord]:
        if ticker not in self.positions:
            return None
        pos = self.positions.pop(ticker)
        sell_value = pos.shares * price
        pnl = sell_value - pos.cost_basis
        self.balance += sell_value
        record = TradeRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="SELL", ticker=ticker, price=price,
            shares=pos.shares, value_usd=sell_value, balance_after=self.balance,
            pnl=pnl, reasoning=reasoning, confidence=confidence, risk_level=risk_level,
        )
        self.trade_history.append(record)
        self._save()
        return record

    # ── 空売り ────────────────────────────────────────────
    def sell_short(self, ticker: str, price: float, reasoning: str = "",
                   confidence: float = 0.5, risk_level: str = "MEDIUM") -> Optional[TradeRecord]:
        """空売りポジションを建てる（売り→買い戻しで利益）"""
        if ticker in self.short_positions:
            return None
        invest = self.balance * self.risk_per_trade
        if invest < 1:
            return None
        shares = invest / price
        self.balance -= invest  # 証拠金として引き落とし
        self.short_positions[ticker] = Position(
            ticker=ticker, shares=shares, buy_price=price,
            bought_at=datetime.now(timezone.utc).isoformat(),
            cost_basis=invest, peak_price=price,  # peak_price=安値追跡（下がるほど有利）
        )
        record = TradeRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="SELL", ticker=ticker, price=price,
            shares=shares, value_usd=invest, balance_after=self.balance,
            reasoning=reasoning, confidence=confidence, risk_level=risk_level,
        )
        record.is_short = True
        self.trade_history.append(record)
        self._save()
        return record

    def cover(self, ticker: str, price: float, reasoning: str = "",
              confidence: float = 0.5, risk_level: str = "MEDIUM") -> Optional[TradeRecord]:
        """空売りポジションを買い戻す（決済）"""
        if ticker not in self.short_positions:
            return None
        pos = self.short_positions.pop(ticker)
        pnl = (pos.buy_price - price) * pos.shares  # 下がれば+、上がれば-
        self.balance += pos.cost_basis + pnl  # 証拠金返却 + 損益
        record = TradeRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="BUY", ticker=ticker, price=price,
            shares=pos.shares, value_usd=pos.shares * price, balance_after=self.balance,
            pnl=pnl, reasoning=reasoning, confidence=confidence, risk_level=risk_level,
        )
        record.is_short = True
        self.trade_history.append(record)
        self._save()
        return record

    def check_short_exits(self, ticker: str, current_price: float) -> tuple[bool, str]:
        """空売りポジションの利確・損切りチェック"""
        pos = self.short_positions.get(ticker)
        if not pos:
            return False, ""
        change_pct = (current_price - pos.buy_price) / pos.buy_price
        if change_pct <= -self.take_profit_pct:
            return True, f"空売り利確: {change_pct*100:.1f}%下落 (閾値-{self.take_profit_pct*100:.0f}%)"
        if change_pct >= self.stop_loss_pct:
            return True, f"空売り損切り: +{change_pct*100:.1f}%上昇 (閾値+{self.stop_loss_pct*100:.0f}%)"
        # トレーリング（安値から一定以上戻したら決済）
        if current_price < pos.peak_price:
            pos.peak_price = current_price
            self._save()
        rise_from_low = (current_price - pos.peak_price) / pos.peak_price if pos.peak_price else 0
        if rise_from_low >= self.trailing_stop_pct:
            return True, f"空売りトレーリング: 安値${pos.peak_price:,.2f}から+{rise_from_low*100:.1f}%"
        return False, ""

    # ── 部分売却 ──────────────────────────────────────────
    def partial_sell(self, ticker: str, price: float, fraction: float,
                     reasoning: str = "", confidence: float = 0.5,
                     risk_level: str = "MEDIUM",
                     ladder_key: str = None,
                     update_dca: bool = False) -> Optional[TradeRecord]:
        """ポジションの fraction（0〜1）分を売却する"""
        pos = self.positions.get(ticker)
        if not pos:
            return None
        fraction = min(max(fraction, 0.0), 1.0)
        sell_shares = pos.shares * fraction
        sell_cost   = pos.cost_basis * fraction
        sell_value  = sell_shares * price
        pnl         = sell_value - sell_cost
        self.balance += sell_value
        record = TradeRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="SELL", ticker=ticker, price=price,
            shares=sell_shares, value_usd=sell_value, balance_after=self.balance,
            pnl=pnl, reasoning=reasoning, confidence=confidence, risk_level=risk_level,
        )
        self.trade_history.append(record)
        # ポジション残量を更新
        remaining = pos.shares - sell_shares
        if fraction >= 1.0 or remaining * price < 0.01:
            self.positions.pop(ticker)
        else:
            pos.shares     -= sell_shares
            pos.cost_basis -= sell_cost
            if ladder_key and ladder_key not in pos.ladder_hits:
                pos.ladder_hits.append(ladder_key)
            if update_dca:
                pos.last_dca_date = datetime.now(timezone.utc).isoformat()
        self._save()
        return record

    # ── ラダー利確チェック（MEDIUM用） ──────────────────────
    def check_ladder_exits(self, ticker: str, current_price: float,
                           targets=None) -> tuple[bool, float, str, str]:
        """
        段階的利確チェック。
        戻り値: (売るべきか, 売却比率, 理由, ラダーキー)
        targets: [(profit_pct, sell_fraction), ...]
        """
        if targets is None:
            targets = [(0.05, 0.33), (0.10, 0.33), (0.15, 1.0)]
        pos = self.positions.get(ticker)
        if not pos:
            return False, 0.0, "", ""
        change_pct = (current_price - pos.buy_price) / pos.buy_price
        for profit_pct, fraction in targets:
            key = f"{profit_pct:.2f}"
            if key in pos.ladder_hits:
                continue
            if change_pct >= profit_pct:
                return (True, fraction,
                        f"ラダー利確 +{profit_pct*100:.0f}%: {fraction*100:.0f}%売却", key)
        return False, 0.0, "", ""

    # ── DCA週次売却チェック（LONG用） ────────────────────────
    def check_dca_sell(self, ticker: str, current_price: float,
                       interval_days: int = 7,
                       fraction: float = 0.20) -> tuple[bool, float, str]:
        """
        含み益がある場合、interval_days ごとに fraction 分売却。
        戻り値: (売るべきか, 売却比率, 理由)
        """
        pos = self.positions.get(ticker)
        if not pos:
            return False, 0.0, ""
        if current_price <= pos.buy_price:
            return False, 0.0, ""
        now = datetime.now(timezone.utc)
        if pos.last_dca_date:
            last = datetime.fromisoformat(pos.last_dca_date)
        else:
            last = datetime.fromisoformat(pos.bought_at)
        if now - last < timedelta(days=interval_days):
            return False, 0.0, ""
        change_pct = (current_price - pos.buy_price) / pos.buy_price
        return (True, fraction,
                f"DCA週次利確: +{change_pct*100:.1f}%  {fraction*100:.0f}%売却")

    # ── 損切り＋トレーリングのみ（ラダー/DCA用・利確なし版） ──
    def check_stop_exits(self, ticker: str, current_price: float) -> tuple[bool, str]:
        """損切り・トレーリングストップのみ判定（利確はラダーに委ねる）"""
        pos = self.positions.get(ticker)
        if not pos:
            return False, ""
        if self.disable_price_exits:
            return False, ""
        change_pct = (current_price - pos.buy_price) / pos.buy_price
        if change_pct <= -self.stop_loss_pct:
            return True, f"損切り: {change_pct*100:.1f}% (閾値-{self.stop_loss_pct*100:.0f}%)"
        if current_price > pos.peak_price:
            pos.peak_price = current_price
            self._save()
        drop_from_peak = (current_price - pos.peak_price) / pos.peak_price
        if drop_from_peak <= -self.trailing_stop_pct:
            return True, (f"トレーリングストップ: "
                          f"高値${pos.peak_price:,.2f}から{drop_from_peak*100:.1f}%"
                          f" (閾値-{self.trailing_stop_pct*100:.0f}%)")
        return False, ""

    # ── スキャルピング専用出口（SHORT用） ───────────────────
    def check_scalp_exits(self, ticker: str, current_price: float,
                          take_profit_pct: float = 0.08,
                          stop_loss_pct: float = 0.05,
                          trailing_pct: float = 0.03,
                          tight_trigger: float = 0.05,
                          tight_pct: float = 0.02) -> tuple[bool, str]:
        """
        スキャルピング出口ルール。
        +tight_trigger% 到達後はトレーリングを tight_pct% に引き締め。
        """
        pos = self.positions.get(ticker)
        if not pos:
            return False, ""
        change_pct = (current_price - pos.buy_price) / pos.buy_price
        if change_pct >= take_profit_pct:
            return True, f"スキャル利確: +{change_pct*100:.1f}%"
        if change_pct <= -stop_loss_pct:
            return True, f"スキャル損切り: {change_pct*100:.1f}%"
        if current_price > pos.peak_price:
            pos.peak_price = current_price
            self._save()
        peak_profit = (pos.peak_price - pos.buy_price) / pos.buy_price
        active_trailing = tight_pct if peak_profit >= tight_trigger else trailing_pct
        drop_from_peak = (current_price - pos.peak_price) / pos.peak_price
        if drop_from_peak <= -active_trailing:
            return True, (f"スキャルトレーリング: "
                          f"高値${pos.peak_price:,.2f}から{drop_from_peak*100:.1f}%"
                          f" (閾値-{active_trailing*100:.0f}%)")
        return False, ""

    def portfolio_value(self, prices: dict[str, float]) -> float:
        long_val = sum(pos.shares * prices.get(pos.ticker, pos.buy_price) for pos in self.positions.values())
        short_pnl = sum((pos.buy_price - prices.get(pos.ticker, pos.buy_price)) * pos.shares
                        for pos in self.short_positions.values())
        return self.balance + long_val + short_pnl

    def summary(self, prices: dict[str, float]) -> dict:
        pv = self.portfolio_value(prices)
        sells = [t for t in self.trade_history if t.action == "SELL" and not getattr(t, "is_short", False)]
        covers = [t for t in self.trade_history if t.action == "BUY" and getattr(t, "is_short", False)]
        closed = sells + covers
        wins = [t for t in closed if t.pnl > 0]
        win_rate = len(wins) / len(closed) * 100 if closed else 0.0
        total_pnl = sum(t.pnl for t in closed)
        positions_info = []
        for ticker, pos in self.positions.items():
            current = prices.get(ticker, pos.buy_price)
            unrealized = (current - pos.buy_price) / pos.buy_price * 100
            positions_info.append(
                f"{ticker}: {pos.shares:.4f}株 @ ${pos.buy_price:,.2f} "
                f"-> ${current:,.2f} ({'+' if unrealized >= 0 else ''}{unrealized:.1f}%)"
            )
        for ticker, pos in self.short_positions.items():
            current = prices.get(ticker, pos.buy_price)
            unrealized = (pos.buy_price - current) / pos.buy_price * 100  # 逆方向
            positions_info.append(
                f"{ticker}[空売り]: {pos.shares:.4f}株 @ ${pos.buy_price:,.2f} "
                f"-> ${current:,.2f} ({'+' if unrealized >= 0 else ''}{unrealized:.1f}%)"
            )
        return {
            "portfolio_value":  round(pv, 2),
            "cash_balance":     round(self.balance, 2),
            "initial_balance":  self.initial_balance,
            "total_return_pct": round((pv / self.initial_balance - 1) * 100, 2),
            "realized_pnl":     round(total_pnl, 2),
            "win_rate":         round(win_rate, 1),
            "total_trades":     len(closed),
            "open_positions":   len(self.positions),
            "short_positions":  len(self.short_positions),
            "positions":        positions_info,
        }
