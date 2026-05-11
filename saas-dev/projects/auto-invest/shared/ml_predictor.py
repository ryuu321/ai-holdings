"""
MLベース取引シグナル予測
XGBoost (fallback: GradientBoosting) をオンライン学習

【仕組み】
  - trades.db の過去取引からシグナル×結果を学習
  - 入力: RSI/MACD/ADX/VolMom/FR/OI/F&G/News... のスコア
  - 出力: 次の取引が利益になる確率 (0.0〜1.0)
  - 最低10件の確定取引があれば予測開始

【研究実績】
  - LLM+RL組み合わせ: RL単独比でSharpe向上
  - GBM系: シグナルの非線形結合を自動発見
"""
from __future__ import annotations
import json
import sqlite3
import numpy as np
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "data" / "trades.db"
MODEL_PATH = Path(__file__).parent.parent / "data" / "ml_model.pkl"

# 学習に使う特徴量の優先順位付き定義
FEATURE_MAP = {
    # シグナル名: (特徴量名, デフォルト値)
    "RSI":              "rsi_score",
    "MACD":             "macd_score",
    "MACDHist":         "macd_hist_score",
    "BB":               "bb_score",
    "FearGreed":        "fg_score",
    "News":             "news_score",
    "LLMSentiment":     "llm_score",
    "ADX":              "adx_score",
    "MTF":              "mtf_score",
    "VolMom":           "vol_mom_score",
    "FundingRate":      "fr_score",
    "LSRatio":          "ls_score",
    "GoldenCross":      "gc_score",
    "DeathCross":       "dc_score",
    "AboveMA200":       "ma200_score",
    "AboveMA50":        "ma50_score",
    "StatArb":          "stat_arb_score",
    "VIX":              "vix_score",
    "Rates":            "rates_score",
    "DXY":              "dxy_score",
    "M2":               "m2_score",
    "RSI_MACD_Confirm": "confirm_score",
    "SPY":              "spy_score",
    "Overall":          "overall_score",
}

ALL_FEATURES = list(FEATURE_MAP.values())
MIN_SAMPLES  = 10   # 学習開始に必要な最低取引件数


def _extract_features(signals_json) -> np.ndarray:
    """signals_json → 特徴量ベクトル (len=ALL_FEATURES)"""
    vec = {k: 0.0 for k in ALL_FEATURES}
    if not signals_json:
        return np.array([vec[k] for k in ALL_FEATURES], dtype=float)
    try:
        if isinstance(signals_json, str):
            signals = json.loads(signals_json)
        else:
            signals = signals_json or []
        for sig in signals:
            name = sig.get("name", "")
            if name in FEATURE_MAP:
                vec[FEATURE_MAP[name]] = float(sig.get("score", 0))
    except Exception:
        pass
    return np.array([vec[k] for k in ALL_FEATURES], dtype=float)


def _load_training_data(bot_type: str) -> tuple[np.ndarray, np.ndarray]:
    """trades.db から学習データを構築"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("""
            SELECT signals_json, pnl FROM trades
            WHERE bot_type = ? AND action IN ('SELL','BUY') AND pnl IS NOT NULL
            ORDER BY timestamp ASC
        """, (bot_type,))
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return np.array([]), np.array([])

    if len(rows) < MIN_SAMPLES:
        return np.array([]), np.array([])

    X, y = [], []
    for sig_json, pnl in rows:
        X.append(_extract_features(sig_json))
        y.append(1 if pnl > 0 else 0)
    return np.array(X), np.array(y)


class MLPredictor:
    """
    過去取引から学習し、次の取引の勝率を予測するモデル。
    XGBoostが使えない場合はGradientBoostingにフォールバック。
    """

    def __init__(self, bot_type: str = "SHORT"):
        self.bot_type = bot_type
        self.model    = None
        self._trained = False
        self._n_samples = 0
        self._load_or_train()

    def _build_model(self):
        try:
            from xgboost import XGBClassifier
            return XGBClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                eval_metric="logloss",
                random_state=42,
                verbosity=0,
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            return GradientBoostingClassifier(
                n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42)

    def _load_or_train(self):
        """モデルファイルがあればロード、なければ学習"""
        import pickle
        model_file = MODEL_PATH.parent / f"ml_model_{self.bot_type.lower()}.pkl"
        X, y = _load_training_data(self.bot_type)
        if len(X) < MIN_SAMPLES:
            return  # データ不足

        # 常に最新データで再学習（過去全件使用）
        try:
            from sklearn.model_selection import cross_val_score
            model = self._build_model()
            model.fit(X, y)

            # クロスバリデーションで精度確認
            if len(X) >= 20:
                cv_scores = cross_val_score(model, X, y, cv=min(5, len(X)//4), scoring="accuracy")
                self._cv_accuracy = float(cv_scores.mean())
            else:
                self._cv_accuracy = None

            self.model      = model
            self._trained   = True
            self._n_samples = len(X)

            # モデル保存
            with open(model_file, "wb") as f:
                pickle.dump(model, f)

        except Exception as e:
            print(f"[MLPredictor] 学習エラー: {e}")

    def predict_proba(self, current_signals: list[dict]) -> tuple[float, str]:
        """
        現在のシグナルリストから勝率を予測
        Returns: (probability 0-1, label)
        """
        if not self._trained or self.model is None:
            return 0.5, f"学習データ不足({self._n_samples}/{MIN_SAMPLES}件)"

        X = _extract_features(current_signals).reshape(1, -1)
        try:
            proba = float(self.model.predict_proba(X)[0][1])
            if proba >= 0.70:
                label = f"ML勝率={proba:.0%} 高確信(n={self._n_samples})"
            elif proba >= 0.55:
                label = f"ML勝率={proba:.0%} やや強気(n={self._n_samples})"
            elif proba <= 0.30:
                label = f"ML勝率={proba:.0%} 警告(n={self._n_samples})"
            else:
                label = f"ML勝率={proba:.0%} 中立(n={self._n_samples})"
            return proba, label
        except Exception as e:
            return 0.5, f"予測エラー: {e}"

    def signal_score(self, current_signals: list[dict]) -> tuple[int, str]:
        """
        予測確率をスコア(-2〜+2)に変換
        +2: 非常に強気 / +1: 強気 / 0: 中立 / -1: 弱気 / -2: 強い警告
        """
        proba, label = self.predict_proba(current_signals)
        if proba >= 0.72:   return +2, label
        elif proba >= 0.60: return +1, label
        elif proba <= 0.28: return -2, label
        elif proba <= 0.40: return -1, label
        else:               return  0, label

    def feature_importance(self) -> dict:
        """どのシグナルが予測に効いているか"""
        if not self._trained or self.model is None:
            return {}
        try:
            imp = self.model.feature_importances_
            return dict(sorted(
                zip(ALL_FEATURES, imp), key=lambda x: -x[1])[:10])
        except Exception:
            return {}


# シングルトンキャッシュ (起動コストを省く)
_cache: dict[str, MLPredictor] = {}

def get_predictor(bot_type: str) -> MLPredictor:
    if bot_type not in _cache:
        _cache[bot_type] = MLPredictor(bot_type)
    return _cache[bot_type]


def refresh_predictor(bot_type: str) -> MLPredictor:
    """取引後に呼び出して再学習"""
    _cache[bot_type] = MLPredictor(bot_type)
    return _cache[bot_type]
