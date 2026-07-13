# 常见标注格式解析规范（步骤 0）

**目标**：统一处理不同来源的文本标注格式，将其解析为结构化数据供后续管线使用。

## 场景 1：`merged_dataset.txt`（文本+位置配对）

本格式在方言 ASR 数据中最为常见，典型结构为每三行一组：

```
文本：今天天气真好。
位置：audio\陈璐鑫_7959\41.wav

文本：你吃饭了吗？
位置：audio\张伟_1234\42.wav
```

每组包含：
- 第 1 行：`文本：{标注文本}`
- 第 2 行：`位置：{音频相对路径}`
- 第 3 行：空行（分隔符，可缺失）

### 解析核心逻辑

```python
import json, re
from pathlib import Path

def parse_merged_dataset(txt_path, raw_dir, output_jsonl=None):
    """
    解析 merged_dataset.txt，返回标准化的 entry 列表。
    
    Args:
        txt_path: merged_dataset.txt 的完整路径
        raw_dir: raw 目录（音频路径的基准目录）
        output_jsonl: 可选，写入解析结果到 JSONL
    """
    entries = []
    errors = {"empty_text": 0, "missing_audio": 0, "dup_path": 0}
    seen_paths = set()

    with open(txt_path, encoding='utf-8') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # 跳过空行和无关行
        if not line or not (line.startswith('文本：') or line.startswith('文本:')):
            i += 1
            continue
        
        # 提取文本
        text = re.sub(r'^文本[：:]', '', line).strip()
        
        # 下一行应是位置行
        i += 1
        pos_line = lines[i].strip() if i < len(lines) else ''
        
        audio_rel = ''
        if pos_line.startswith('位置：') or pos_line.startswith('位置:'):
            audio_rel = re.sub(r'^位置[：:]', '', pos_line).strip()
            # 统一 Windows 反斜杠
            audio_rel = audio_rel.replace('\\', '/')
        
        i += 1  # 跳过空行
        
        # 校验
        if not text:
            errors["empty_text"] += 1
            continue
        
        full_path = raw_dir / audio_rel
        if not full_path.exists():
            errors["missing_audio"] += 1
            continue
        
        if audio_rel in seen_paths:
            errors["dup_path"] += 1
            continue
        seen_paths.add(audio_rel)
        
        # 推断 source 字段：从音频路径的第一级目录名
        source = audio_rel.split('/')[0] if '/' in audio_rel else 'unknown'
        
        entries.append({
            "raw_audio": audio_rel,
            "text": text,
            "source": source,
        })
    
    return entries, errors
```

### 关键处理细节

| 问题 | 处理 |
|------|------|
| 路径分隔符 | Windows 生成时用 `\`，统一替换为 `/` |
| 首部/尾部非标准行 | 逐行扫描 `文本：` 标识，不假设行号 |
| 空文本 | `文本：` 后无内容的行 → 记录 `empty_text` |
| 重复音频路径 | 同一路径出现多次 → 只保留第一次，后续记录 `dup_path` |
| 音频文件缺失 | 路径存在但文件不存在 → 记录 `missing_audio` |
| 编码 | 统一 UTF-8，遇到 BOM 自动跳过 |

### 从目录名推断 `source`

这是多来源合并数据的常见做法。路径模式示例：

| 原始路径 | 推断 source | 说明 |
|----------|------------|------|
| `audio/陈璐鑫_7959/41.wav` | `audio` | 主录音访谈 |
| `douyin/阿南吃遍仙居_20260509/seg_001.wav` | `douyin` | 抖音短视频 |
| `biaozhu/a1b2c3d4.wav` | `biaozhu` | 外部标注 |
| `guangdian/999热线/seg_001.wav` | `guangdian` | 广电节目切片 |
| `2025/01_001.wav` | `2025` | 新增采集数据 |

如果原始数据已有 `source` 字段（如旧版 JSONL），优先使用既有的值。

---

## 场景 2：文件名即文本

部分数据集的文本直接编码在文件名中。

### 文件名模式

```
{说话人}_{文本}.wav
```

示例：`陈璐鑫_今天天气真好.wav`

### 解析策略

```python
def parse_filename_as_text(filepath):
    stem = filepath.stem  # 不含扩展名
    # 按约定分隔符拆分
    parts = stem.split('_', maxsplit=1)
    if len(parts) == 2:
        speaker_id, text = parts
        return speaker_id, text
    return None, stem
```

**注意事项**：
- 文本中的 `_` 易被误拆，建议约定分隔符为 `——` 或限定 maxsplit
- 文件名含 Windows 非法字符（`\ / : * ? " < > |`）需处理
- 文件名可能含句号 `.`，只去掉最后一个扩展名部分

---

## 场景 3：SRT 字幕

SRT 解析在 [03-srt-processing.md](./03-srt-processing.md) 中有详细说明，此处仅列出与标注解析相关的关键点：

```python
def parse_srt(content):
    """标准 SRT 解析：序号 → 时间轴 → 文本 → 清理"""
    entries = []
    for block in content.strip().split('\n\n'):
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        idx = lines[0].strip()
        time_range = lines[1].strip()
        text = '\n'.join(lines[2:]).strip()
        entries.append({
            'index': idx,
            'time_range': time_range,
            'text': text,
        })
    return entries
```

SRT 清洗策略见 [03-srt-processing.md](./03-srt-processing.md#srt-噪声清洗)。

---

## 场景 4：JSONL 已有产物追加

当需要合并多个已有 JSONL 文件时，需处理字段不一致的问题。

```python
def normalize_jsonl_entry(entry, dialect_name="Xianju"):
    """统一已有 JSONL 字段，补齐缺失字段。"""
    # 方言前缀
    text = entry.get('text', '')
    prefix = f"language {dialect_name}<asr_text>"
    if not text.startswith('language '):
        text = prefix + text
        entry['text'] = text
    
    # 补齐必填字段
    if 'duration' in entry and 'duration_bucket' not in entry:
        d = entry['duration']
        entry['duration_bucket'] = (
            "word_0.3_1.5s" if d < 1.5 else
            "short_1.5_3s" if d < 3.0 else
            "medium_3_10s" if d < 10.0 else
            "long_10s+"
        )
    
    if 'quality_flags' not in entry:
        entry['quality_flags'] = ['clean']
    
    return entry
```
