# Tailect-SKILL

方言 ASR 训练数据构建与预处理 — VS Code Agent Skills 仓库。

## 技能列表

| Skill | 描述 |
|-------|------|
| [fangyan-asr-data-prep](./skills/fangyan-asr-data-prep/SKILL.md) | 方言语音识别(ASR)训练数据构建与预处理管线 |
| [tv-script-dialect-extract](./skills/tv-script-dialect-extract/SKILL.md) | 电视台方言节目按台本提取主持人语音（演播室镜头锚点 + 强制对齐 + 切片 + 审阅页） |

## 安装

在 VS Code 的 `.vscode/agents.json` 或 `copilot-instructions.md` 中引用此仓库中的 skill：

```json
{
  "skills": [
    {
      "name": "fangyan-asr-data-prep",
      "description": "方言语音识别(ASR)训练数据构建与预处理",
      "url": "https://github.com/Luwis-dh/Tailect-SKILL"
    },
    {
      "name": "tv-script-dialect-extract",
      "description": "电视台方言节目按台本提取主持人语音",
      "url": "https://github.com/Luwis-dh/Tailect-SKILL"
    }
  ]
}
```

## 目录结构

```
Tailect-SKILL/
├── README.md
└── skills/
    ├── fangyan-asr-data-prep/
    │   ├── SKILL.md
    │   └── references/
    │       ├── 00-annotation-formats.md   # 常见标注格式解析
    │       ├── 01-env-and-setup.md        # 环境配置
    │       ├── 02-vad-processing.md       # VAD 语音边界检测
    │       ├── 03-srt-processing.md       # SRT 字幕切分+同步校正
    │       ├── 04-forced-aligner.md       # ForcedAligner 强制对齐
    │       ├── 05-text-and-manifest.md    # 文本标准化与 Manifest 生成
    │       └── 06-quality-split.md        # 去重、划分与质量控制
    └── tv-script-dialect-extract/
        ├── SKILL.md
        ├── references/
        │   ├── 01-principles.md           # 画面锚点原理、对齐代价表、切分策略
        │   └── 02-troubleshooting.md      # 症状排错、环境问题、验收流程
        └── scripts/
            ├── common.py                  # 拼音代价、DP/局部对齐、音频工具
            ├── detect_studio.py           # ① 视频 → 演播室镜头块 + 16k 音频
            ├── transcribe_sensevoice.py   # ② SenseVoice + Silero VAD 全片转写
            ├── align_and_cut.py           # ③ 台本配对 + 边界精修 + 切片
            ├── split_long.py              # ④ 按标点切成 3~10s
            └── make_review.py             # ⑤ 生成试听打标审阅网页
```

## 方言 ASR 数据管线功能

### 核心处理流程
- **录音访谈类**：VAD 语音边界检测 → 格式统一 → Manifest → 去重 → 划分
- **电视台节目类**：SRT 噪声清洗 → 音画同步校正 → 按时间戳切分 → Manifest → 去重 → 划分
- **超长音频**：ForcedAligner 强制对齐 → 标点定位切分 → 合并 → 重新划分

### 进阶功能 (V2 新增)
- **会话隔离划分**：以 session hash 目录为原子单位，一通电话的所有 WAV 划入同一 split
- **异构数据源分层**：独立条目 + 会话数据 + 追加测试集，三源分别处理再合并
- **时长桶分层抽样**：dev/test 与训练集保持 word/short/medium/long 比例一致
- **批量补全 duration**：32 线程并行 ffprobe 扫描，12 万文件约 5~10 分钟
- **路径迁移修复**：目录重组后批量替换 JSONL 路径，全量 `os.path.exists()` 验证
- **方言前缀归一化**：自动检测并统一 `XianJu` → `Xianju` 等大小写不一致
- **完整性自动检查**：全量扫描音频存在性、格式合规、duration 完整、路径分隔符
- **测试集追加模式**：稀有方言全部追加到 test，不参与均匀分配

## 电视台节目按台本提取主持人口播

针对「有视频 + 有串词台本」的栏目化方言新闻节目：主持人只在演播室出镜，广告是贴片、采访路人都在新闻片里。

**核心思路**：画面定"在哪说"，台本定"说什么"，ASR 只做缝合。方言 ASR 只有 60~75% 字准，当标注不可用；但作为强制对齐的模糊文本完全够用。

### 五步管线

```
视频 ──ffmpeg──> 16k 单声道 wav ──> SenseVoice 全片转写
  └──1fps 缩略图──> 演播室镜头检测 ──> 候选块
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

### 关键能力
- **演播室镜头检测**：比较画面左右两侧与参考帧的像素差，全片唯一静止的背景即为演播室，10/10 精确率，±1 秒
- **台本段落分类**：正文 / 片名 / 记者署名 / 广告位四类自动分离
- **拼音 DP 强制对齐**：无关字代价（1.60）高于跳字代价之和（1.35），防止把广告里的字硬配给台本
- **局部对齐（Smith-Waterman）**：窗口内自动跳过混入的采访同期声
- **语速护栏**：3.4~4.8 字/秒，超出即判对齐失败并退回镜头块边界
- **退化保护**：被同期声污染的片段整段保留并打 `check`，绝不硬切出重叠废数据
- **审阅网页**：上下文波形 + 绿色高亮切段 + 试听 + 一键打标 + 导出

### 实测数据（绍兴台《师爷说新闻》26 分钟）
- 10 个演播室块 ↔ 台本 10 段正文，完全对应
- 切出 10 条 / 202.9 秒，语速 3.5~4.6 字/秒
- 再切分为 26 条训练片段，22 条落 `medium_3_10s`，无 >20s
- SenseVoice int8 ONNX 在 CPU 上 26 分钟音频约 2 分钟转完（13.6× 实时）
