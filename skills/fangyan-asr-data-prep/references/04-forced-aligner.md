# 超长音频智能切片 — ForcedAligner 强制对齐（步骤 2C）

**目标**：将 `超时文件.txt` 中超长（>20s）但有文本标注的音频，智能切分为多段短音频（<25s）。

## 适用场景

| 数据类型 | 典型来源 | 文本来源 |
|----------|----------|----------|
| 录音访谈/对话 | 110报警录音、客服录音 | 文件名即文本 |
| 节目片段 | 电视台节目长片段 | 文件名或 SRT |
| 语料朗读 | TTRJS 等长句朗读 | 文件名即完整文本 |

## 核心工具

**Qwen3-ForcedAligner-0.6B**：非自回归语音强制对齐模型。

```bash
pip install qwen-asr
modelscope download --model Qwen/Qwen3-ForcedAligner-0.6B --local_dir ./Qwen3-ForcedAligner-0.6B
```

## 关键行为：ForcedAligner 不输出标点

输出 segments **仅含 CJK 中文字符和字母数字**，所有标点不被输出。切片时必须用**源文本标点位置** + ForcedAligner 字符时间戳定位切分点。

```
源文本: "今天天气真好，我们出去玩吧。"
ForcedAligner输出:
  [0.0s]今 [0.2s]天 [0.4s]天 [0.6s]气 [0.8s]真 [1.0s]好
  [1.5s]我 [1.7s]们 [1.9s]出 [2.1s]去 [2.3s]玩 [2.5s]吧
  → "，"在"好"(1.2s)和"我"(1.5s)之间 → 约1.35s
```

## 三级切片策略

```
超时音频 (>20s)
├─ 源文本含 。？！ → 在句末标点处切分（最精确）
├─ 源文本无 。？！但有 ， → 在逗号处切分
└─ 源文本无任何标点 → 按 ~10s 目标时长均匀切分（保底）
```

## 处理流程

```
① 复制临时文件 → to_align/seq_00001.wav（扁平短名，避 Docker 中文路径问题）
② 生成映射 → mapping.jsonl: {id, original_path, temp_path, text}
③ Docker GPU 对齐 → Qwen3ForcedAligner.align() → results.jsonl
④ 标点位置插值 → 将源文本标点定位到时间轴
⑤ 音频切片 → 在原目录生成 _p001.wav 等
⑥ 生成切片 JSONL
⑦ 合并数据 → 备份原数据 → 合并切片 → 重新 90:5:5 划分
```

## 代码模板

### ⚠️ API 注意事项

| 问题 | 说明 |
|------|------|
| 返回类型 | `align()` 返回 `List[ForcedAlignResult]`，不是 `List[dict]` |
| 访问字符 | `results[0].items` 才是 `List[ForcedAlignItem]` |
| Item 属性 | 每个 item 有 `.text`, `.start_time`, `.end_time`（属性，非 dict key） |
| `audio` 参数 | 需显式 `str()` 转换，不支持 `Path` 对象 |
| `.eval()` | `Qwen3ForcedAligner` 对象**没有** `.eval()` 方法 |
| 模型路径 | 支持本地路径，优先使用本地模型可避免下载 |

### 加载模型
```python
import json, re, os, torch
from qwen_asr import Qwen3ForcedAligner

# 加载本地模型（推荐）或 HuggingFace/ModelScope 远程
MODEL_PATH = "./Qwen3-ForcedAligner-0.6B"  # 本地路径
# MODEL_PATH = "Qwen/Qwen3-ForcedAligner-0.6B"  # 远程

model = Qwen3ForcedAligner.from_pretrained(
    MODEL_PATH,
    dtype=torch.bfloat16,
    device_map="cuda:0",
)
# 注意：不要调用 model.eval() — Qwen3ForcedAligner 没有该方法
```

### 对齐（正确用法）
```python
results = model.align(
    audio=str(audio_path),  # audio 参数需要 str，不支持 Path
    text=source_text,       # 含标点的完整文本
    language="Chinese",
)

# align() 返回 List[ForcedAlignResult]
# ForcedAlignResult.items → List[ForcedAlignItem]
# 每个 item 有 .text, .start_time, .end_time（属性！不是 dict）
result_obj = results[0]
segments = [{
    'text': item.text,
    'start_time': float(item.start_time),
    'end_time': float(item.end_time),
} for item in result_obj.items]

print(f"对齐到 {len(segments)} 个字符")
# segments 仅含 CJK 中文字符和字母数字，不含标点
```

### 标点位置插值
```python
SENTENCE_END = set("。？！")
PAUSE_PUNCT = set("，、；：")

def locate_punctuation(segments, source_text):
    """
    将源文本中的标点位置映射到时间轴。
    ForcedAligner 输出不含标点，需要在前/后字符时间戳之间插值。
    """
    seg_idx = 0
    timed_chars = []
    for ch in source_text:
        if re.match(r'[\u4e00-\u9fff\w]', ch):
            if seg_idx < len(segments):
                timed_chars.append((ch, segments[seg_idx]['start_time'],
                                    segments[seg_idx]['end_time']))
                seg_idx += 1
            else:
                timed_chars.append((ch, 0, 0))
        else:
            if timed_chars and seg_idx < len(segments):
                est = (timed_chars[-1][2] + segments[seg_idx]['start_time']) / 2
            elif timed_chars:
                est = timed_chars[-1][2] + 0.05
            else:
                est = 0
            timed_chars.append((ch, est, est))
    return timed_chars
```

### 在标点处切分
```python
def split_at_punctuation(timed_chars, min_dur=1.0, max_dur=20.0):
    """
    按标点位置将时间戳序列切分为音频片段。
    优先在句末标点切分，其次逗号，最后无标点时均匀切分。
    """
    slices = []
    start = 0
    has_sentence_end = any(c[0] in SENTENCE_END for c in timed_chars)
    punct_set = SENTENCE_END | PAUSE_PUNCT if has_sentence_end else PAUSE_PUNCT

    for i, (ch, st, et) in enumerate(timed_chars):
        if ch not in punct_set:
            continue
        end = i + 1
        parts = timed_chars[start:end]
        text = ''.join(c[0] for c in parts).strip()
        if not text:
            start = end
            continue
        dur = parts[-1][2] - parts[0][1]
        if min_dur <= dur <= max_dur:
            slices.append({'text': text, 'start_time': parts[0][1],
                           'end_time': parts[-1][2], 'duration': round(dur, 3)})
        start = end

    if start < len(timed_chars):
        rem = timed_chars[start:]
        text = ''.join(c[0] for c in rem).strip()
        if text:
            dur = rem[-1][2] - rem[0][1]
            if min_dur <= dur:
                if dur > max_dur:
                    # 无标点时均匀切分
                    n_parts = max(1, round(dur / 12.0))
                    target = dur / n_parts
                    for p in range(n_parts):
                        p_start = start + int(p * len(rem) / n_parts)
                        p_end = start + int((p + 1) * len(rem) / n_parts)
                        if p_end > len(timed_chars):
                            p_end = len(timed_chars)
                        if p_start >= p_end:
                            continue
                        p_parts = timed_chars[p_start:p_end]
                        p_text = ''.join(c[0] for c in p_parts).strip()
                        if p_text:
                            p_dur = p_parts[-1][2] - p_parts[0][1]
                            if min_dur <= p_dur <= max_dur:
                                slices.append({
                                    'text': p_text,
                                    'start_time': p_parts[0][1],
                                    'end_time': p_parts[-1][2],
                                    'duration': round(p_dur, 3)
                                })
                else:
                    slices.append({
                        'text': text, 'start_time': rem[0][1],
                        'end_time': rem[-1][2], 'duration': round(dur, 3)
                    })
    return slices
```

### 安全对齐（带重试和错误捕获）
```python
def try_align(model, audio_path, raw_text, max_retries=1):
    for attempt in range(max_retries + 1):
        try:
            results = model.align(
                audio=str(audio_path),
                text=raw_text,
                language="Chinese",
            )
            if results and len(results) > 0:
                items = results[0].items if hasattr(results[0], 'items') else []
                seg_list = [{
                    'text': item.text,
                    'start_time': float(item.start_time),
                    'end_time': float(item.end_time),
                } for item in items if hasattr(item, 'text')]
                if len(seg_list) >= 2:
                    return seg_list, None
                else:
                    return None, f"too_few_segments({len(seg_list)})"
            else:
                return None, "empty_results"
        except Exception as e:
            err = str(e)
            if attempt < max_retries:
                time.sleep(1)
            else:
                return None, err
    return None, "max_retries_exceeded"
```

## 切片音频命名规范

```
原: 你电瓶车停着，监控看到有人拿走了啊_1.wav
切片: 你电瓶车停着，监控看到有人拿走了啊_1_p001.wav
     你电瓶车停着，监控看到有人拿走了啊_1_p002.wav
```

推荐用扁平化短文件名（避免 Docker 中文 I/O 问题）：
```
to_align/seq_00001.wav
slices/seq_00001_fa_001.wav
slices/seq_00001_fa_002.wav
```

## 推荐三阶段执行策略

超长音频补救是全管线中 GPU 计算最密集、失败可能性最高的步骤，建议**与基础数据管线分离**：

| 阶段 | 内容 | 产物 | 独立可验证？ |
|------|------|------|------------|
| Phase 1 | 格式统一→manifest→去重→划分（排除超长） | `train.jsonl` 等，不含 >20s 数据 | ✅ 可直接训练 |
| Phase 2 | ForcedAligner 对齐→标点定位→切片 | `timeout_slices_manifest.jsonl` | 依赖 Phase 1 的超时清单 |
| Phase 3 | 合并基础 + 切片→统一重划分 | 最终 `train.jsonl`、`dev.jsonl`、`test.jsonl` | ✅ 最终产物 |

**优点**：Phase 1 产物的训练不阻塞，Phase 2 失败不影响基础集完整性，每阶段结束都有可验证的 checkpoint。

## 参考脚本

- `timeout_slice_pipeline.py` — 超时文件解析 + 临时文件准备 + Docker 对齐管理
- `slice_and_merge.py` — 标点切片 + 音频切分 + 合并重划分
