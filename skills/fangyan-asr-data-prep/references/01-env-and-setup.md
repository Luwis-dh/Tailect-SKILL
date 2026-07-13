# 环境与依赖配置

## 必装依赖

| 依赖 | 用途 | 安装命令 |
|------|------|----------|
| **FFmpeg** | 音频解码/转码 | `apt install ffmpeg` (Linux) / `winget install ffmpeg` (Win) |
| **Python 3.9+** | 脚本运行 | [python.org](https://python.org) |
| **PyTorch** | VAD 模型运行 | `pip install torch torchaudio` |
| **silero-vad** | 语音活动检测 | `pip install silero-vad` |
| **numpy** | 数据处理 | `pip install numpy` |
| **tqdm** | 进度条 | `pip install tqdm` |

## 选装依赖

| 依赖 | 用途 | 安装命令 |
|------|------|----------|
| **funasr + modelscope** | 中文标点恢复 | `pip install funasr modelscope` |
| **soundfile** | 音频解码 | `pip install soundfile` |
| **qwen-asr** | ForcedAligner 强制对齐 | `pip install qwen-asr` |

## Windows 专用设置

### OpenMP 冲突
```
OMP: Error #15: Initializing libiomp5md.dll, but found libiomp5md.dll already initialized.
```
**解决**：运行前设置环境变量：
```powershell
# PowerShell
$env:KMP_DUPLICATE_LIB_OK="TRUE"
python your_script.py

# CMD
set KMP_DUPLICATE_LIB_OK=TRUE
python your_script.py
```

### Linux 环境变量速查

以下环境变量在 Linux 容器/服务器中处理大规模数据时经常需要设置：

| 变量 | 症状 | 解决 |
|------|------|------|
| `OMP_NUM_THREADS` | `libgomp: Invalid value` | 显式设为 1：`export OMP_NUM_THREADS=1` |
| `TRANSFORMERS_NO_TF=1` | TensorFlow 与 numpy2 导入冲突 | 同时设 `USE_TF=0`，避免 tensorflow 被加载 |
| `KMP_DUPLICATE_LIB_OK=TRUE` | 多个 OpenMP 库冲突 | 在 Linux 下同样有效 |
| `HF_ENDPOINT` | HuggingFace 下载超时 | 国内镜像：`export HF_ENDPOINT=https://hf-mirror.com` |

推荐启动脚本模板（`setenv.sh`）：

```bash
#!/bin/bash
export OMP_NUM_THREADS=1
export TRANSFORMERS_NO_TF=1
export USE_TF=0
export KMP_DUPLICATE_LIB_OK=TRUE
export TF_ENABLE_ONEDNN_OPTS=0  # 关闭 oneDNN 日志

# 若需国内镜像
# export HF_ENDPOINT=https://hf-mirror.com

echo "环境变量已设置"
```

### PowerShell UTF-8 BOM 陷阱
`Set-Content` 默认带 BOM，导致 JSONL 解析异常。
```powershell
# 正确（无 BOM）
[System.IO.File]::WriteAllLines($file, $content, [System.Text.UTF8Encoding]::new($false))
```

### Docker 中文路径 I/O 错误
Docker for Windows bind mount 对中文长文件名可能返回 `Input/output error`。
**解决方案**（混合架构）：
1. 将中文名音频复制到扁平短名目录（如 `to_align/seq_00001.wav`）
2. Docker 容器仅做 GPU 推理，文件 I/O 在 Windows 侧完成
3. 最终切片在 Windows 侧处理

## 验证安装

```python
import torch, silero_vad, numpy as np
print("torch:", torch.__version__)
print("silero_vad:", silero_vad.__version__)
```

> **提示**：新版 `torchaudio` (2.11+) 强依赖 `torchcodec`。报错时降级 torchaudio 或使用 **ffmpeg pipe 解码** 替代方案。

---

## 步骤 1：音频格式统一

**目标**：将所有原始音频转为 ASR 标准格式。

### FFmpeg 转换
```bash
ffmpeg -y -i input.wav -ar 16000 -ac 1 -sample_fmt s16 output.wav
```

### 时长获取（生产级，支持 10 万+文件）

处理大批量音频时，`ffprobe` 的稳定性至关重要：

```python
import subprocess, time

def get_duration(file_path, timeout=10):
    """
    获取音频时长，带超时和错误处理。
    适用于批量处理 10 万+ 文件的生产环境。
    """
    cmd = ["ffprobe", "-v", "error",
           "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
    try:
        output = subprocess.check_output(
            cmd, text=True, encoding='utf-8',
            errors='replace', stderr=subprocess.PIPE,
            timeout=timeout
        )
        val = output.strip()
        return float(val) if val else 0.0
    except subprocess.TimeoutExpired:
        # ffprobe 在某些损坏文件上可能挂起
        return -1.0
    except (subprocess.CalledProcessError, ValueError, OSError):
        return 0.0
```

### 处理逻辑
1. 统一转为 16kHz/单声道/16-bit PCM WAV
2. 超长音频（>20秒）记录到 `超时文件.txt`，不入 manifest
3. 失败记录到 `处理异常日志.txt`

### 步骤 3：响度归一化（可选）
多源数据合并时响度差异大的场景使用：
```bash
ffmpeg -i input.wav -af loudnorm=I=-23:LRA=7:tp=-2 output.wav
```
低于 -23 LUFS 时归一化，高于则跳过。

---

## 大规模音频处理建议

当数据集规模超过 1 万条（尤其是 10 万+ 级别），以下策略可以大幅提升处理效率。

### 并行复制策略

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil, os
from pathlib import Path

def copy_audio_parallel(src_dst_pairs, workers=8):
    """并行复制音频文件到预处理目录。"""
    def _copy(pair):
        src, dst = pair
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return dst

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_copy, p): p for p in src_dst_pairs}
        ok, fail = 0, 0
        for f in as_completed(futures):
            try:
                f.result()
                ok += 1
            except Exception as e:
                fail += 1
        return ok, fail
```

### `-c copy` vs 重编码的选择

| 场景 | 策略 | 耗时/文件 |
|------|------|----------|
| 已是 16kHz/单声道/16-bit | `-c copy` 流复制，不做重采样 | ~0.1s |
| 采样率/声道/位深不匹配 | 完整重编码 `-ar 16000 -ac 1 -sample_fmt s16` | ~1-5s |
| 不确定格式 | 先 `ffprobe` 检查，按需选择 | — |

**实测数据**（仙居 103,961 条，8 线程）：
- 复制已合格音频 + 格式检查：~12 分钟
- 若全部重编码：预计 >2 小时

### 分块合并策略

处理 10 万+ 条数据时，不要一次性把所有条目写入一个 JSONL，可采用分块写入再合并：

```python
def write_chunked_manifest(entries, output_dir, chunk_size=10000):
    """分批写入 manifest，最后合并。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)
    chunks = []
    for i in range(0, len(entries), chunk_size):
        chunk_path = output_dir / f"manifest_chunk_{i//chunk_size:04d}.jsonl"
        with open(chunk_path, 'w', encoding='utf-8') as f:
            for e in entries[i:i + chunk_size]:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
        chunks.append(chunk_path)
    return chunks

def merge_manifests(chunk_paths, output_path):
    """合并分块 manifest。"""
    with open(output_path, 'w', encoding='utf-8') as out:
        for cp in chunk_paths:
            with open(cp, encoding='utf-8') as f:
                out.write(f.read())
```

### 磁盘 I/O 瓶颈识别

```bash
# 检查磁盘 I/O 是否成为瓶颈
iostat -x 1  # 查看 %util 和 await
# 如果 %util > 90% 或 await > 30ms，需要降低并行度
```

**经验法则**：
- HDD：workers ≤ 4
- SSD/NVMe：workers ≤ 16
- 网络存储（NFS）：workers ≤ 2，优先用 `-c copy`
