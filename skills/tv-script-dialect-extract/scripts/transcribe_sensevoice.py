"""步骤 2：SenseVoice（DeepSeek Harness 自带 ONNX 模型）+ Silero VAD 全片转写。

不额外下载模型：直接复用 DSH 的语音输入资产。26 分钟节目在 CPU 上约 2 分钟。

用法：
    python transcribe_sensevoice.py --audio work/full16k.wav --out work/asr.json
    python transcribe_sensevoice.py --audio x.wav --out y.json --limit 120   # 只跑前 120s 试听

产出：JSON 列表 [{start, end, text}, ...] + 同名 .txt

依赖：sherpa-onnx, numpy
  pip install sherpa-onnx    （装不上时见 SKILL.md「环境」一节的手动解压办法）
"""
import argparse
import json
import os
import time
import wave

import numpy as np
import sherpa_onnx

DEFAULT_MODEL_DIR = os.path.join(os.path.expanduser("~"), ".dsh", "speech-to-text", "sensevoice", "models")
SR = 16000


def read_wav(path):
    with wave.open(path, "rb") as f:
        assert f.getnchannels() == 1 and f.getframerate() == SR and f.getsampwidth() == 2, \
            "需要 16k/单声道/16bit wav"
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def clean(text):
    """去掉 SenseVoice 的 <|zh|><|NEUTRAL|><|Speech|><|woitn|> 等标签。"""
    out, i = [], 0
    while i < len(text):
        if text.startswith("<|", i):
            j = text.find("|>", i)
            if j != -1:
                i = j + 2
                continue
        if text[i] == "<":
            j = text.find(">", i)
            if j != -1:
                out.append(text[i:j + 1])
                i = j + 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--limit", type=float, default=0, help="只转写前 N 秒，0=全片")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()

    model = os.path.join(args.model_dir, "sensevoice-onnx", "model.int8.onnx")
    tokens = os.path.join(args.model_dir, "sensevoice-onnx", "tokens.txt")
    vad_path = os.path.join(args.model_dir, "silero", "silero_vad.onnx")
    for p in (model, tokens, vad_path):
        if not os.path.exists(p):
            raise SystemExit("模型文件缺失: %s\n请确认 DSH 语音输入已初始化，或用 --model-dir 指定" % p)

    t0 = time.time()
    samples = read_wav(args.audio)
    if args.limit:
        samples = samples[: int(args.limit * SR)]
    print("audio %.1fs" % (len(samples) / SR))

    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=model, tokens=tokens, num_threads=args.threads,
        use_itn=True, language="auto", debug=False)

    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = vad_path
    cfg.silero_vad.threshold = 0.5
    cfg.silero_vad.min_silence_duration = 0.45
    cfg.silero_vad.min_speech_duration = 0.25
    cfg.silero_vad.max_speech_duration = 20
    cfg.sample_rate = SR
    cfg.num_threads = 2
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)

    results = []

    def flush():
        while not vad.empty():
            seg = vad.front
            st = rec.create_stream()
            st.accept_waveform(SR, np.asarray(seg.samples, dtype=np.float32))
            rec.decode_stream(st)
            results.append({
                "start": round(seg.start / SR, 3),
                "end": round((seg.start + len(seg.samples)) / SR, 3),
                "text": clean(st.result.text),
            })
            vad.pop()

    win = SR // 10
    for i in range(0, len(samples), win):
        vad.accept_waveform(samples[i:i + win])
        flush()
    vad.flush()
    flush()

    json.dump(results, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    txt = args.out.replace(".json", ".txt")
    with open(txt, "w", encoding="utf-8") as f:
        for r in results:
            f.write("[%7.2f-%7.2f] %s\n" % (r["start"], r["end"], r["text"]))
    print("segments %d  elapsed %.1fs  -> %s" % (len(results), time.time() - t0, args.out))


if __name__ == "__main__":
    main()
