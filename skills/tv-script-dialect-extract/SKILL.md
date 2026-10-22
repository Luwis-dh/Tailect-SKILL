---
name: tv-script-dialect-extract
description: '电视台方言新闻节目按台本提取主持人语音。用演播室镜头检测做结构锚点，台本正文段与镜头块按序一一配对，SenseVoice 转写只用来精修边界和质检，最后按标点切成 3-10 秒片段并生成可试听打标的审阅网页。覆盖演播室镜头检测、台本段落分类、拼音DP强制对齐、局部对齐边界精修、标点切分、能量谷底吸附、退化保护、时长桶、JSONL manifest、审阅页。适用于栏目化节目：主持人只在演播室出镜说话，广告是贴片、采访路人都在新闻片里。'
argument-hint: '指定节目视频与串词台本，如 --video 2026.10.19.mp4 --docx 串词.docx --dialect Shaoxing；或指定步骤: detect(镜头检测) / transcribe(转写) / cut(配对切片) / split(切分) / review(审阅页)'
user-invocable: true
---

# 电视台节目「台本 → 主持人方言语音」提取

从一期节目里把**主持人说的方言**按台本切出来，文本直接取台本原文（而不是 ASR 结果），产出可直接训练的 JSONL。

## 何时使用

- 有**视频**，也有**串词台本**（docx/txt），台本内容是主持人的话
- 节目是栏目化的：主持人在**固定演播室**出镜，中间插新闻片/广告/采访
- 目标是方言 ASR 训练数据，需要"音频 + 精准文本"

不适用：没有台本（改用纯 ASR + 说话人分离）；主持人满场跑、没有固定机位；纯录音无画面。

## 先确认三件事（决定这条链路成不成立）

1. **主持人是否只在演播室说话？** 抽几帧看，口播时是不是同一个固定背景。
2. **台本正文段数 ≈ 演播室镜头块数？** 相等且顺序一致，才能一一配对。
3. **广告和采访在不在台本里？** 通常不在——这正是我们可以靠"画面"而不是"识别"来剔除它们的原因。

三条都成立就直接跑；任一条不成立，看 `references/02-troubleshooting.md`。

> 实测样例（绍兴台《师爷说新闻》26 分钟）：10 个演播室块 ↔ 台本 10 段正文，完全对应；另有 1 段台本在成片里被剪掉。

## 管线

```
视频 ──ffmpeg──> 16k 单声道 wav ──> SenseVoice 全片转写（带时间戳）
  └──1fps 缩略图──> 演播室镜头检测 ──> 10 个候选块
                                        │
台本 docx ──分类──> 正文段 ──按序配对──┘
                                        ▼
                     块 ±10s 窗口内拼音局部对齐 → 精修边界
                                        ▼
                        切片 + 能量裁静音 + manifest.jsonl
                                        ▼
                     按标点 + 字级时间切 3~10s → manifest_split.jsonl
                                        ▼
                                审阅网页（试听 + 打标）
```

## 快速开始

> 安装：把整个 `tv-script-dialect-extract/` 目录拷到 `%USERPROFILE%\.dsh\skills\` 下，新会话即可出现在技能目录。
> 所有命令都在**数据根目录**执行（manifest 里的 `audio` 是相对该目录的路径）。

```bash
cd <工作目录>
S=<skill目录>/scripts

# 1. 抽音频 + 找演播室镜头块（--ref-time 必须是纯演播室画面的时刻）
python $S/detect_studio.py --video 节目.mp4 --work work --ref-time 30

# 2. 全片转写（复用 DSH 自带 SenseVoice，不额外下模型）
python $S/transcribe_sensevoice.py --audio work/full16k.wav --out work/asr.json

# 3. 台本配对 + 精修 + 切片
python $S/align_and_cut.py --docx 串词.docx --work work --out 产出 --dialect Shaoxing

# 4. 超过 10s 的切成 3~10s
python $S/split_long.py --manifest 产出/manifest.jsonl --work work --out 产出

# 5. 审阅网页（打开就能听）
python $S/make_review.py --manifest 产出/manifest_split.jsonl --work work --out 产出/审阅
```

依赖：`ffmpeg`、`numpy`、`pypinyin`、`python-docx`、`Pillow`、`sherpa-onnx`。
`SenseVoice` 模型默认取 `~/.dsh/speech-to-text/sensevoice/models`，可用 `--model-dir` 覆盖。

## 参数速查

| 脚本 | 参数 | 默认 | 说明 |
|---|---|---|---|
| detect_studio | `--ref-time` | 30 | 参考帧秒数，**必须落在纯演播室画面上**，否则全错 |
| | `--threshold` | 25 | 像素差阈值。漏检→调大，误检→调小 |
| | `--min-run` | 3 | 最短镜头块，太短的口播会被吞掉 |
| align_and_cut | `--dialect` | Shaoxing | 写进 `language <X><asr_text>`，多期合并前必须大小写统一 |
| | `--window` | 10 | 镜头块两侧扩展秒数，用于找真实起止 |
| | `--pad` | 0.15 | 边界留白 |
| split_long | `--min/--max` | 4/10 | 目标片段时长区间 |

## 产出物

```
产出/
├── manifest.jsonl          # 整段版（10 条左右），对照用
├── manifest_split.jsonl    # 训练用（切分后），推荐
├── 时间轴.csv              # 台本原文 + ASR + 语速 + 质检分，Excel 可直接改
├── 对齐审阅.md             # 逐条对照
├── 主持人语音/             # 整段 wav
├── 主持人语音_切分/         # 训练用 wav
└── 审阅/切分审阅.html       # 试听 + 打标
```

JSONL 字段：`id / audio / text / duration / speaker_id / source / start / end / parent_id / duration_bucket / quality_flags`。

## 验收标准（不满足就是有问题）

| 检查 | 合格线 | 不符合说明什么 |
|---|---|---|
| 条数 | 台本正文段数 == 镜头块数 | 不等 → 有段落被剪掉，或镜头检测漏/多 |
| **语速** | **3.4~4.8 字/秒**，条间波动 < 1 | 偏离 → 配对错位或边界吃字，这是最灵敏的指标 |
| 时长桶 | 多数落 `medium_3_10s`，无 >20s | 全 `long_10s+` → 忘了跑 split_long |
| 质检分 | 多数 >0.15 | 个别低是方言重，**连续低**=对齐失败 |
| 总时长 | 约占全片 10~20% | 过高 → 把采访/广告切进来了 |

跑完先开审阅网页过一遍，重点看 `quality_flags` 带 `check` 的。

## 核心设计（为什么这样做）

- **画面定"在哪说"，台本定"说什么"，ASR 只做缝合**。方言 ASR 只有 60~75% 字准，当标注必废；但当"对齐用的模糊文本"完全够用。
- **不用说话人分离**：主持人有固定机位，广告/采访不在演播室，视觉比声纹稳得多。
- **对齐用拼音而不是字面**：方言写法和 ASR 输出字面差很远，但声母韵母接近。
- **无关字替换代价必须高于跳字代价**（1.60 > 1.0+0.35），否则 DP 会把广告里的字硬配给台本。
- **局部对齐（Smith-Waterman）而不是全局**：窗口里混着别人的话，要能自动跳过。
- **短音频不是异常**：2~3 秒的句尾保留，落 `short_1.5_3s` 桶即可。

细节见 `references/01-principles.md`。

## 常见坑（都踩过）

1. **参考帧选错** → 检出 0 个块，或检出的是新闻片。先 `--ref-time` 对着看一帧。
2. **台本标注不可信**：`（口播）`只是部分标注，没标的也可能是主持人。**按画面筛，不按标注筛**。
3. **台本有错字**（"天气"写成"天价"）：tag 会原样进训练集，跑完扫一遍。
4. **成片比台本少一段**（被剪）：必须做条数核对，别硬配对。
5. **比对窗口太宽**会把邻段吸进来；太窄会丢头尾。`--window 10` 起步。
6. **被污染的单段**（前后紧贴新闻片同期声）：字级对齐会退化，脚本会**整段保留 + 打 `check`**，不要强行切——硬切会出"多条互相重叠、文本对不上"的废数据。
7. **train/dev/test 划分要按 `parent_id` 会话隔离**，同一段口播切出的多条不能分到两边。

更多见 `references/02-troubleshooting.md`。

## 与其他技能的关系

- `fangyan-asr-data-prep`：管数据集的**组织与划分**（目录结构、时长桶分层、去重、train/dev/test、完整性检查）。本技能只负责**从视频生产出合格的片段和 manifest**，产出后按它那套规范落地即可。
- 本技能替代不了 VAD/SRT/ForcedAligner 分支：没有台本走 SRT/VAD，没有画面走纯音频。
