# SRT 字幕清洗与音频切分（步骤 2B）

针对**电视台节目**等有 SRT 字幕的视频/音频数据的专门流程。

---

## 2B.1 SRT 噪声清洗

### 常见噪声类型

| 噪声类型 | 示例 | 来源 |
|----------|------|------|
| 台标水印 | `临海 电视台`、`CHINA` | 画面固定文字 OCR |
| OCR 乱码 | `EEEE E`、`TTV`、`R1:` | 硬字幕 OCR 识别错误 |
| 画面标识 | `禁止吸烟`、`进入厂区` | 画面叠加文字 |
| 纯数字垃圾 | `11111111`、`2024` | OCR 误识别 |
| 单字符垃圾 | `N`、`W`、`工` | OCR 残留 |

### 清洗流程

按 `DROP_ENTIRE` → `HEAD_NOISE` → `TAIL_NOISE` 顺序迭代清洗。输出 `_cleaned.srt`（保留原始文件不动）。

### 清洗代码

```python
import re

DROP_ENTIRE_PATTERNS = [
    r'^[Ee\s]{3,}$',
    r'^\d{4,}\s*$',
    r'^CHINA|ITALIA|CH\s*NT$',
]

TAIL_NOISE_PATTERNS = [
    (r'\s*临海\s*电视台\s*$', ''),
    (r'\s*CHINA\s*$', ''),
    (r'\s*[NnWw]\s*$', ''),
]

HEAD_NOISE_PATTERNS = [
    (r'^[Ee]{2,}(\s*[Ee]+)*\s*', ''),
    (r'^CHINA\s*', ''),
]

def clean_text(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    for pat in DROP_ENTIRE_PATTERNS:
        if re.match(pat, stripped):
            return None
    result = text
    for _ in range(2):
        for pat, rep in HEAD_NOISE_PATTERNS:
            result = re.sub(pat, rep, result)
        for pat, rep in TAIL_NOISE_PATTERNS:
            result = re.sub(pat, rep, result)
    result = result.strip()
    return result if result else None
```

### SRT 后缀兼容

- 标准格式：`节目名_cleaned.srt`
- 变体：`节目名_cleaned.srt.txt`（第一批市局数据常见）
- **处理建议**：同时搜索两种模式

---

## 2B.2 SRT 解析与时间戳提取

```python
def parse_srt(content: str) -> list[dict]:
    entries = []
    blocks = content.strip().split('\n\n')
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
            timestamp_line = lines[1].strip()
            text = '\n'.join(lines[2:]).strip()
            parts = timestamp_line.split(' --> ')
            start_sec = timestamp_to_seconds(parts[0])
            end_sec = timestamp_to_seconds(parts[1])
            entries.append({'index': index, 'start': start_sec,
                            'end': end_sec, 'text': text})
        except (ValueError, IndexError):
            continue
    return entries

def timestamp_to_seconds(ts: str) -> float:
    ts = ts.strip().replace(',', '.')
    parts = ts.split(':')
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    else:
        return float(parts[0])
```

---

## 2B.3 按字幕时间戳切分音频

### FFmpeg 逐条切分（稳定但慢）
```bash
ffmpeg -y -i source.mp4 -ss 00:01:23.456 -to 00:01:26.789 \
  -ar 16000 -ac 1 -sample_fmt s16 output_001.wav
```

### Python 封装（含偏移量支持）
```python
import subprocess, os

def slice_audio_by_timestamp(source_audio, output_dir, srt_entries,
                             sample_rate=16000, offset=0.0):
    os.makedirs(output_dir, exist_ok=True)
    results = []
    for i, entry in enumerate(srt_entries):
        start_sec = entry['start'] + offset
        end_sec = entry['end'] + offset
        duration = end_sec - start_sec
        if duration < 0.3 or start_sec < 0:
            continue
        output_path = os.path.join(output_dir, f"segment_{i:04d}.wav")
        cmd = ["ffmpeg", "-y", "-i", source_audio, "-ss", str(start_sec),
               "-to", str(end_sec), "-ar", str(sample_rate), "-ac", "1",
               "-sample_fmt", "s16", output_path]
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            results.append({"audio": output_path, "text": entry['text'],
                            "duration": duration, "start": start_sec, "end": end_sec})
        except subprocess.CalledProcessError:
            pass
    return results
```

### 高性能批量切片（推荐）

对 300+ 节目时，**逐条 ffmpeg 极慢**（53,396 条约 45 分钟），推荐预解码+Python wave 模块（约 7 分钟）：

```python
import wave, subprocess, os
from pathlib import Path

def decode_to_temp(source_audio: str, temp_wav: str) -> bool:
    cmd = ["ffmpeg", "-y", "-i", source_audio,
           "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", temp_wav]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    return True

def batch_slice(temp_wav, slice_dir, srt_entries, audio_name,
                min_dur=0.3, max_dur=20.0):
    os.makedirs(slice_dir, exist_ok=True)
    with wave.open(temp_wav, 'rb') as wf:
        framerate = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()

    results = []
    for entry in srt_entries:
        seg_idx = entry['index']
        duration = entry['end'] - entry['start']
        if duration < min_dur or duration > max_dur:
            continue
        seg_path = os.path.join(slice_dir, f"{seg_idx:04d}.wav")
        if os.path.exists(seg_path) and os.path.getsize(seg_path) > 100:
            actual_dur = get_duration(seg_path)
            if actual_dur > 0:
                results.append({"audio": seg_path, "text": entry['text'],
                                "duration": actual_dur})
                continue
        start_frame = int(entry['start'] * framerate)
        end_frame = min(int(entry['end'] * framerate), n_frames)
        n_seg_frames = end_frame - start_frame
        if n_seg_frames <= 0:
            continue
        with wave.open(temp_wav, 'rb') as wf:
            wf.setpos(start_frame)
            frames = wf.readframes(n_seg_frames)
        with wave.open(seg_path, 'wb') as wf_out:
            wf_out.setnchannels(n_channels)
            wf_out.setsampwidth(sampwidth)
            wf_out.setframerate(framerate)
            wf_out.writeframes(frames)
        results.append({"audio": seg_path, "text": entry['text'],
                        "duration": n_seg_frames / framerate})
    return results
```

### 同名文件跨源冲突
不同数据源可能同名（如 `20070115第01期.mp3` 同时出现在多个目录）。建议按两级目录隔离：
```
预处理/种田垟2007/20070115第01期/0001.wav
预处理/种田垟第一批/20070115第01期/0001.wav
```

---

## 2B.4 音画同步校正

### 不同步类型

| 类型 | 特征 | 常见原因 |
|------|------|----------|
| **恒定偏移** | 所有字幕统一偏快/偏慢固定秒数 | 片头片尾裁剪、转码偏移 |
| **渐进漂移** | 越往后越偏，偏移量增大 | 帧率转换(25↔29.97fps) |
| **分段偏移** | 中间正常，前后段偏移不同 | 广告剪除未调字幕 |

### 2B.4.1 恒定偏移校正

```python
def shift_srt_timestamps(srt_entries: list[dict], offset_sec: float):
    shifted = []
    for entry in srt_entries:
        new_start = entry['start'] + offset_sec
        new_end = entry['end'] + offset_sec
        if new_start < 0:
            continue
        shifted.append({**entry, 'start': new_start, 'end': new_end})
    return shifted

def write_shifted_srt(entries: list[dict], output_path: str):
    def to_srt(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')
    lines = []
    for i, e in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{to_srt(e['start'])} --> {to_srt(e['end'])}")
        lines.append(e['text'])
        lines.append("")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
```

### 2B.4.2 渐进漂移校正

```python
def correct_drift(srt_entries, head_offset, tail_offset, total_duration):
    drift_rate = (tail_offset - head_offset) / total_duration
    corrected = []
    for entry in srt_entries:
        t = (entry['start'] + entry['end']) / 2
        offset_at_t = head_offset + drift_rate * t
        new_start = entry['start'] + offset_at_t
        new_end = entry['end'] + offset_at_t
        if new_start < 0:
            continue
        corrected.append({**entry, 'start': new_start, 'end': new_end})
    return corrected
```

### 2B.4.3 VAD 辅助自动同步（高级）

对节目开头 30~60 秒运行 VAD，与 SRT 时间戳互相关匹配：

```python
import numpy as np

def auto_find_offset(vad_timestamps, srt_timestamps,
                     max_offset=10.0, step=0.1):
    resolution = 0.1
    total_len = int(max(vad_timestamps[-1][1], srt_timestamps[-1][1]) / resolution) + 1
    def to_signal(ts, length):
        sig = np.zeros(length, dtype=np.float32)
        for start, end in ts:
            sig[int(start/resolution):min(int(end/resolution), length)] = 1.0
        return sig
    vad_sig = to_signal(vad_timestamps, total_len)
    srt_sig = to_signal(srt_timestamps, total_len)
    offsets = np.arange(-max_offset, max_offset, step)
    cors = []
    for off in offsets:
        shift = int(off / resolution)
        if shift > 0:
            v, s = vad_sig[shift:], srt_sig[:len(vad_sig)-shift]
        elif shift < 0:
            s, v = srt_sig[-shift:], vad_sig[:len(srt_sig)+shift]
        else:
            v, s = vad_sig, srt_sig
        if len(v) == 0 or len(s) == 0:
            continue
        cors.append(np.dot(v, s) / (np.linalg.norm(v) * np.linalg.norm(s) + 1e-8))
    return offsets[np.argmax(cors)]
```

> **注意**：VAD 自动同步仅辅助参考，**始终人工复核**。

### 2B.4.6 第一句话对齐法（推荐）

对有固定开场白的节目（如"人生大事讨小娘"），批量检测偏移分类：

**决策树**：
1. SRT首句时间 > 100s → 字幕文件不完整，废弃
2. 含标准开场白 AND SRT首句 < 15s → 恒定偏移，可校正
3. 含标准开场白 AND VAD首声 < 10s → VAD误检，忽略
4. 首句不是标准开场白 → 非标准开场，忽略
5. 其他 → 待人工审查

完整代码见原始文档 `batch_detect_sync.py` 参考。

### 2B.4.4 偏移校正标准工作流

```python
# 方式一（推荐）：人工判断 → 修正 SRT
offset = float(input("请输入偏移量（秒，正=字幕滞后，负=字幕超前）: "))
with open('节目_cleaned.srt', encoding='utf-8') as f:
    entries = parse_srt(f.read())
corrected = shift_srt_timestamps(entries, offset)
write_shifted_srt(corrected, '节目_synced.srt')

# 然后用同步后的 SRT 切分
segments = slice_audio_by_timestamp('source.mp4', '输出切片/', corrected)
```
