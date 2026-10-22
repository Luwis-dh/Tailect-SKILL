"""步骤 3：台本段落 ↔ 演播室镜头按序配对，用局部对齐精修边界，切片并出 manifest。

配对依据：这类栏目"主持人只在演播室说话"，台本正文段数与演播室块数应当相等且顺序一致。
边界精修：在镜头块 ±window 秒内，用拼音局部对齐找出台本真正被念到的那一段，取首末字时间。

用法：
    python align_and_cut.py --docx 串词.docx --work work --out 产出 --dialect Shaoxing

产出：
    <out>/主持人语音/*.wav
    <out>/manifest.jsonl
    <out>/时间轴.csv
    <out>/对齐审阅.md
"""
import argparse
import csv
import json
import os
import re

import numpy as np

import common as C


def refine_bounds(text, segs, w0, w1, pad=0.15, rate=C.RATE):
    """在 [w0,w1] 里把整段台本对齐到 ASR 字，返回 (start, end, 对齐率) 或 None。"""
    chars, times = [], []
    for s in segs:
        if s["end"] <= w0 or s["start"] >= w1:
            continue
        t = C.normalize(s["text"])
        n = len(t)
        if not n:
            continue
        for k, ch in enumerate(t):
            chars.append(ch)
            times.append(s["start"] + (s["end"] - s["start"]) * (k + 0.5) / n)

    A = list(C.normalize(text))
    if not A or not chars:
        return None
    mapping, score, i0, i1 = C.local_align(A, chars, [C.py_code(c) for c in A], [C.py_code(c) for c in chars])
    pts = [times[j] for j in mapping if j >= 0]
    if len(pts) < 0.35 * len(A):
        return None

    start, end = max(0.0, min(pts) - pad), max(pts) + pad
    # 局部对齐会切掉噪声大的头尾，按语速补回（上限 2.5s），保证台本不丢字
    if i0 > 0:
        start = max(0.0, start - min(i0 / rate, 2.5))
    if i1 < len(A):
        end = end + min((len(A) - i1) / rate, 2.5)
    # 语速护栏：明显过长说明对齐跑偏，退回镜头块
    if end - start > len(A) / 3.0 + 3:
        return None
    return start, end, len(pts) / len(A)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docx", required=True)
    ap.add_argument("--work", default="work")
    ap.add_argument("--out", default="产出")
    ap.add_argument("--dialect", default="Shaoxing", help="方言前缀，写进 language <X><asr_text>")
    ap.add_argument("--source", default="", help="来源标识，默认取视频文件名")
    ap.add_argument("--window", type=float, default=10.0, help="镜头块两侧扩展秒数，用于精修")
    ap.add_argument("--pad", type=float, default=0.15)
    args = ap.parse_args()

    clip_dir = os.path.join(args.out, "主持人语音")
    os.makedirs(clip_dir, exist_ok=True)
    for f in os.listdir(clip_dir):
        if f.endswith(".wav"):
            os.remove(os.path.join(clip_dir, f))

    paras = [p for p in C.classify_paragraphs(args.docx) if p["kind"] == "speech"]
    blocks = json.load(open(os.path.join(args.work, "studio_runs.json")))
    segs = json.load(open(os.path.join(args.work, "asr.json"), encoding="utf-8"))
    audio = C.read_wav(os.path.join(args.work, "full16k.wav"))
    source = args.source or "节目"

    print("台本正文段 %d / 演播室块 %d" % (len(paras), len(blocks)))
    if len(paras) != len(blocks):
        print("!! 数量不一致：按顺序截断配对。多出的部分需人工处理：")
        for p in paras[len(blocks):]:
            print("   未配对台本:", p["text"][:50])
        for b in blocks[len(paras):]:
            print("   未配对镜头块:", b)

    n = min(len(paras), len(blocks))
    rows, entries = [], []
    for k in range(n):
        p, (bs, be) = paras[k], blocks[k]
        ref = refine_bounds(p["text"], segs, bs - args.window, be + args.window, pad=args.pad)
        if ref:
            start, end, ratio = ref
        else:
            start, end, ratio = bs, be, 0.0
            print("  [%02d] 对齐失败，退回镜头块边界 %.1f-%.1f" % (k + 1, bs, be))

        lo, hi = max(0, int(start * C.SR)), min(len(audio), int(end * C.SR))
        clip, ta, tb = C.trim(audio[lo:hi])
        start = start + ta
        end = start + (tb - ta)
        dur = len(clip) / float(C.SR)

        name = "host_%02d_%06.1f-%06.1f.wav" % (k + 1, start, end)
        C.write_wav(os.path.join(clip_dir, name), clip)

        asr_txt = "".join(s["text"] for s in segs if s["end"] > start and s["start"] < end)
        sim = C.bigram_sim(p["text"], asr_txt)
        flags = ["clean"] if sim >= 0.15 else ["check"]

        entries.append({
            "id": "host_%02d" % (k + 1),
            "audio": "%s/主持人语音/%s" % (os.path.basename(os.path.normpath(args.out)), name),
            "text": "language %s<asr_text>%s" % (args.dialect, p["text"]),
            "duration": round(dur, 3),
            "speaker_id": "spk_host",
            "source": source,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration_bucket": C.bucket(dur),
            "quality_flags": flags,
            "asr_sim": round(sim, 3),
        })
        rows.append({"序号": k + 1, "开始": round(start, 2), "结束": round(end, 2), "时长": round(dur, 2),
                     "台本字数": len(C.normalize(p["text"])),
                     "语速字秒": round(len(C.normalize(p["text"])) / max(dur, 0.1), 1),
                     "对齐率": round(ratio, 2), "质检分": round(sim, 3),
                     "音频": name, "台本": p["text"], "ASR": asr_txt})

    with open(os.path.join(args.out, "manifest.jsonl"), "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(os.path.join(args.out, "时间轴.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    md = ["# 主持人方言语音提取结果", "",
          "| # | 起止 | 时长 | 字数 | 语速 | 对齐率 | 质检分 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append("| %d | %s-%s | %.1fs | %d | %.1f | %.2f | %.2f |" % (
            r["序号"], C.fmt(r["开始"]), C.fmt(r["结束"]), r["时长"], r["台本字数"], r["语速字秒"], r["对齐率"], r["质检分"]))
    md.append("")
    for r in rows:
        md.append("## %d. [%s - %s] %.1fs" % (r["序号"], C.fmt(r["开始"]), C.fmt(r["结束"]), r["时长"]))
        md.append("- 台本：" + r["台本"])
        md.append("- ASR ：" + (r["ASR"] or "(空)"))
        md.append("")
    open(os.path.join(args.out, "对齐审阅.md"), "w", encoding="utf-8").write("\n".join(md))

    total = sum(e["duration"] for e in entries)
    print("切出 %d 条，总 %.1fs (%.1f 分钟)" % (len(entries), total, total / 60))
    for r in rows:
        print("  %2d  %s-%s  %5.1fs  %3d字  %4.1f字/秒  质检%.2f" % (
            r["序号"], C.fmt(r["开始"]), C.fmt(r["结束"]), r["时长"], r["台本字数"], r["语速字秒"], r["质检分"]))


if __name__ == "__main__":
    main()
