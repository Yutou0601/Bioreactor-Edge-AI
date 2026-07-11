"""
PyTorch (ReactorLSTM) -> ONNX 匯出工具
========================================
把 core/model.py 的 ReactorLSTM 匯出成 .onnx，供 x86 監控電腦與 Jetson Orin
Nano 兩端用同一份中介表示格式跑推論（ONNX Runtime 具硬體不可知性）。

用法：
  python export_onnx.py                      # 用 core/weights/ 下的已訓練權重
  python export_onnx.py --random-weights      # 沒有已訓練權重時，用隨機權重測試
                                                # 匯出流程本身是否可行（僅供工程驗證，
                                                # 不代表模型已可用於實際預測）
"""
import argparse
import os

import numpy as np
import torch

from core.model import ReactorLSTM
from core.inference import INPUT_SIZE, SEQ_LEN

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_WEIGHTS_DIR = os.path.join(_BASE_DIR, "core", "weights")
_DEFAULT_OUT = os.path.join(_WEIGHTS_DIR, "reactor_lstm.onnx")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="匯出 ReactorLSTM 為 ONNX")
    parser.add_argument("--random-weights", action="store_true",
                         help="沒有已訓練權重時，用隨機初始化權重測試匯出流程是否可行")
    parser.add_argument("--out", default=_DEFAULT_OUT, help="輸出 .onnx 路徑")
    parser.add_argument("--opset", type=int, default=17, help="ONNX opset 版本")
    return parser


def load_model(use_random_weights: bool) -> ReactorLSTM:
    model = ReactorLSTM(input_size=INPUT_SIZE, output_size=2)
    weights_path = os.path.join(_WEIGHTS_DIR, "reactor_lstm_weights.pth")

    if use_random_weights:
        print("[export_onnx] 使用隨機初始化權重（--random-weights），僅測試匯出流程")
    elif os.path.exists(weights_path):
        model.load_state_dict(torch.load(weights_path, map_location="cpu"))
        print(f"[export_onnx] 已載入已訓練權重 → {weights_path}")
    else:
        raise FileNotFoundError(
            f"找不到已訓練權重 {weights_path}。\n"
            f"若只是要先驗證匯出流程是否可行（尚未訓練模型），"
            f"請加上 --random-weights 旗標。"
        )

    model.eval()
    return model


def export_and_verify(model: ReactorLSTM, out_path: str, opset: int) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    dummy_input = torch.randn(1, SEQ_LEN, INPUT_SIZE, dtype=torch.float32)

    with torch.no_grad():
        torch_output = model(dummy_input).numpy()

    torch.onnx.export(
        model,
        (dummy_input,),
        out_path,
        input_names=["sensor_window"],
        output_names=["prediction"],
        dynamic_axes={"sensor_window": {0: "batch"}, "prediction": {0: "batch"}},
        opset_version=opset,
    )
    print(f"[export_onnx] 已匯出 → {out_path}")

    import onnx
    import onnxruntime as ort

    onnx_model = onnx.load(out_path)
    onnx.checker.check_model(onnx_model)
    print("[export_onnx] onnx.checker 結構檢查通過")

    session = ort.InferenceSession(out_path, providers=["CPUExecutionProvider"])
    ort_output = session.run(None, {"sensor_window": dummy_input.numpy()})[0]

    max_abs_diff = np.max(np.abs(torch_output - ort_output))
    print(f"[export_onnx] PyTorch vs ONNX Runtime 最大絕對誤差: {max_abs_diff:.3e}")

    # 再測一次不同 batch size，確認 dynamic_axes 設定確實可用（未來一次可能會
    # 想批次跑歷史資料，而不是每次只推論一筆）
    dummy_batch = torch.randn(4, SEQ_LEN, INPUT_SIZE, dtype=torch.float32)
    with torch.no_grad():
        torch_batch_output = model(dummy_batch).numpy()
    ort_batch_output = session.run(None, {"sensor_window": dummy_batch.numpy()})[0]
    batch_max_abs_diff = np.max(np.abs(torch_batch_output - ort_batch_output))
    print(f"[export_onnx] 動態 batch size=4 驗證: 最大絕對誤差 {batch_max_abs_diff:.3e}")

    ok = max_abs_diff < 1e-4 and batch_max_abs_diff < 1e-4
    print(f"[export_onnx] 驗證結果: {'✓ 通過' if ok else '✗ 誤差超出預期，需要進一步檢查'}")


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    os.chdir(_BASE_DIR)
    m = load_model(args.random_weights)
    export_and_verify(m, args.out, args.opset)
