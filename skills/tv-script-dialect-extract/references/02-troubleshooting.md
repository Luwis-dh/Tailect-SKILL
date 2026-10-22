# 排错与验收

## 症状 → 原因 → 处理

| 症状 | 最可能原因 | 处理 |
|---|---|---|
| 检出 0 个演播室块 | 参考帧不是演播室画面 | 打开 `work/fps1/p_000NN.jpg` 挑一帧纯演播室，用 `--ref-idx` 或 `--ref-time` 指定 |
| 块数 > 台本段数 | 阈值太松 / 片头片尾静态画面 | 降 `--threshold` 到 20 或 15；把过短的块剔除 |
| 块数 < 台本段数 | 有机位角度不同被漏 | 换参考帧重跑，或人工补一条到 `studio_runs.json` |
| 所有条目语速 < 3 字/秒 | 切太宽（把静音/别人说话带进来了） | 检查 `--window` 是否过大；看该条质检分 |
| 某条语速 > 6 字/秒 | 切太窄，吃字了 | 该条多半是"退化保护"退回块边界，或局部对齐把头部切掉 |
| 质检分连续为 0.0x | 台本与音频不匹配（配对错位） | 核对条数与顺序；看了 `对齐审阅.md` 里的 ASR 列 |
| 切分后多条时间重叠 | 字级对齐退化后仍强行切 | 脚本应有退化保护（整段保留 + `check`），检查 `span_ok` 分支 |
| 审阅页没声音 | `file://` 对音频的限制 | 在产出目录 `python -m http.server 8800`，用 `http://127.0.0.1:8800/...` 打开 |
| 审阅页空白 | JS 语法错误/数据没嵌进去 | `node --check` 抽出 `<script>` 内容自检 |

## 环境问题（Windows + DSH 沙箱）

### pip 装包报 `Permission denied: ...\pip-unpack-xxx\*.whl`

沙箱下 pip 往临时目录写 wheel 会失败（下载完成了，落盘被拒）。绕开办法：手动下 wheel 再解压。

```python
# 从国内镜像拿 wheel（pypi.org 常常 SSL 失败，清华源稳定）
import urllib.request, re, urllib.parse, zipfile, os
name = "sherpa-onnx"
base = "https://pypi.tuna.tsinghua.edu.cn/simple/%s/" % name
page = urllib.request.urlopen(base, timeout=20).read().decode()
links = [(html_name, urllib.parse.urljoin(base, h)) for h in re.findall(r'href="([^"#]+)', page)]
# 挑 cp313-win_amd64 或 py3-none-any 的 wheel，下载后 zipfile.extractall(目标目录)
```

然后把目标目录塞进 `PYTHONPATH` 即可（不需要 `pip install`）。

### 模型缓存在沙箱外

`~/.cache/modelscope`、`~/.cache/huggingface` 通常不可写。要么把缓存变量指到工作目录（`MODELSCOPE_CACHE`），要么直接用 DSH 自带的 `~/.dsh/speech-to-text/...`（只读即可）。

### torch 是 CPU 版

`torch.__version__` 带 `+cpu` 时，GPU 用不上。SenseVoice int8 ONNX 在 CPU 上已经很快（26 分钟音频约 2 分钟），不必换。

## 验收流程（5 分钟）

1. **条数**：`台本正文段数 == 镜头块数`，不等就别往下走。
2. **语速**：看 `时间轴.csv` 的「语速字秒」列，应落在 3.4~4.8，条间波动 < 1。
3. **时长桶**：`manifest_split.jsonl` 里 `>20s` 必须为 0，`medium_3_10s` 应占多数。
4. **总时长**：约为全片的 10~20%。过高说明把采访切进来了。
5. **审阅页**：过一遍 `quality_flags` 含 `check` 的，重点听切点前后。

## 交付前的格式检查

```python
import json, wave, os
rows = [json.loads(l) for l in open("产出/manifest_split.jsonl", encoding="utf-8")]
for r in rows:
    assert os.path.exists(r["audio"]), r["id"]
    with wave.open(r["audio"]) as f:
        assert f.getframerate() == 16000 and f.getnchannels() == 1
        assert abs(f.getnframes() / f.getframerate() - r["duration"]) < 0.05
    assert r["text"].startswith("language "), r["id"]
    assert "<asr_text>" in r["text"], r["id"]
```

再按 `fangyan-asr-data-prep` 的规范落地目录、做去重和 train/dev/test（**按 `parent_id` 会话隔离**）。
