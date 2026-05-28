"""
models/predictor.py
ML model to predict next-day price direction (up/down) for NSE stocks.

Features: technical indicators + lagged returns
Model:    XGBoost classifier → predicted probability of next-day gain
Eval:     Walk-forward (expanding window) cross-validation
"""

import numpy as np
import pandas as pd
from typing import List
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import (accuracy_score, precision_score,
                             recall_score, roc_auc_score, classification_report)
from sklearn.preprocessing import StandardScaler
import xgboost as xgb

from data.fetcher import fetch_single
from utils.indicators import add_all_indicators

FEATURE_COLS = [
    "RSI", "MACD", "MACD_Signal", "MACD_Hist",
    "BB_Pct", "BB_Width",
    "SMA_5", "SMA_20", "SMA_50",
    "ATR_Pct", "Volume_Ratio",
    "Return_1d", "Return_5d", "Return_20d",
    "Volatility_20d",
]

# Lag versions of return columns
LAG_COLS = ["Return_1d", "RSI", "MACD_Hist", "Volume_Ratio"]
LAGS = [1, 2, 3, 5]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build feature matrix from OHLCV + indicator DataFrame."""
    df = add_all_indicators(df.copy())

    # Add lag features
    for col in LAG_COLS:
        if col in df.columns:
            for lag in LAGS:
                df[f"{col}_lag{lag}"] = df[col].shift(lag)

    # Target: 1 if next-day close > today's close
    df["Target"] = (df["Close"].shift(-1) > df["Close"]).astype(int)

    feature_cols = [c for c in df.columns if c in FEATURE_COLS or
                    any(c.startswith(f"{lc}_lag") for lc in LAG_COLS)]
    df = df[feature_cols + ["Target"]].dropna()
    return df


def train_and_evaluate(tickers: List[str], period: str = "3y"):
    """Train and evaluate XGBoost model for each ticker using walk-forward CV."""
    for ticker in tickers:
        print(f"\n{'─'*60}")
        print(f"  ML Model — {ticker}")
        print(f"{'─'*60}")

        df = fetch_single(ticker, period=period)
        feat_df = build_features(df)

        X = feat_df.drop(columns=["Target"])
        y = feat_df["Target"]

        print(f"  Dataset: {len(X)} samples | {X.shape[1]} features | "
              f"Class balance: {y.mean():.2%} positive")

        tscv = TimeSeriesSplit(n_splits=5)
        scaler = StandardScaler()

        all_preds, all_probs, all_true = [], [], []

        for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

            X_train_s = scaler.fit_transform(X_train)
            X_test_s  = scaler.transform(X_test)

            model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                use_label_encoder=False,
                eval_metric="logloss",
                random_state=42,
                verbosity=0,
            )
            model.fit(X_train_s, y_train,
                      eval_set=[(X_test_s, y_test)],
                      verbose=False)

            preds = model.predict(X_test_s)
            probs = model.predict_proba(X_test_s)[:, 1]
            all_preds.extend(preds)
            all_probs.extend(probs)
            all_true.extend(y_test)

            fold_acc = accuracy_score(y_test, preds)
            print(f"    Fold {fold+1}: Accuracy={fold_acc:.3f}")

        # ── Overall metrics ───────────────────────────────────────────────────
        print(f"\n  {'─'*40}")
        print(f"  Overall Performance (Walk-Forward CV)")
        print(f"  Accuracy:  {accuracy_score(all_true, all_preds):.3f}")
        print(f"  Precision: {precision_score(all_true, all_preds):.3f}")
        print(f"  Recall:    {recall_score(all_true, all_preds):.3f}")
        print(f"  ROC-AUC:   {roc_auc_score(all_true, all_probs):.3f}")
        print(f"\n  Classification Report:")
        print(classification_report(all_true, all_preds,
                                    target_names=["Down", "Up"]))

        # ── Feature importance ────────────────────────────────────────────────
        fi = pd.Series(model.feature_importances_, index=X.columns)
        top_features = fi.sort_values(ascending=False).head(10)
        print("  Top 10 Features:")
        for feat, imp in top_features.items():
            bar = "█" * int(imp * 200)
            print(f"    {feat:<25} {imp:.4f}  {bar}")
