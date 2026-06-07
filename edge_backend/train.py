import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
import os

# 從我們剛寫好的模組匯入工具
from core.model import ReactorLSTM
from data_pipeline.loader import load_all_data
from data_pipeline.preprocessor import fit_and_save_scalers, create_sequences

os.makedirs("core/weights", exist_ok=True)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"目前使用的運算設備: {device}")

if __name__ == "__main__":
    print("1. 正在載入感測器資料...")
    df = load_all_data("data/*.csv")
    
    features = ['ORP (mV)', '酸鹼值 (pH)', '溫度 (°C)']
    target_cols = ['反應器壓力 (kg/cm²)', 'CH4濃度 (%)']

    print("2. 正在計算並儲存資料比例尺 (Scalers)...")
    data_x, data_y = fit_and_save_scalers(df, features, target_cols)

    print("3. 正在切割時間序列 (過去 30 筆預測未來第 5 筆)...")
    X, y = create_sequences(data_x, data_y, seq_length=30, predict_ahead=5)

    X_tensor = torch.tensor(X, dtype=torch.float32).to(device)
    y_tensor = torch.tensor(y, dtype=torch.float32).to(device)
    
    dataset = TensorDataset(X_tensor, y_tensor)
    dataloader = DataLoader(dataset, batch_size=128, shuffle=True)

    model = ReactorLSTM(input_size=len(features), output_size=len(target_cols)).to(device)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    print(f"4. 開始在 Jetson GPU 上進行批次訓練 (共 {len(dataloader)} 個批次/輪)！")
    epochs = 50 
    
    for epoch in range(epochs):
        model.train()
        total_loss = 0
        for batch_x, batch_y in dataloader:
            optimizer.zero_grad()
            predictions = model(batch_x)
            loss = criterion(predictions, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            
        avg_loss = total_loss / len(dataloader)
        if (epoch+1) % 10 == 0 or epoch == 0:
            print(f"第 {epoch+1:2d}/50 輪訓練 | 平均誤差 (Loss): {avg_loss:.4f}")

    save_path = "core/weights/reactor_lstm_weights.pth"
    torch.save(model.state_dict(), save_path)
    print("訓練完成！模型權重與比例尺皆已成功儲存至 core/weights/ 目錄下。")