"""Download and validate local speech-recognition models during installation."""

import onnx_asr


print("Downloading Silero VAD...")
onnx_asr.load_vad("silero")
print("Downloading fast GigaAM v3 E2E CTC INT8...")
onnx_asr.load_model("gigaam-v3-e2e-ctc", quantization="int8")
print("Downloading accurate GigaAM v3 E2E RNN-T INT8...")
onnx_asr.load_model("gigaam-v3-e2e-rnnt", quantization="int8")
print("Models are ready.")
