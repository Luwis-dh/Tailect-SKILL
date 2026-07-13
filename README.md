# Tailect-SKILL

方言 ASR 训练数据构建与预处理 — VS Code Agent Skills 仓库。

## 技能列表

| Skill | 描述 |
|-------|------|
| [fangyan-asr-data-prep](./skills/fangyan-asr-data-prep/SKILL.md) | 方言语音识别(ASR)训练数据构建与预处理管线 |

## 安装

在 VS Code 的 `.vscode/agents.json` 或 `copilot-instructions.md` 中引用此仓库中的 skill：

```json
{
  "skills": [
    {
      "name": "fangyan-asr-data-prep",
      "description": "方言语音识别(ASR)训练数据构建与预处理",
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
    └── fangyan-asr-data-prep/
        ├── SKILL.md
        └── references/
            ├── 00-annotation-formats.md   # 常见标注格式解析
            ├── 01-env-and-setup.md        # 环境配置
            ├── 02-vad-processing.md       # VAD 语音边界检测
            ├── 03-srt-processing.md       # SRT 字幕切分+同步校正
            ├── 04-forced-aligner.md       # ForcedAligner 强制对齐
            ├── 05-text-and-manifest.md    # 文本标准化与 Manifest 生成
            └── 06-quality-split.md        # 去重、划分与质量控制
```

## 方言 ASR 数据管线功能

- **录音访谈类**：VAD 语音边界检测 → 格式统一 → Manifest → 去重 → 划分
- **电视台节目类**：SRT 噪声清洗 → 音画同步校正 → 按时间戳切分 → Manifest → 去重 → 划分
- **超长音频**：ForcedAligner 强制对齐 → 标点定位切分 → 合并 → 重新划分
