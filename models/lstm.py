"""
models/lstm.py — Phase 3b
LSTM (Long Short-Term Memory) price direction predictor for NSE equities.

Architecture:
    Input  : sliding window of SEQ_LEN trading days × N features
    Model  : 2-layer LSTM (hidden=64) + dropout + linear head
    Output : probability of next-day close > today's close
    Loss   : BCEWithLogitsLoss  (binary cross-entropy)
    Optim  : Adam  (lr=1e-3)

Validation: Walk-forward (TimeSeriesSplit, 5 folds) — no data leakage.

Requires: torch  (pip install torch --index-url https://download.pytorch.org/whl/cpu)
"""

import numpy as np
import pandas as pd
from typing import List
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (accuracy_score, precision_score,
                             recall_score, roc_auc_score, classification_report)

from data.fetcher import fetch_single
from utils.indicators import add_all_indicators

# ── Feature set (same as XGBoost predictor for easy comparison) ───────────────
FEATURE_COLS = [
    "RSI", "MACD", "MACD_Signal", "MACD_Hist",
    "BB_Pct", "BB_Width",
    "SMA_5", "SMA_20", "SMA_50",
    "ATR_Pct", "Volume_Ratio",
    "Return_1d", "Return_5d", "Return_20d", "Volatility_20d",
]
LAG_COLS = ["Return_1d", "RSI", "MACD_Hist", "Volume_Ratio"]
LAGS     = [1, 2, 3, 5]
SEQ_LEN  = 30   # 30-day lookback window per sample


# ── Torch import (with friendly error) ───────────────────────────────────────
try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


# ── Model definition ──────────────────────────────────────────────────────────
# FIX ML1 — LSTMClassifier's base class (nn.Module) and _evaluate's
# @torch.no_grad() decorator are both evaluated at MODULE IMPORT time, not
# when train_and_evaluate_lstm() runs. That meant the "friendly PyTorch not
# installed" fallback below was unreachable in practice: without torch,
# `import models.lstm` itself raised a bare `NameError: name 'nn' is not
# defined` before TORCH_AVAILABLE was ever checked, and the try/except
# import guard above was doing nothing useful. Gating the whole
# torch-dependent block behind `if TORCH_AVAILABLE:` lets the module import
# cleanly either way, so train_and_evaluate_lstm()'s existing fallback to
# the XGBoost predictor actually gets a chance to run.
if TORCH_AVAILABLE:

    class LSTMClassifier(nn.Module):
        """2-layer LSTM for binary next-day direction classification."""

        def __init__(self, input_size: int, hidden_size: int = 64, num_layers: int = 2,
                     dropout: float = 0.3):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size  = input_size,
                hidden_size = hidden_size,
                num_layers  = num_layers,
                dropout     = dropout if num_layers > 1 else 0.0,
                batch_first = True,
            )
            self.dropout = nn.Dropout(dropout)
            self.head    = nn.Linear(hidden_size, 1)   # logit output

        def forward(self, x):                          # x: (batch, seq_len, features)
            out, _ = self.lstm(x)
            out     = self.dropout(out[:, -1, :])      # last timestep
            return self.head(out).squeeze(1)           # (batch,) logits


# ── Feature engineering ───────────────────────────────────────────────────────
def _build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Build flat feature matrix with lag columns and target."""
    df = add_all_indicators(df.copy())
    for col in LAG_COLS:
        if col in df.columns:
            for lag in LAGS:
                df[f"{col}_lag{lag}"] = df[col].shift(lag)
    df["Target"] = (df["Close"].shift(-1) > df["Close"]).astype(int)
    keep = [c for c in df.columns
            if c in FEATURE_COLS or any(c.startswith(f"{lc}_lag") for lc in LAG_COLS)]
    return df[keep + ["Target"]].dropna()


def _make_sequences(X: np.ndarray, y: np.ndarray, seq_len: int):
    """Convert flat feature matrix into (samples, seq_len, features) tensors."""
    Xs, ys = [], []
    for i in range(seq_len, len(X)):
        Xs.append(X[i - seq_len: i])
        ys.append(y[i])
    return np.array(Xs, dtype=np.float32), np.array(ys, dtype=np.float32)


if TORCH_AVAILABLE:

    # ── Training loop ─────────────────────────────────────────────────────────
    def _train_epoch(model, loader, criterion, optimizer, device):
        model.train()
        total_loss = 0.0
        for Xb, yb in loader:
            Xb, yb = Xb.to(device), yb.to(device)
            optimizer.zero_grad()
            logits = model(Xb)
            loss   = criterion(logits, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += loss.item() * len(yb)
        return total_loss / len(loader.dataset)


    @torch.no_grad()
    def _evaluate(model, loader, device):
        model.eval()
        all_logits, all_labels = [], []
        for Xb, yb in loader:
            all_logits.append(model(Xb.to(device)).cpu())
            all_labels.append(yb)
        logits = torch.cat(all_logits)
        labels = torch.cat(all_labels)
        probs  = torch.sigmoid(logits).numpy()
        preds  = (probs >= 0.5).astype(int)
        return preds, probs, labels.numpy().astype(int)


    @torch.no_grad()
    def _eval_loss(model, loader, criterion, device):
        """Average criterion loss over a loader, with no gradient tracking.

        FIX ML2 companion — a genuine validation-loss computation, used in
        place of the train_loss proxy that used to stand in for it (see
        FIX ML2 below).
        """
        model.eval()
        total_loss, n = 0.0, 0
        for Xb, yb in loader:
            Xb, yb = Xb.to(device), yb.to(device)
            logits = model(Xb)
            loss   = criterion(logits, yb)
            total_loss += loss.item() * len(yb)
            n += len(yb)
        return total_loss / n if n else float("nan")


# ── Public entry point ────────────────────────────────────────────────────────
def train_and_evaluate_lstm(
    tickers: List[str],
    period: str = "3y",
    seq_len: int = SEQ_LEN,
    hidden_size: int = 64,
    num_layers: int = 2,
    n_epochs: int = 30,
    batch_size: int = 32,
    lr: float = 1e-3,
):
    """
    Train and evaluate LSTM price-direction classifier for each ticker.

    Uses walk-forward cross-validation (TimeSeriesSplit) to avoid look-ahead bias.
    Prints per-fold accuracy and overall metrics, plus a feature-count summary.
    """
    if not TORCH_AVAILABLE:
        print(
            "\n  [LSTM] PyTorch not installed.\n"
            "  Install with:  pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
            "  Falling back to XGBoost predictor...\n"
        )
        from models.predictor import train_and_evaluate
        train_and_evaluate(tickers=tickers, period=period)
        return

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n  Using device: {device}")

    for ticker in tickers:
        print(f"\n{'─'*60}")
        print(f"  LSTM Model  —  {ticker}")
        print(f"{'─'*60}")

        # ── Build features ─────────────────────────────────────────────────────
        raw_df   = fetch_single(ticker, period=period)
        feat_df  = _build_feature_matrix(raw_df)

        feat_cols = [c for c in feat_df.columns if c != "Target"]
        X_flat    = feat_df[feat_cols].values
        y_flat    = feat_df["Target"].values

        print(
            f"  Dataset : {len(feat_df)} rows | {len(feat_cols)} features | "
            f"seq_len={seq_len} | positive={y_flat.mean():.1%}"
        )

        tscv = TimeSeriesSplit(n_splits=5)
        all_preds, all_probs, all_true = [], [], []

        for fold, (tr_idx, te_idx) in enumerate(tscv.split(X_flat)):
            # ── Scale on train, apply to test ──────────────────────────────────
            scaler    = StandardScaler()
            X_tr_s    = scaler.fit_transform(X_flat[tr_idx]).astype(np.float32)
            X_te_s    = scaler.transform(X_flat[te_idx]).astype(np.float32)

            X_tr, y_tr = _make_sequences(X_tr_s, y_flat[tr_idx], seq_len)
            X_te, y_te = _make_sequences(X_te_s, y_flat[te_idx], seq_len)

            if len(X_tr) < batch_size or len(X_te) == 0:
                continue

            tr_loader = DataLoader(TensorDataset(
                torch.from_numpy(X_tr), torch.from_numpy(y_tr)
            ), batch_size=batch_size, shuffle=False)

            te_loader = DataLoader(TensorDataset(
                torch.from_numpy(X_te), torch.from_numpy(y_te)
            ), batch_size=batch_size)

            # ── Model, loss, optimiser ─────────────────────────────────────────
            model     = LSTMClassifier(len(feat_cols), hidden_size, num_layers).to(device)
            criterion = nn.BCEWithLogitsLoss()
            optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
            scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
                optimizer, patience=5, factor=0.5
            )

            best_val_loss = float("inf")
            best_state    = None

            for epoch in range(n_epochs):
                train_loss = _train_epoch(model, tr_loader, criterion, optimizer, device)
                # FIX ML2 — this used to be `val_loss = train_loss` ("use train
                # as proxy for tiny folds"), which meant both the LR scheduler
                # and the best-checkpoint selection below were really just
                # tracking training loss trending down — which it almost
                # always does with Adam and no early-stopping signal, so this
                # silently picked the LAST epoch's weights nearly every time
                # regardless of whether the model had started overfitting on
                # the held-out fold. te_loader already exists for exactly this
                # purpose; computing the real validation loss on it costs one
                # more no-grad forward pass and makes both the scheduler step
                # and the checkpoint choice mean what they claim to.
                val_loss = _eval_loss(model, te_loader, criterion, device)
                scheduler.step(val_loss)
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_state    = {k: v.clone() for k, v in model.state_dict().items()}

            # ── Evaluate best model on this fold ──────────────────────────────
            if best_state:
                model.load_state_dict(best_state)
            preds, probs, y_true = _evaluate(model, te_loader, device)

            fold_acc = accuracy_score(y_true, preds)
            print(f"    Fold {fold + 1}:  Accuracy={fold_acc:.3f}  Samples={len(y_true)}")
            all_preds.extend(preds.tolist())
            all_probs.extend(probs.tolist())
            all_true.extend(y_true.tolist())

        if not all_true:
            print("  Not enough data for evaluation.")
            continue

        # ── Overall metrics ────────────────────────────────────────────────────
        print(f"\n  {'─'*40}")
        print(f"  Overall — Walk-Forward CV  (LSTM)")
        print(f"  Accuracy   : {accuracy_score(all_true, all_preds):.3f}")
        print(f"  Precision  : {precision_score(all_true, all_preds, zero_division=0):.3f}")
        print(f"  Recall     : {recall_score(all_true, all_preds, zero_division=0):.3f}")
        print(f"  ROC-AUC    : {roc_auc_score(all_true, all_probs):.3f}")
        print(f"\n  Classification Report:")
        print(classification_report(all_true, all_preds,
                                    target_names=["Down", "Up"],
                                    zero_division=0))

        # ── XGBoost comparison ─────────────────────────────────────────────────
        print("  (Run  --mode ml  to compare with XGBoost baseline)\n")
