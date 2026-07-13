# VAD 语音边界检测（步骤 2A）

用于**录音访谈类**数据（纯文本标注，无时间戳）。核心工具：Silero VAD。

## 核心原则

1. **VAD 不是必须裁剪**：短音频、命令词应保留前后静音 padding
2. **必须记录 VAD 参数**：原始起止时间、padding 量
3. **短音频保护**：时长 <3s 时用保守参数（低阈值、大 padding）

## 代码模板

### 音频加载（ffmpeg pipe 解码，全格式兼容）

```python
import os, subprocess, threading, numpy as np, torch
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

def load_audio_pipe(audio_path: str, max_duration_sec: float = None
                    ) -> tuple[np.ndarray, int]:
    """用 ffmpeg pipe 解码任意音频为 16kHz mono float32"""
    cmd = ["ffmpeg", "-y"]
    if max_duration_sec is not None:
        cmd += ["-t", str(max_duration_sec)]
    cmd += ["-i", str(audio_path), "-ar", "16000", "-ac", "1",
            "-sample_fmt", "s16", "-f", "s16le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate(timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 解码失败: {stderr.decode('utf-8', errors='replace')[:200]}")
    audio_np = np.frombuffer(stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return audio_np, 16000
```

### VAD 模型管理（thread-local，多线程安全）

```python
_thread_local = threading.local()

def get_vad_model():
    if not hasattr(_thread_local, "model"):
        from silero_vad import load_silero_vad
        _thread_local.device = torch.device("cpu")
        _thread_local.model = load_silero_vad().to(_thread_local.device)
    return _thread_local.model, _thread_local.device
```

### VAD 边界检测（带 padding 控制）

```python
from silero_vad import get_speech_timestamps

def detect_speech_boundaries(audio_path, threshold=0.5,
                             min_speech_duration_ms=300,
                             pre_pad_ms=100, post_pad_ms=100,
                             is_short_utterance=False,
                             max_duration_sec=None):
    model, device = get_vad_model()

    if is_short_utterance:
        threshold = max(threshold * 0.7, 0.2)
        pre_pad_ms = max(pre_pad_ms, 200)
        post_pad_ms = max(post_pad_ms, 200)

    audio_np, sr = load_audio_pipe(audio_path, max_duration_sec)
    waveform = torch.from_numpy(audio_np).unsqueeze(0)

    speech_ts = get_speech_timestamps(
        waveform[0], model,
        threshold=threshold,
        min_speech_duration_ms=min_speech_duration_ms,
        min_silence_duration_ms=500,
        window_size_samples=1536,
    )

    results = []
    total_samples = waveform.shape[1]
    for ts in speech_ts:
        start_sample = max(0, ts['start'] - int(sr * pre_pad_ms / 1000))
        end_sample = min(total_samples, ts['end'] + int(sr * post_pad_ms / 1000))
        results.append({
            'speech_start': ts['start'] / sr,
            'speech_end': ts['end'] / sr,
            'start_sample': start_sample,
            'end_sample': end_sample,
            'pre_pad_ms': pre_pad_ms,
            'post_pad_ms': post_pad_ms,
        })
    return results
```

## 可控裁剪策略

| 任务类型 | 裁剪策略 | 前置 padding | 后置 padding |
|----------|----------|-------------|-------------|
| `general_asr` 对话/长句 | 标准裁剪 | 50~100ms | 50~100ms |
| `general_asr` 短句(<3s) | 保守裁剪 | 100~200ms | 100~200ms |
| `command_asr` 命令词 | 最小裁剪 | 200~300ms | 200~300ms |
| `keyword_spotting` | 不裁剪 | 保留原始 | 保留原始 |

## 关键参数

- Silero VAD 阈值：长句/安静环境用 0.5，短句/嘈杂用 0.3
- 最小语音段长度：300ms
- 命令词等极短语音：阈值降至 0.2~0.3

## 多线程并行处理

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def process_one(file):
    boundaries = detect_speech_boundaries(file, max_duration_sec=30)
    return file, boundaries

with ThreadPoolExecutor(max_workers=4) as ex:
    futures = {ex.submit(process_one, f): f for f in file_list}
    for fut in as_completed(futures):
        fname, bounds = fut.result()
        print(f"{fname}: {len(bounds)} 个语音段")
```
