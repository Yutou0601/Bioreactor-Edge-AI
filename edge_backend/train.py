import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
import os
import numpy as np

from core.model import ReactorLSTM
from data_pipeline.loader import load_all_data
from data_pipeline.preprocessor import fit_and_save_scalers, create_sequences, engineer_features

os.makedirs("core/weights", exist_ok=True)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"目前使用的運算設備: {device}")

# ── 切割比例 ──────────────────────────────────────────────
TRAIN_RATIO = 0.70
VAL_RATIO   = 0.15
# TEST_RATIO = 1 - TRAIN_RATIO - VAL_RATIO = 0.15

EPOCHS        = 80
BATCH_SIZE    = 128
LR            = 0.001
EARLY_STOP_PATIENCE = 10   # val_loss 連續 N 輪未改善則停止


def split_sequences(X, y, train_r, val_r):
    """時間序列只能按時間順序切，不能 random shuffle（否則資料洩漏）"""
    n = len(X)
    t1 = int(n * train_r)
    t2 = int(n * (train_r + val_r))
    return (X[:t1],  y[:t1],
            X[t1:t2], y[t1:t2],
            X[t2:],   y[t2:])


def eval_loss(model, loader, criterion):
    model.eval()
    total = 0.0
    with torch.no_grad():
        for bx, by in loader:
            total += criterion(model(bx), by).item()
    return total / len(loader)


if __name__ == "__main__":
    print("1. 正在載入感測器資料...")
    df = load_all_data("data/*.csv")
    print(f"   共 {len(df):,} 筆原始資料")

    print("1.5 正在計算衍生特徵 (EMA / 斜率 / MACD)...")
    df = engineer_features(df)

    features    = ['orp_ema', 'orp_slope', 'orp_macd', '酸鹼值 (pH)', '溫度 (°C)', '反應器壓力 (kg/cm²)']
    target_cols = ['反應器壓力 (kg/cm²)', 'CH4濃度 (%)']

    print("2. 正在計算並儲存資料比例尺 (Scalers，僅用訓練集 fit)...")
    # Scaler 只能 fit 訓練集，否則測試集資訊洩漏
    n_total   = len(df)
    n_train   = int(n_total * TRAIN_RATIO)
    df_train  = df.iloc[:n_train]
    df_rest   = df.iloc[n_train:]

    from sklearn.preprocessing import MinMaxScaler
    import joblib
    scaler_x = MinMaxScaler()
    scaler_y = MinMaxScaler()
    scaler_x.fit(df_train[features].values)
    scaler_y.fit(df_train[target_cols].values)
    joblib.dump(scaler_x, 'core/weights/scaler_x.pkl')
    joblib.dump(scaler_y, 'core/weights/scaler_y.pkl')

    data_x = scaler_x.transform(df[features].values)
    data_y = scaler_y.transform(df[target_cols].values)

    print("3. 正在切割時間序列 (過去 30 筆預測未來第 5 筆)...")
    X, y = create_sequences(data_x, data_y, seq_length=30, predict_ahead=5)
    print(f"   序列總數: {len(X):,}")

    X_tr, y_tr, X_val, y_val, X_te, y_te = split_sequences(X, y, TRAIN_RATIO, VAL_RATIO)
    print(f"   Train: {len(X_tr):,}  |  Val: {len(X_val):,}  |  Test: {len(X_te):,}  "
          f"({TRAIN_RATIO:.0%} / {VAL_RATIO:.0%} / {1-TRAIN_RATIO-VAL_RATIO:.0%})")

    def to_loader(Xa, ya, shuffle):
        ds = TensorDataset(
            torch.tensor(Xa, dtype=torch.float32).to(device),
            torch.tensor(ya, dtype=torch.float32).to(device),
        )
        return DataLoader(ds, batch_size=BATCH_SIZE, shuffle=shuffle)

    train_loader = to_loader(X_tr, y_tr, shuffle=True)
    val_loader   = to_loader(X_val, y_val, shuffle=False)
    test_loader  = to_loader(X_te, y_te, shuffle=False)

    model     = ReactorLSTM(input_size=len(features), output_size=len(target_cols)).to(device)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    print(f"\n4. 開始訓練 (共 {len(train_loader)} 批次/輪，最多 {EPOCHS} 輪，Early Stop patience={EARLY_STOP_PATIENCE})")
    print(f"   {'Epoch':>5}  {'Train Loss':>10}  {'Val Loss':>10}  {'狀態':>6}")
    print(f"   {'-'*40}")

    best_val_loss   = float('inf')
    patience_count  = 0
    best_state_dict = None

    for epoch in range(EPOCHS):
        # ── 訓練 ──
        model.train()
        train_total = 0.0
        for bx, by in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(bx), by)
            loss.backward()
            optimizer.step()
            train_total += loss.item()
        train_loss = train_total / len(train_loader)

        # ── 驗證 ──
        val_loss = eval_loss(model, val_loader, criterion)

        # ── Early Stopping ──
        if val_loss < best_val_loss:
            best_val_loss  = val_loss
            best_state_dict = {k: v.clone() for k, v in model.state_dict().items()}
            patience_count = 0
            marker = '★'
        else:
            patience_count += 1
            marker = f'({patience_count}/{EARLY_STOP_PATIENCE})'

        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"   {epoch+1:>5}  {train_loss:>10.4f}  {val_loss:>10.4f}  {marker}")

        if patience_count >= EARLY_STOP_PATIENCE:
            print(f"\n   Early Stop 觸發 (第 {epoch+1} 輪，Val Loss 連續 {EARLY_STOP_PATIENCE} 輪未改善)")
            break

    # ── 還原最佳權重並評估測試集 ──
    if best_state_dict:
        model.load_state_dict(best_state_dict)

    test_loss = eval_loss(model, test_loader, criterion)

    print(f"\n{'='*46}")
    print(f"  最佳 Val  Loss : {best_val_loss:.4f}")
    print(f"  Test      Loss : {test_loss:.4f}")
    gap = abs(test_loss - best_val_loss) / best_val_loss * 100
    if gap < 20:
        print(f"  泛化差距       : {gap:.1f}%  → 模型泛化良好")
    else:
        print(f"  泛化差距       : {gap:.1f}%  → 可能 Overfit，考慮增加資料或 Dropout")
    print(f"{'='*46}")

    torch.save(model.state_dict(), "core/weights/reactor_lstm_weights.pth")
    print("模型權重與比例尺已儲存至 core/weights/")
