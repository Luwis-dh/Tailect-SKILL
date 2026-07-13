# 数据去重、划分与质量控制（步骤 6、7、8、9）

---

## 步骤 6：数据去重策略

### 核心原则

**文本相同不代表样本重复**——同一文本由不同说话人/设备/环境录制，是宝贵的多样性数据。

### 去重规则

| 情况 | 处理方式 |
|------|----------|
| 音频 SHA256/MD5 完全一致 | **可去重** |
| 同一音频路径重复出现 | 合并或去重 |
| 文本相同但说话人不同 | **不应删除** |
| 文本相同但设备/环境不同 | **不应删除** |
| 同一说话人同一文本重复大量出现 | 可降采样（保留 5~20 条） |
| 文本相似度高（SimHash）长文本（>10字） | 标记复核 |
| **短文本（<5字）文本相似度高** | **不应用于去重** |
| 数据导出错误导致的重复记录 | 去重 |

### 音频级去重代码
```python
import hashlib, os

def sha256_hash(filepath, chunk_size=8192):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()

def dedup_by_audio_hash(entries):
    seen = set()
    unique, removed = [], []
    for entry in entries:
        audio_path = entry.get('audio', '')
        if os.path.exists(audio_path):
            h = sha256_hash(audio_path)
            if h not in seen:
                seen.add(h)
                unique.append(entry)
            else:
                removed.append(audio_path)
        else:
            removed.append(f"{audio_path} (文件不存在)")
    return unique, removed
```

---

## 步骤 7：数据集划分（Train/Dev/Test）

### 划分比例
推荐 `train:dev:test = 90:5:5` 或 `80:10:10`

### 核心规则
1. **优先说话人隔离**：同一说话人划入同一集合
2. 无说话人信息时按会话/文件隔离
3. **分层抽样**：按时长桶分层，确保各集合分布一致
4. **短句必须出现在 dev/test**，不应全部塞入训练集
5. 可构建专用评估子集：`dev_short`, `test_short`, `test_command`, `test_hotword`

### 时长分桶
```
超短: 0.3~1.5s（词汇级/命令词）
短:   1.5~3s（短语）
中:   3~10s（短句）
长:   10s+（长句/段落）
```

### 分层划分代码
```python
import random
from collections import defaultdict

def stratified_split(entries, train_ratio=0.90, dev_ratio=0.05,
                     test_ratio=0.05, seed=42,
                     speaker_key='speaker_id',
                     duration_key='duration'):
    random.seed(seed)

    # 按说话人分组（存在时）
    if speaker_key and speaker_key in entries[0]:
        speaker_groups = defaultdict(list)
        for e in entries:
            speaker_groups[e.get(speaker_key, 'unknown')].append(e)
        groups = list(speaker_groups.values())
        random.shuffle(groups)
        n_total = len(groups)
        n_train = int(n_total * train_ratio)
        n_dev = int(n_total * dev_ratio)
        train = [e for g in groups[:n_train] for e in g]
        dev = [e for g in groups[n_train:n_train + n_dev] for e in g]
        test = [e for g in groups[n_train + n_dev:] for e in g]
        return train, dev, test

    # 无说话人信息，按时长分桶分层
    buckets = [(0, 1.5), (1.5, 3.0), (3.0, 10.0), (10.0, float('inf'))]
    def get_bucket(dur):
        for lo, hi in buckets:
            if lo <= dur < hi:
                return f"{lo}-{hi}"
        return f"{buckets[-1][0]}+"

    bucket_entries = defaultdict(list)
    for e in entries:
        dur = float(e.get(duration_key, 0)) if isinstance(e.get(duration_key), (int, float)) \
              else float(str(e.get(duration_key, '0')).rstrip('s'))
        bucket_entries[get_bucket(dur)].append(e)

    train, dev, test = [], [], []
    for bucket, bucket_list in bucket_entries.items():
        random.shuffle(bucket_list)
        n = len(bucket_list)
        train.extend(bucket_list[:int(n * train_ratio)])
        dev.extend(bucket_list[int(n * train_ratio):int(n * (train_ratio + dev_ratio))])
        test.extend(bucket_list[int(n * (train_ratio + dev_ratio)):])

    random.shuffle(train)
    random.shuffle(dev)
    random.shuffle(test)
    return train, dev, test
```

### 构建专用评估子集
```python
def build_eval_subsets(all_entries):
    subsets = {}
    short_entries = [e for e in all_entries if float(e.get('duration', 0)) < 1.5]
    command_entries = [e for e in all_entries if e.get('utterance_type') == 'command']
    if short_entries:
        subsets['test_short'] = random.sample(short_entries, min(200, len(short_entries)))
    if command_entries:
        subsets['test_command'] = random.sample(command_entries, min(200, len(command_entries)))
    return subsets
```

### 划分后路径一致性验证
```python
def verify_all_splits(split_dir, prefix="language "):
    for fn in ["manifest.jsonl", "train.jsonl", "dev.jsonl", "test.jsonl"]:
        fp = Path(split_dir) / fn
        if not fp.exists():
            print(f"⚠ 文件不存在: {fn}")
            continue
        entries = [json.loads(l) for l in open(fp, encoding='utf-8') if l.strip()]
        missing = [e for e in entries if not os.path.exists(e.get("audio", ""))]
        bad_text = [e for e in entries if not e.get("text", "").startswith(prefix)]
        print(f"{fn}: {len(entries)} 条" +
              (f" | ⚠ {len(missing)} 路径缺失" if missing else " | ✓ 路径全部存在") +
              (f" | ⚠ {len(bad_text)} text 前缀异常" if bad_text else " | ✓ text 格式正确"))
```

---

## 步骤 8：质量控制

### 全流程自动检查项

| 检查项 | 检测方法 | 处置 |
|--------|----------|------|
| 音频文件损坏 | `wave.open()` / `ffprobe` | 移除并记录 |
| 音频为空/0字节 | `os.path.getsize()` | 移除 |
| 文本为空 | 字符串判空 | 移除 |
| 时长 >20秒 | 时长检测 | 移入 `超时文件.txt` |
| 音频 Clipping | 检测峰值幅度 | 标记 `clipped` |
| 背景噪声过高 | VAD 非语音段 SNR | 标记 `noisy` / `very_noisy` |
| SRT 切片静音过多 | VAD 检测切片首尾 10% | >30% → 标记 |
| 切片时长异常 | 实际 vs SRT 标注 | 比值 <0.5 或 >1.5 → 标记 |
| 相邻切片异常间隙 | 计算前后差值 | >3s 或 <0 → 标记 |
| 文本-时长比例失调 | 字数/时长比 | <0.05 或 >0.5 → 标记 |

### 质量控制原则
优先**打标签**而非直接删除：
```python
import re

def strip_text_prefix(text):
    return re.sub(r'^language \w+<asr_text>', '', text)

def tag_quality(entry):
    flags = []
    duration = float(entry.get('duration', 0))
    text = strip_text_prefix(entry.get('text', ''))

    if duration < 0.3:
        flags.append('too_short')
    elif duration < 1.5:
        flags.append('short_utterance')
    if not text.strip():
        flags.append('empty_text')

    snr = entry.get('snr')
    if snr is not None:
        if snr < 5:
            flags.append('very_noisy')
        elif snr < 15:
            flags.append('noisy')
        else:
            flags.append('clean')

    entry['quality_flags'] = flags
    return entry
```

### 8.7 SRT 文本人工审查

自动筛查脚本：
```python
def audit_srt(srt_dir: Path) -> list[dict]:
    issues = []
    for srt_path in sorted(srt_dir.glob("*_cleaned.srt*")):
        content = srt_path.read_text(encoding="utf-8-sig")
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "-->" in line or line.isdigit():
                continue
            problems = []
            if re.match(r'^[A-Za-z0-9\s]{2,}$', line):
                problems.append("纯英文/数字")
            if len(line) <= 1:
                problems.append("单字符")
            if re.search(r'\S\s{2,}\S', line):
                problems.append("不规范空格")
            if problems:
                issues.append({"file": srt_path.name, "line": i+1,
                               "text": line[:60], "problems": "; ".join(problems)})
    return issues
```

---

## 自动化质量验证清单（可脚本化）

每次 Pipeline 运行后应自动执行以下检查，而不是留到人工审查阶段。

### 验证函数模板

```python
import json, os
from pathlib import Path

def validate_dataset(manifest_path, data_root, dialect="Xianju"):
    """
    全自动数据集质量验证。
    
    Args:
        manifest_path: manifest.jsonl 路径
        data_root: 音频基准目录
        dialect: 方言前缀，用于检查 text 格式
    
    Returns:
        dict: 各项检查结果
    """
    results = {}
    errors = []
    
    # 1. JSONL 可解析性
    entries = []
    with open(manifest_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                errors.append(f"JSONL parse error: {e}")
    results['total_entries'] = len(entries)
    results['parse_errors'] = len(errors)
    
    # 2. 方言前缀
    prefix = f"language {dialect}<asr_text>"
    bad_text = [e for e in entries if not e.get('text', '').startswith(prefix)]
    results['bad_prefix'] = len(bad_text)
    
    # 3. 必填字段
    missing_fields = [e for e in entries 
                      if not all(k in e for k in ('audio', 'text', 'duration'))]
    results['missing_fields'] = len(missing_fields)
    
    # 4. 时长范围
    durations = [e['duration'] for e in entries]
    results['duration_min'] = min(durations)
    results['duration_max'] = max(durations)
    results['over_20s'] = sum(1 for d in durations if d > 20)
    results['under_0.3s'] = sum(1 for d in durations if d < 0.3)
    
    # 5. 音频文件存在性
    missing_audio = []
    for e in entries:
        ap = Path(data_root) / e['audio']
        if not ap.exists():
            missing_audio.append(e['id'])
    results['missing_audio'] = len(missing_audio)
    
    # 6. 音频路径去重
    audio_paths = [e['audio'] for e in entries]
    results['dup_audio'] = len(audio_paths) - len(set(audio_paths))
    
    # 7. 空文本
    empty_text = [e for e in entries if not e.get('text', '').strip()
                  or e['text'].strip() == f"language {dialect}<asr_text>"]
    results['empty_text'] = len(empty_text)
    
    # 8. 划分比例（如果 train/dev/test 存在）
    split_dir = Path(manifest_path).parent
    for split_name in ['train', 'dev', 'test']:
        split_path = split_dir / f"{split_name}.jsonl"
        if split_path.exists():
            split_entries = [json.loads(l) for l in open(split_path, encoding='utf-8') if l.strip()]
            split_dur = sum(e['duration'] for e in split_entries)
            results[f'{split_name}_count'] = len(split_entries)
            results[f'{split_name}_hours'] = round(split_dur / 3600, 2)
    
    return results

def print_validation_report(results):
    """打印验证报告，标注异常项。"""
    print("=" * 50)
    print("数据集质量验证报告")
    print("=" * 50)
    
    checks = [
        ("JSONL 完整性", results['parse_errors'], 0, "数"),
        ("方言前缀异常", results['bad_prefix'], 0, "条"),
        ("缺失必填字段", results['missing_fields'], 0, "条"),
        ("音频路径重复", results['dup_audio'], 0, "条"),
        ("空文本", results['empty_text'], 0, "条"),
        ("音频文件缺失", results['missing_audio'], 0, "个"),
        (">20s 超长", results.get('over_20s', 0), 0, "条"),
        ("<0.3s 过短", results.get('under_0.3s', 0), 0, "条"),
    ]
    
    all_pass = True
    for name, val, expected, unit in checks:
        status = "✓" if val == expected else "✗"
        if val != expected:
            all_pass = False
        print(f"  {status} {name}: {val}{unit}")
    
    print(f"\n总条目: {results['total_entries']}")
    print(f"时长范围: {results['duration_min']:.2f}s ~ {results['duration_max']:.2f}s")
    
    if 'train_count' in results:
        total = results['train_count'] + results['dev_count'] + results['test_count']
        print(f"\n划分: train={results['train_count']} ({results['train_hours']}h) "
              f"dev={results['dev_count']} ({results['dev_hours']}h) "
              f"test={results['test_count']} ({results['test_hours']}h)")
        if total > 0:
            print(f"  比例: {results['train_count']/total*100:.1f}/"
                  f"{results['dev_count']/total*100:.1f}/"
                  f"{results['test_count']/total*100:.1f}")
    
    print(f"\n总体: {'✓ 全部通过' if all_pass else '✗ 存在异常，请检查'}")
    return all_pass

# 使用
# report = validate_dataset("预处理/manifest.jsonl", "/root/dataset", dialect="Xianju")
# print_validation_report(report)
```

### 检查项速查表

| 检查项 | 脚本化方法 | 通过标准 |
|--------|-----------|----------|
| JSONL 可解析 | `all(json.loads(l) for l in f)` | 100% |
| 方言前缀 | `t.startswith('language {dialect}<asr_text>')` | 100% |
| 时长范围 | 检查 `duration` 字段 | 0.3s ~ 20s |
| 音频文件存在 | `os.path.exists(audio)` | 100% |
| 音频路径去重 | `len(paths) == len(set(paths))` | 0 重复 |
| 划分比例 | train/dev/test 计数 | ~90/5/5 |
| 空文本 | `text.strip()` 判空 | 0 条 |
| 缺失/损坏 | `ffprobe` 逐条检查 | 0 条 |

> **建议**：将上述验证函数加入每次 Pipeline 运行的尾部，与 `总体数据详细报告.txt` 一起输出。任何偏离通过标准的异常都应自动触发警告。

---

## 步骤 9：日志与产物管理

### 日志配置
```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('处理日志.txt', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('asr_prep')
```

### 产物目录结构
```
预处理/
├── manifest.jsonl         # 全量清单
├── train.jsonl            # 训练集
├── dev.jsonl              # 验证集
├── test.jsonl             # 测试集
├── 存档_中间文件/          # 中间产物归档
│   ├── 种田垟原始清单_manifest_zty.jsonl
│   ├── train.bak_无标点.jsonl
│   └── ...
├── <音频切片目录>/
├── 超时文件.txt
├── 处理异常日志.txt
└── 总体数据详细报告.txt
```

### 统计报告模板
```python
def generate_report(train, dev, test):
    durations = {
        'train': sum(e.get('duration', 0) for e in train),
        'dev':   sum(e.get('duration', 0) for e in dev),
        'test':  sum(e.get('duration', 0) for e in test),
    }
    report = f"""=== 总体数据报告 ===
训练集: {len(train)} 条, {durations['train']:.1f}秒
验证集: {len(dev)} 条, {durations['dev']:.1f}秒
测试集: {len(test)} 条, {durations['test']:.1f}秒
总计: {len(train)+len(dev)+len(test)} 条,
      {durations['train']+durations['dev']+durations['test']:.1f}秒
"""
    return report
```

---

## 训练采样建议

### 通用 ASR 任务
| 时长分桶 | 采样权重 | 说明 |
|----------|---------|------|
| 长句/常规句（3s+） | 70% ~ 90% | 主体数据 |
| 短词/短句（<3s） | 10% ~ 30% | 保证短词识别 |

### 命令词/关键词识别
- 短词/命令词为主体
- **必须加入负样本**（相似词、背景噪声、非命令语音）

### 热词/实体词增强
- 短实体音频保留，训练时过采样（重复 2~5 倍）
- 验证集单独构建 `hotword_eval` 子集

### 动态采样示例
```python
def sample_by_bucket(entries, bucket_weights, epoch_size, seed=42):
    random.seed(seed)
    buckets = defaultdict(list)
    for e in entries:
        buckets[e.get('duration_bucket', 'unknown')].append(e)
    sampled = []
    for bucket, weight in bucket_weights.items():
        pool = buckets.get(bucket, [])
        n = int(epoch_size * weight)
        sampled.extend(random.choices(pool, k=min(n, len(pool) * 10)))
    random.shuffle(sampled)
    return sampled[:epoch_size]

# 通用 ASR 采样
epoch_sample = sample_by_bucket(all_entries, {
    'word_0.3_1.5s': 0.10,
    'short_1.5_3s': 0.15,
    'medium_3_10s': 0.50,
    'long_10s+': 0.25,
}, epoch_size=10000)
```

---

## 短音频与词汇级样本处理策略

### 基本立场
**短音频不是默认异常。** 完整、清晰、标注准确的词汇级短音频应保留。

### 短音频决策表
| 条件 | 处理方式 |
|------|----------|
| 音频完整清晰，0.3~1.5 秒 | **保留** |
| 命令词、热词、实体词、人名、地名 | **强烈建议保留** |
| 时长 <0.15 秒 | 丢弃或复核 |
| 文本相同但说话人/设备不同 | **保留**（多样性） |
| 同一说话人同一文本重复上千条 | 降采样 |
| 噪声严重但可辨认 | 标记 `noisy` |
| 标注和音频不一致 | 丢弃或重标 |

### 短音频处理流程
1. 时长检测，标记 `duration_bucket`
2. 对 `word_0.3_1.5s` 桶：VAD 保守参数（低阈值、大 padding）
3. 质量打标 `quality_flags`
4. 仅丢弃明显异常（截断、无语音、标注错误）
5. 分层划分：各时长桶按比例进入 train/dev/test
