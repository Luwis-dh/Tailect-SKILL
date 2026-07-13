# 文本处理与 Manifest 生成（步骤 4、4.6、5）

---

## 步骤 4：文本清洗与标准化

### 操作流程
1. **Unicode 标准化**：统一为 NFC 格式
2. **脏字符去除**：移除控制字符、零宽字符、多余空白
3. **标点处理**：保留中英文标点
4. **数字/英文处理**：根据语言学合理性处理
5. **一致性校验**：确保 `text` 不为空
6. **语言前缀**：添加 `language <DIALECT><asr_text>` 前缀

### Text-to-JSONL 代码模板
```python
def text_to_asr_entry(text, audio_path, duration,
                      dialect_name="",         # 从方言前缀对照表取值
                      speaker_id=None,
                      utterance_type=None,
                      quality_flags=None):
    """
    将单条文本转为标准 JSONL 条目。
    
    Args:
        dialect_name: 方言名，如 "Tiantai"、"Xianju"、"Linhai" 等。
                      请从技能文档的「方言前缀对照」表取值。
                      若为 "" 则不添加语言前缀。
    """
    text = text.strip()
    if not text:
        return None

    if duration < 0.3:
        duration_bucket = 'too_short'
    elif duration < 1.5:
        duration_bucket = 'word_0.3_1.5s'
    elif duration < 3.0:
        duration_bucket = 'short_1.5_3s'
    elif duration < 10.0:
        duration_bucket = 'medium_3_10s'
    else:
        duration_bucket = 'long_10s+'

    prefix = f"language {dialect_name}<asr_text>" if dialect_name else ""

    entry = {
        "audio": audio_path,
        "text": prefix + text,
        "duration": duration,
        "duration_bucket": duration_bucket,
    }
    if speaker_id:
        entry["speaker_id"] = speaker_id
    if utterance_type:
        entry["utterance_type"] = utterance_type
    if quality_flags:
        entry["quality_flags"] = quality_flags
    return entry
```

---

## 步骤 4.6：标点符号恢复（可选）

### 适用场景
- ASR 训练数据文本无标点
- TTS 训练数据需要完整标点

### 推荐模型
```bash
pip install funasr modelscope
modelscope download --model iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch
```

### 处理流程
```
原始文本 → 去掉已有标点 → funasr batch 推理 → 恢复标点 → 写回
```

### 代码模板
```python
import os, json, re
import warnings
warnings.filterwarnings("ignore")
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from funasr import AutoModel

DIALECT_PREFIX = "Tiantai"  # 根据实际方言修改
TEXT_PREFIX = f"language {DIALECT_PREFIX}<asr_text>"
BATCH_SIZE = 64

PUNCT_PAT = re.compile(r'[\u3000-\u303f\uff00-\uffef\u2000-\u206f'
                        r'\u0021-\u002f\u003a-\u0040\u005b-\u0060\u007b-\u007e]')

def strip_punct(text):
    return PUNCT_PAT.sub("", text)

def needs_punctuation(text):
    stripped = re.sub(r'language \w+<asr_text>', '', text)
    if re.search(r'[，。？！、；：]', stripped):
        return False
    return bool(re.search(r'[\u4e00-\u9fff]', stripped))

def add_punctuation(entries: list[dict]) -> list[dict]:
    model = AutoModel(
        model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
        disable_update=True, log_level="WARNING",
    )
    texts, indices = [], []
    for i, e in enumerate(entries):
        t = e["text"]
        if not needs_punctuation(t):
            continue
        if t.startswith(TEXT_PREFIX):
            clean = strip_punct(t[len(TEXT_PREFIX):])
            if clean.strip():
                texts.append(clean)
                indices.append(i)

    for bs in range(0, len(texts), BATCH_SIZE):
        batch = texts[bs:bs + BATCH_SIZE]
        outputs = model.generate(batch)
        for j, out in enumerate(outputs):
            idx = indices[bs + j]
            punct_text = out["text"] if isinstance(out, dict) else out
            entries[idx]["text"] = TEXT_PREFIX + punct_text
    return entries

# 使用示例
PREPROC_DIR = "临海/预处理"
for fname in ["train.jsonl", "dev.jsonl", "test.jsonl"]:
    fpath = os.path.join(PREPROC_DIR, fname)
    entries = [json.loads(l) for l in open(fpath, encoding='utf-8') if l.strip()]

    # 备份原始
    bak_path = fpath.replace(".jsonl", ".bak_无标点.jsonl")
    with open(bak_path, 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    entries = add_punctuation(entries)

    with open(fpath, 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
```

---

## 步骤 5：Manifest 生成

### 按时长排序写入
```python
import json

def write_sorted_manifest(entries: list[dict], output_path: str):
    def get_duration_seconds(e):
        d = e.get('duration', 0)
        if isinstance(d, (int, float)):
            return float(d)
        return float(str(d).rstrip('s'))

    entries.sort(key=get_duration_seconds)
    with open(output_path, 'w', encoding='utf-8') as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
```

---

## 音频文件名标准化

### 问题
- Docker 容器中文路径 I/O 错误
- 跨平台兼容性差
- 特殊字符需转义

### 命名规范
`{source}_{5位序号}[_p3位切片序号].wav`

| 原文件名 | 新文件名 |
|----------|----------|
| `你电瓶车停着，监控...啊_1.wav` | `110_audio_00001.wav` |
| `什么大意？.wav` | `magic_MagicData_00001.wav` |
| `..._p001.wav`（切片） | `110_audio_00042_p001.wav` |

### 操作流程
1. 扫描 `预处理/audio/` 下所有 `.wav`，按来源目录分组
2. 生成 `rename_map.jsonl`（新旧文件名映射）
3. 备份所有 jsonl
4. `os.rename(old, new)`，不覆盖
5. 更新所有 jsonl 中的 `audio` 字段
6. 验证所有路径

### 代码模板
```python
import json, os, re
from collections import defaultdict
from pathlib import Path

def generate_rename_plan(audio_root, min_digits=5):
    source_files = defaultdict(list)
    for fpath in sorted(Path(audio_root).rglob("*.wav")):
        rel = fpath.relative_to(audio_root)
        source = rel.parts[0].replace(" ", "_")
        source_files[source].append(fpath)

    rename_entries = []
    seq_counter = defaultdict(int)
    for source_key in sorted(source_files.keys()):
        for fpath in sorted(source_files[source_key]):
            seq_counter[source_key] += 1
            stem = fpath.stem
            slice_suf = re.search(r'(_p\d{3})$', stem)
            sfx = slice_suf.group(1) if slice_suf else ""
            new_stem = f"{source_key}_{seq_counter[source_key]:0{min_digits}d}{sfx}"
            new_path = fpath.parent / f"{new_stem}.wav"
            rename_entries.append((fpath, new_path))

    with open("rename_map.jsonl", 'w', encoding='utf-8') as f:
        for old, new in rename_entries:
            f.write(json.dumps({"old_path": str(old), "new_path": str(new),
                                "old_stem": old.stem, "new_stem": new.stem},
                               ensure_ascii=False) + '\n')
    return rename_entries


def update_jsonl_paths(jsonl_files, rename_entries):
    path_map = {str(o): str(n) for o, n in rename_entries}
    for jf in jsonl_files:
        records = []
        with open(jf, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                old = record.get("audio", "")
                if old in path_map:
                    record["audio"] = path_map[old]
                records.append(record)
        with open(jf, 'w', encoding='utf-8') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
```

### 路径验证
```python
def verify_audio_paths(entries: list[dict]) -> list[str]:
    missing = []
    for e in entries:
        apath = e.get("audio", "")
        if apath and not os.path.exists(apath):
            missing.append(apath)
    return missing

for fn in ["train.jsonl", "dev.jsonl", "test.jsonl", "manifest.jsonl"]:
    entries = [json.loads(l) for l in open(fn, encoding='utf-8') if l.strip()]
    missing = verify_audio_paths(entries)
    print(f"{fn}: {len(entries)} 条" +
          (f" | ⚠ {len(missing)} 个路径缺失" if missing else " | ✓ 全部存在"))
```
