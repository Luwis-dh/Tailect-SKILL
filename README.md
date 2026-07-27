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
