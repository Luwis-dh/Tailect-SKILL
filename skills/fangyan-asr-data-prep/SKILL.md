---
name: fangyan-asr-data-prep
description: '方言语音识别(ASR)训练数据构建与预处理。覆盖录音访谈(VAD边界检测)、电视台节目(SRT字幕切分+同步校正)、超长音频智能切片(ForcedAligner强制对齐)。包含短音频保护、SRT噪声清洗、音画同步校正、文本标准化、音频去重、分层数据集划分、质量控制。'
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
| `audio` | ✅ | 相对于数据集根目录的相对路径 |
| `text` | ✅ | 格式: `language <方言><asr_text>内容` |
| `duration` | ✅ | 秒，float |
| `speaker_id` | 推荐 | 用于说话人隔离划分 |
| `source` | 推荐 | 数据来源标识，如 `audio`、`douyin`、`guangdian`、`biaozhu`、`2025`。从目录名推断，用于分来源统计和质量跟踪。若目录重命名则需同步更新 manifest |
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
| **7. 数据集划分** | 说话人隔离+时长桶分层 90:5:5 | [质量控制](./references/06-quality-split.md) |
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

## 现有方言区处理脚本索引

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

---

## 设计原则

1. **无损原始数据**：`raw/` 不动，`预处理/` 副本处理
2. **可复现**：所有随机操作固定 seed，参数记日志
3. **最小修改**：优质音频不降噪/归一化
4. **尽早过滤**：超长/为空/损坏尽早排除；但短音频不是异常
5. **标记优先于删除**：异常打标签，按标签分层使用
6. **持续记录**：每步骤输出详细日志
