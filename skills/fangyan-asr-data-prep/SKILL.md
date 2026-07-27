---
name: fangyan-asr-data-prep
description: '方言语音识别(ASR)训练数据构建与预处理。覆盖录音访谈(VAD边界检测)、电视台节目(SRT字幕切分+同步校正)、超长音频智能切片(ForcedAligner强制对齐)。包含短音频保护、SRT噪声清洗、音画同步校正、文本标准化、音频去重、分层数据集划分、质量控制、会话隔离划分、异构数据源分层、路径迁移修复、批量duration补齐、完整性自动检查、方言前缀归一化、测试集追加模式。'
argument-hint: '指定方言区域目录名，如 天台、太平、临海、仙居、城区、三门、温州、舟山、嘉兴；或指定处理模式: srt(字幕切分) / vad(VAD切分) / merge(合并划分)'
user-invocable: true
---

# 方言 ASR 训练数据构建与预处理管线

## 概述

从**原始音频+文本标注**到**可直接用于 ASR 训练的 JSONL 数据集**的完整管线。

### 三种数据源处理路径

```
录音访谈类: raw/音频 → 格式统一 → VAD语音边界检测 → manifest → 去重 → 划分
电视台节目类: raw/视频+SRT → SRT噪声清洗 → 音画同步校正 → 按时间戳切分 → manifest → 去重 → 划分
超长音频: 超时文件(>20s) → ForcedAligner强制对齐 → 标点定位切分 → 合并 → 重新划分
```

### 核心原则

- **短音频不是默认异常**：完整清晰的词汇级短音频保留，通过分桶和分层采样使用
- **标记优先于删除**：异常优先打标签，按标签分层使用
- **无损原始数据**：`raw/` 不动，所有处理在 `预处理/` 副本中
- **方言前缀大小写统一**：各数据集合并前必须检查 `language <方言><` 的大小写一致性（如 `XianJu` 和 `Xianju` 必须统一），避免同一方言被误判为两种

## 何时使用

- 为方言区域构建 ASR 训练数据集
- 需要 VAD 切分、SRT 字幕切分、音画同步校正
- 需要生成标准 JSONL manifest、train/dev/test 划分
- 需要数据去重、质量控制

---

## 参考文档索引

| 文档 | 内容 |
|------|------|
| [00-annotation-formats.md](./references/00-annotation-formats.md) | 常见标注格式解析（merged_dataset.txt、文件名即文本、SRT、JSONL 追加） |
| [01-env-and-setup.md](./references/01-env-and-setup.md) | 环境配置、音频格式统一、响度归一化、大规模并行处理 |
| [02-vad-processing.md](./references/02-vad-processing.md) | Silero VAD 语音边界检测 |
| [03-srt-processing.md](./references/03-srt-processing.md) | SRT 字幕切分+同步校正 |
| [04-forced-aligner.md](./references/04-forced-aligner.md) | ForcedAligner 强制对齐切片 |
| [05-text-and-manifest.md](./references/05-text-and-manifest.md) | 文本标准化、标点恢复、Manifest 生成 |
| [06-quality-split.md](./references/06-quality-split.md) | 数据去重、分层划分、质量控制、自动化验证 |

## 数据源分支

| 数据来源 | 推荐路径 | 参考文档 |
|----------|----------|----------|
| 录音访谈/现场采集（纯文本标注） | VAD 语音边界检测 | [VAD 处理](./references/02-vad-processing.md) |
| 电视台节目（SRT 字幕） | SRT 时间戳切分+同步校正 | [SRT 处理](./references/03-srt-processing.md) |
| 超长音频（>20s，有文本） | ForcedAligner 强制对齐切片 | [ForcedAligner](./references/04-forced-aligner.md) |

---

## 数据结构规范

### 目录结构

```
<方言区>/
├── raw/                     # 原始数据（输入）
├── 预处理/                   # 处理后数据（输出）
│   ├── manifest.jsonl       # 全量清单
│   ├── train.jsonl          # 训练集
│   ├── dev.jsonl            # 验证集
│   ├── test.jsonl           # 测试集
│   ├── <音频切片目录>/
│   ├── 超时文件.txt
│   └── 处理异常日志.txt
├── 处理脚本/
└── 存档_中间文件/
```

### JSONL 字段

```json
{
  "id": "utt_000001",
  "audio": "太平/预处理/YH_audio/001.wav",
  "text": "language Tiantai<asr_text>今天天气真好。",
  "duration": 5.234,
  "speaker_id": "spk_001",
  "duration_bucket": "medium_3_10s",
  "quality_flags": ["clean"]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `audio` | ✅ | 相对于数据集根目录的相对路径，**路径更新后需同步修改所有 JSONL** |
| `text` | ✅ | 格式: `language <方言><asr_text>内容`，方言名**大小写须统一**（如统一 `Xianju` 而非 `XianJu`） |
| `duration` | ✅ | 秒，float。若缺失可事后用 `ffprobe` 批量补齐 |
| `speaker_id` | 推荐 | 用于说话人隔离划分；无 speaker 信息时按 session 目录隔离 |
| `source` | 推荐 | 数据来源标识，如 `audio`、`douyin`、`guangdian`、`biaozhu`、`2025`、`110_biaozhu`。用于分来源统计和质量跟踪。若目录重命名则需同步更新 manifest |
| `duration_bucket` | 推荐 | `word_0.3_1.5s` / `short_1.5_3s` / `medium_3_10s` / `long_10s+` |
| `quality_flags` | 推荐 | `clean` / `noisy` / `short_utterance` 等 |

### 方言前缀对照

| 方言区 | 前缀 | 示例 |
|--------|------|------|
| 天台 | `language Tiantai<asr_text>` | 今天天气真好。 |
| 临海 | `language Linhai<asr_text>` | 各位观众大家好。 |
| 太平(温岭/玉环) | `language Taiping<asr_text>` | 你吃饭了吗？ |
| 仙居 | `language Xianju<asr_text>` | 这条路怎么走？ |
| 城区(椒黄路) | `language Chengqu<asr_text>` | 麻烦你讲慢一点。 |
| 三门 | `language Sanmen<asr_text>` | 好的，我知道了。 |
| 温州 | `language Wenzhou<asr_text>` | — |
| 舟山 | `language Zhoushan<asr_text>` | — |
| 嘉兴 | `language Jiaxing<asr_text>` | — |

---

## 管线步骤速览

| 步骤 | 内容 | 参考详情 |
|------|------|----------|
| **0. 环境准备** | 安装 FFmpeg、PyTorch、silero-vad 等 | [环境配置](./references/01-env-and-setup.md) |
| **1. 音频格式统一** | 16kHz/单声道/16-bit WAV，超长过滤 | [环境配置](./references/01-env-and-setup.md) |
| **2A. VAD 检测** | 录音访谈类，Silero VAD 边界检测+裁剪 | [VAD 处理](./references/02-vad-processing.md) |
| **2B. SRT 切分** | 电视台节目类，降噪→同步→切片 | [SRT 处理](./references/03-srt-processing.md) |
| **2C. 超长切片** | ForcedAligner 强制对齐+标点定位 | [ForcedAligner](./references/04-forced-aligner.md) |
| **3. 响度归一化** | 可选，多源数据响度统一 | — |
| **4. 文本标准化** | Unicode NFC、脏字符、方言前缀 | [文本处理](./references/05-text-and-manifest.md) |
| **4.6 标点恢复** | 可选，funasr 模型恢复标点 | [文本处理](./references/05-text-and-manifest.md) |
| **5. Manifest 生成** | JSONL 排序+音频文件名标准化 | [文本处理](./references/05-text-and-manifest.md) |
| **6. 数据去重** | 音频哈希去重，保留文本重复 | [质量控制](./references/06-quality-split.md) |
| **7. 数据集划分** | 会话隔离+时长桶分层+异构源策略 | [质量控制](./references/06-quality-split.md) |
| **7b. 方言前缀归一化** | 合并前检查 `language <方言>` 大小写一致性 | 本页常见问题 |
| **7c. 异构数据源分层** | 独立条目 + 会话级数据分开处理 | 本页下方详细说明 |
| **7d. 完整性检查** | JSONL 全量扫描：音频存在性 + duration 完整性 | 本页下方详细说明 |
| **8. 质量控制** | 自动检查+人工审查 | [质量控制](./references/06-quality-split.md) |
| **9. 日志与归档** | 处理日志、中间产物管理 | [质量控制](./references/06-quality-split.md) |

---

## 完整管线调用示例

### 场景 1：SRT 电视台节目

```python
# 1. 清洗 SRT (python clean_srt_noise.py --dir "raw/节目目录")

# 2. 解析 SRT
with open('节目_cleaned.srt', encoding='utf-8') as f:
    entries = parse_srt(f.read())

# 3. 音画同步校正（若发现偏移）
shifted = shift_srt_timestamps(entries, offset=2.5)

# 4. 按时间戳切分音频
segments = slice_audio_by_timestamp('节目.mp4', '输出切片/', shifted)

# 5. 生成 ASR 条目并排序写入
entries_out = [text_to_asr_entry(s['text'], s['audio'], s['duration'])
               for s in segments if s['duration'] > 0.3]
write_sorted_manifest(entries_out, '预处理/manifest.jsonl')
```

### 场景 2：录音访谈

```bash
python audio_pipeline.py "E:\方言\天台" --workers 8
```

### 场景 3：合并 manifest 并划分

```bash
python 合并manifest并生成训练集.py
```

## 推荐三阶段执行策略（大规模数据）

当数据集规模超过 1 万条时，建议将线性管线拆分为三个阶段，每阶段输出独立可验证的产物：

```
Phase 1 — 基础数据集
  raw/ → 格式统一 → manifest → 去重 → 划分
  （排除 >20s 超长音频，写入超时文件清单）
  → 产物可直接用于 ASR 训练
  → 耗时与数据量正相关，CPU/磁盘密集型

Phase 2 — 超长音频补救（可选）
  超时文件 → ForcedAligner 强制对齐 → 标点定位切片
  → 依赖 Phase 1 的超时清单
  → GPU 密集型，失败不影响基础集完整性

Phase 3 — 合并与重划分（仅在 Phase 2 执行后需要）
  基础 manifest + 切片 manifest → 合并 → 统一重划分
  → 最终 train/dev/test
```

**优点**：
- Phase 1 产物可先落地训练，不阻塞后续开发
- Phase 2 失败不影响基础集完整性
- 每阶段结束都有一个可验证的 checkpoint
- 可选择只做 Phase 1（数据量远大于训练需求时）

---

## 进阶实践（基于真实项目经验）

### 1. 会话隔离划分（Session-based Partitioning）

**问题场景**：110 接警数据中，一通电话包含多轮对话（多个 WAV），同一通话的所有语句必须划入同一集合（全进 train 或全进 test），不能拆分。

**策略**：
- 以 session 目录（或 hash 目录）为划分**原子单位**，而非以单条 utterance
- session 目录样例如 `1781712295_33100087cd2b3022564ae9b63d4a2f35b1334a/`
- 每个 session 目录下 N 个 WAV（N 通常 5~90 条不等）

```python
import random
from collections import defaultdict

# 按 session 分组
session_groups = defaultdict(list)
for entry in all_entries:
    session_id = extract_session_id(entry["audio"])
    session_groups[session_id].append(entry)

session_ids = list(session_groups.keys())
random.shuffle(session_ids)

# 取前 N 个 session → test
test_session_ids = set(session_ids[:N])  # N=10 通常够用
test_entries = []
for sid in test_session_ids:
    test_entries.extend(session_groups[sid])

# 其余 → train
train_entries = []
for sid in session_ids[N:]:
    train_entries.extend(session_groups[sid])
```

**注意事项**：
- 10 个 session 通常包含 160~300 条 utterance，因方言而异（session 内条目数 1~93 不等）
- 需提前统计各区域 session 数量和平均条目数，确保 test 集规模可控

---

### 2. 异构数据源分层策略

**问题场景**：总数据集包含多种来源，需不同策略处理：

| 数据源类型 | 示例 | 处理策略 |
|-----------|------|---------|
| **独立条目** | 各方言区独立 train.jsonl | 按说话人/时长桶分层抽取 |
| **会话数据** | 110 接警录音 | 按 session 目录隔离抽取 |
| **追加测试集** | 太平(仅891条) | 不进 train/dev，**全部追加到 test** |

**三步策略**：

```
Step 1: 各类源独立处理，分别产出 (train_src, dev_src, test_src)
Step 2: 合并同类集合 train_src_A + train_src_B → train
Step 3: 追加仅测试源 test_src_extra → test（不参与均匀分配）
```

**各源分别确定需要多少条进 test/dev**，然后将 dev/test 各源的样本合并后去重：

```python
# 主方言：时长桶分层 → dev:1000, test:1000
dev_main = stratified_by_duration(pool_main, target=1000)
test_main = stratified_by_duration(pool_main_remaining, target=1000)

# 110 会话数据：取 10 个 session → test
test_110 = extract_sessions(pool_110, n_sessions=10)

# 追加测试集：全进 test，不进 dev/train
test_extra = pool_extra_all  # 如太平 891 条

# 合并：test 总量 = 主方言 test + 110 test + 追加测试集
test_final = test_main + test_110 + test_extra
```

---

### 3. 时长桶分层抽样

**问题场景**：dev/test 的时长分布应与训练集基本一致，避免"test 全短句/train 全长句"的测量偏差。

**定义**：
```
超短 word:   0.3 ~ 1.5s  词汇级/命令词
短   short:  1.5 ~ 3.0s  短语
中   medium: 3.0 ~ 10.0s 短句
长   long:   10.0s+       长句/段落
```

**分层抽取代码**：

```python
from collections import defaultdict

def stratified_by_duration(pool, target_per_dialect):
    """按方言+时长桶分层抽样，从 pool 中抽出 target 条。"""
    # 1. 按方言+时长桶分组
    buckets = defaultdict(list)
    for e in pool:
        d = detect_dialect(e["text"])
        dur = e.get("duration", 0)
        bucket = get_bucket(dur)
        buckets[(d, bucket)].append(e)
    
    # 2. 计算各方言的时长桶比例
    dialect_stats = defaultdict(lambda: defaultdict(int))
    for (d, b), entries in buckets.items():
        dialect_stats[d][b] = len(entries)
    
    selected = []
    for dialect in sorted(set(d for d, _ in buckets)):
        total_d = sum(dialect_stats[dialect].values())
        for bucket, count in dialect_stats[dialect].items():
            ratio = count / total_d
            n = max(1, round(target_per_dialect * ratio))
            pool_b = buckets[(dialect, bucket)]
            random.shuffle(pool_b)
            selected.extend(pool_b[:n])
    
    random.shuffle(selected)
    return selected
```

**验证方法**：
```
train.jsonl 时长分布:  word 10%  short 22%  medium 65%  long 3%
dev.jsonl   时长分布:  word 10%  short 22%  medium 65%  long 3%  ← 应与训练集一致
```

---

### 4. 批量补全 duration 字段

**问题场景**：TianTai 等旧数据集中 70%+ 样本缺失 `duration` 字段，需事后扫描补齐。

**方法**：并行 `ffprobe` 扫描

```python
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_WORKERS = 32  # ffprobe I/O 密集型，可多线程

def get_duration_ffprobe(audio_path):
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return None

def batch_fill_duration(entries):
    """批量补全 duration，返回更新后的 entries。"""
    paths = set()
    for e in entries:
        if e.get("duration") is None and e.get("audio"):
            resolved = resolve_audio_path(e["audio"])
            if resolved:
                paths.add(resolved)
    
    dur_map = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_map = {ex.submit(get_duration_ffprobe, p): p for p in paths}
        for fut in as_completed(fut_map):
            p = fut_map[fut]
            d = fut.result()
            if d and d > 0:
                dur_map[p] = round(d, 3)
    
    for e in entries:
        resolved = resolve_audio_path(e["audio"])
        if resolved in dur_map:
            e["duration"] = dur_map[resolved]
            e["duration_bucket"] = get_bucket(dur_map[resolved])
    return entries
```

**经验值**：12 万文件扫描耗时约 5~10 分钟（32 线程），成功率接近 100%。

---

### 5. 路径迁移与 JSONL 更新

**问题场景**：数据目录重组后（如中文字典名 → 英文字典名），JSONL 中的路径成为死链接。

**典型迁移映射**：
| 旧路径（JSONL 中） | 新路径（实际文件位置） |
|-------------------|----------------------|
| `仙居/预处理/audio/XXX/YYY.wav` | `Xianju/audio/XXX/YYY.wav` |
| `三门/预处理/三门合并音频/XXX/YYY.wav` | `Sanmen/三门合并音频/XXX/YYY.wav` |
| `三门/预处理/超长切片/XXX.wav` | `Sanmen/超长切片/XXX.wav` |
| `三门/预处理/电视台切片/XXX.wav` | `Sanmen/电视台切片/XXX.wav` |
| `智慧110真实标注/预处理/110_audio/...` | `110/110_audio/...` |

**处理流程**：
1. 先备份原始 JSONL（`cp file.jsonl file.jsonl.bak_迁移`）
2. 用字典映射批量替换路径前缀（Python 字符串 `replace`）
3. 全量验证：每条路径 `os.path.exists()` 检查通过
4. 输出验证报告，确认 100% 通过

**验证命令**：
```python
import os
ok = sum(1 for e in entries if os.path.exists(e["audio"]))
total = len(entries)
print(f"{ok}/{total} ({ok/total*100:.1f}%)")
```

---

### 6. 方言前缀大小写归一化

**问题场景**：不同来源数据可能使用不同大小写，如 `language XianJu<` vs `language Xianju<`，导致方言检测遗漏。

**修复方法**：
```python
# 扫描所有 JSONL 统一修复
import json, os, shutil

for fpath in [train_jsonl, dev_jsonl, test_jsonl]:
    fixed = 0
    entries = []
    with open(fpath) as f:
        for line in f:
            d = json.loads(line)
            text = d.get("text", "")
            if "language XianJu<" in text:  # 检测不当大小写
                d["text"] = text.replace("language XianJu<", "language Xianju<")
                fixed += 1
            entries.append(d)
    if fixed:
        bak = fpath + ".bak_case"
        shutil.copy2(fpath, bak)
        with open(fpath, "w") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"{fpath}: 修正 {fixed} 条")
```

---

### 7. 数据完整性自动检查

**检查清单**：

| 检查项 | 方法 | 判定 |
|--------|------|------|
| 音频文件存在 | `os.path.exists(audio)` | 100% 必须通过 |
| 音频格式合规 | `wave.open()` 检查: 16kHz/1ch/16bit | 发现问题记录即可 |
| duration 字段 | 检查 `get("duration") is None` | 建议 100% 补齐 |
| 方言前缀统一 | `re.search(r'language (\w+)<', text)` 统计所有方言名 | 不应有意外方言 |
| 路径分隔符 | 检查是否含 `\\` | 应统一为 `/` |
| JSON 语法 | 逐行 `json.loads()` | 全部通过 |

**全量扫描脚本结构**：
```python
def verify_jsonl(filepath, data_root, path_aliases=None):
    """返回 {total, ok, missing, empty, errors}"""
    issues = []
    total = ok = 0
    with open(filepath) as f:
        for lineno, line in enumerate(f, 1):
            d = json.loads(line)
            ap = d.get("audio", "").replace("\\\\", "/")
            resolved = resolve_with_aliases(ap, data_root, path_aliases)
            if not resolved or not os.path.exists(resolved):
                issues.append(f"L{lineno}: 文件缺失 {ap[:80]}")
            else:
                # 可选：检查 WAV 格式
                ok += 1
            total += 1
    return {"total": total, "ok": ok, "issues": issues[:50]}
```

---

### 8. 测试集追加模式（Test-Only Append）

**问题场景**：太平(Taiping)方言只有 891 条数据，不足以做均匀分配（6 主方言各 1000 条）。策略是**全部追加到 test**，不参与训练和验证。

```python
# 主方言：均匀时长分层 → dev:1000, test:1000
dev_entries = []
test_entries = []
for dialect in main_dialects:
    dev_d = stratified_by_duration(pools[dialect], target=1000)
    test_d = stratified_by_duration(remaining, target=1000)
    dev_entries.extend(dev_d)
    test_entries.extend(test_d)

# 追加方言：仅进 test，不计入均匀分配
taiping_all = load_all_taiping()  # 891 条
test_entries.extend(taiping_all)

print(f"test 总计: {len(test_entries)} 条")
print(f"  (含追加方言: {len(taiping_all)} 条)")
```

| 方言区 | 脚本 | 功能 |
|--------|------|------|
| 天台 | `audio_pipeline.py` | 完整音频预处理管线 |
| 天台 | `generate_tiantai_ttrjs_dataset.py` | TTRJS 数据集生成 |
| 天台 | `rename_audio_files.py` | 音频文件名标准化 |
| 天台 | `timeout_slice_pipeline.py` / `slice_and_merge.py` | 超长音频切片 |
| 太平 | `玉环_audio_slice_parallel.py` | 音频并行切分 |
| 太平 | `太平_train_split.py` | 数据集划分 |
| 太平 | `add_to_manifest.py` | 追加到 manifest |
| 仙居 | `仙居5_28_预处理.py` | 音频预处理+VAD |
| 仙居 | `仙居5_28_超长补救切分.py` | 超长音频二次切分 |
| 仙居 | `合并manifest并生成训练集.py` | 多 manifest 合并划分 |
| 城区 | `append_to_train.py` | 追加到 train.jsonl |
| 临海 | `clean_srt_noise.py` | SRT 字幕噪声清洗 |
| **通用** | `scripts/repart_all_regions.py` | 多方言异构数据源分层重划分（会话隔离+时长桶+追加测试集） |
| **通用** | `scripts/fill_missing_duration.py` | 并行 ffprobe 批量补全缺失 duration 字段 |
| **通用** | `scripts/verify_jsonl_audio.py` | JSONL 完整性全量检查（音频存在性+路径别名解析） |

---

## 常见问题

| 问题 | 原因 | 处理 |
|------|------|------|
| SRT 恒定偏移 | 片头片尾裁剪未调字幕基准 | `shift_srt_timestamps(entries, offset)` |
| SRT 渐进漂移 | 帧率转换(25↔29.97fps) | `correct_drift()` 线性校正 |
| 文件名特殊字符 | Docker 跨平台 I/O 错误 | 标准化为 `{source}_{5位序号}.wav` |
| 时长计算偏差 | wave 模块格式不支持 | 统一用 `ffprobe` |
| SRT 清洗过度 | 正则误命中 | `--dry-run` 预览后调整 |
| 切分后无声 | 字幕偏移未校正 | 质检间隙检测+首尾静音比 |
| 预处理目录磁盘飙升 | 复制+转换大量音频 | 执行前预估：`du -sh raw/` 乘以 2~3 倍预留空间；已合格音频用 `-c copy` 流复制减少重编码开销 |
| **JSONL 方言前缀大小写不一致** | 不同来源标注习惯不同（`XianJu` vs `Xianju`） | 合并前做统一替换，备份后全局查找替换 |
| **路径重组后 JSONL 死链接** | 目录从中文名改为英文名后 JSONL 未同步更新 | 建立新旧路径映射表，批量替换所有 JSONL，全量 `os.path.exists()` 验证 |
| **大量样本缺 duration** | 旧数据集预处理时未计算时长（天台 70%+） | 并行 ffprobe 扫描 12 万文件约 5~10 分钟 |
| **会话数据不能按条拆分** | 一通 110 通话的多个 WAV 不能分到不同集合 | 以 session hash 目录为原子单位，整 session 划入同一 split |
| **稀有方言测试集不足** | 某方言数据量远小于主方言，无法均匀分配 | 采用"追加模式"：全部放入 test 作为额外数据，不参与均匀分配 |
| **旧课程学习数据引用已删除文件** | `train_curriculum.jsonl` 引用了旧仙居录音目录（已合并到 `audio/`） | 若需使用，需重建 curriculum 文件（移除无效路径）；或直接废弃 |
| **dev/test 时长分布与训练集不一致** | 纯随机抽样导致短句/长句比例偏差 | 使用时长桶分层抽样，确保 dev/test 比例与 train 一致 |

---

## 设计原则

1. **无损原始数据**：`raw/` 不动，`预处理/` 副本处理
2. **可复现**：所有随机操作固定 seed，参数记日志
3. **最小修改**：优质音频不降噪/归一化
4. **尽早过滤**：超长/为空/损坏尽早排除；但短音频不是异常
5. **标记优先于删除**：异常打标签，按标签分层使用
6. **持续记录**：每步骤输出详细日志
7. **方言前缀一致性**：多源合并前必须统一 `language <方言>` 的大小写
8. **会话原子性**：同一通话/录音的多个片段不得拆分到不同 split
9. **测试集追加模式**：数据量不足的方言可全部追加到 test 而非强行均匀分配
