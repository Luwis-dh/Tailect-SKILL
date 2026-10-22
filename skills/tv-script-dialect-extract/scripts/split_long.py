"""步骤 4：把超长口播（>10s，尤其 >20s）按标点 + 字级时间切成 3~10s 训练片段。

依据：ASR 训练单条理想 3~10s；>20s 属于"超时文件"，必须切。
做法：字级对齐拿到每个字的时间 → 按台本标点断句 → 贪心合并到 4~10s（优先在句末断）
      → 边界吸附到 ±0.3s 能量谷底，避免切在字中间。

用法：
    python split_long.py --manifest 产出/manifest.jsonl --work work --out 产出

产出：
    <out>/主持人语音_切分/*.wav
    <out>/manifest_split.jsonl
    <out>/切分时间轴.csv
"""
import argparse
import csv
import json
import os
import re
from collections import Counter

import numpy as np

import common as C


def char_times(text, segs, w0, w1):
    """把台本每个字对齐到 ASR 字，返回 (chars, times, ok)。"""
    chars, atimes = [], []
    for s in segs:
        if s["end"] <= w0 or s["start"] >= w1:
            continue
        t = C.normalize(s["text"])
        n = len(t)
        if not n:
            continue
        for k, ch in enumerate(t):
            chars.append(ch)
            atimes.append(s["start"] + (s["end"] - s["start"]) * (k + 0.5) / n)

    A = list(C.normalize(text))
    if not A:
        return [], [], False
    mapping, score, i0, i1 = C.local_align(A, chars, [C.py_code(c) for c in A], [C.py_code(c) for c in chars])
    known = [(k, atimes[j]) for k, j in enumerate(mapping) if j >= 0]
    if len(known) < 0.35 * len(A):
        return A, [], False

    times = [None] * len(A)
    for k, t in known:
        times[k] = t
    ks = [k for k, _ in known]
    for k in range(len(A)):
        if times[k] is not None:
            continue
        prev = max([x for x in ks if x < k], default=None)
        nxt = min([x for x in ks if x > k], default=None)
        if prev is not None and nxt is not None:
            tp, tn = times[prev], times[nxt]
            times[k] = tp + (tn - tp) * (k - prev) / (nxt - prev)
        elif prev is not None:
            times[k] = times[prev] + (k - prev) / C.RATE
        elif nxt is not None:
            times[k] = times[nxt] - (nxt - k) / C.RATE
        else:
            times[k] = w0
    for k in range(1, len(A)):
        if times[k] < times[k - 1]:
            times[k] = times[k - 1] + 0.02
    return A, times, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="产出/manifest.jsonl")
    ap.add_argument("--work", default="work")
    ap.add_argument("--out", default="产出")
    ap.add_argument("--min", dest="min_dur", type=float, default=4.0)
    ap.add_argument("--max", dest="max_dur", type=float, default=10.0)
    ap.add_argument("--clip-dirname", default="主持人语音_切分")
    args = ap.parse_args()

    dst = os.path.join(args.out, args.clip_dirname)
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(dst):
        if f.endswith(".wav"):
            os.remove(os.path.join(dst, f))

    entries = [json.loads(l) for l in open(args.manifest, encoding="utf-8")]
    segs = json.load(open(os.path.join(args.work, "asr.json"), encoding="utf-8"))
    audio = C.read_wav(os.path.join(args.work, "full16k.wav"))

    new_entries, report, kept = [], [], []
    for e in entries:
        pid = e["id"]
        text = e["text"].split("<asr_text>", 1)[1]
        p_start, p_end = float(e["start"]), float(e["end"])

        A, times, ok = char_times(text, segs, p_start - 10, p_end + 10)
        span_ok = ok and len(times) > 1 and (times[-1] - times[0]) > 0.6 * (p_end - p_start)

        clauses = C.split_clauses(text)
        spans, pos = [], 0
        for ct, strong in clauses:
            n = len(C.normalize(ct))
            if n == 0:
                continue
            a, b = pos, min(pos + n, len(A))
            pos = b
            t0 = times[a] if span_ok and a < len(times) else p_start
            t1 = times[b - 1] if span_ok and b - 1 < len(times) else p_end
            spans.append({"text": ct, "t0": t0, "t1": t1, "strong": strong})

        if not spans or not span_ok:
            # 对齐退化（例如该片段被广告/新闻片污染）→ 整段保留，打 check
            spans = [{"text": text, "t0": p_start, "t1": p_end, "strong": True}]
            kept.append(pid)

        groups, cur = [], []
        for sp in spans:
            d = sp["t1"] - sp["t0"]
            cur_d = (cur[-1]["t1"] - cur[0]["t0"]) if cur else 0.0
            if cur and (cur_d + d > args.max_dur or (cur_d >= args.min_dur + 2 and sp["strong"])):
                groups.append(cur)
                cur = []
            cur.append(sp)
            if (cur[-1]["t1"] - cur[0]["t0"]) >= args.min_dur + 2 and sp["strong"]:
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)

        merged = []
        for g in groups:
            d = g[-1]["t1"] - g[0]["t0"]
            if merged and d < 2.5 and (merged[-1][-1]["t1"] - merged[-1][0]["t0"]) + d < args.max_dur:
                merged[-1].extend(g)
            else:
                merged.append(g)

        for gi, g in enumerate(merged):
            s = max(p_start, g[0]["t0"] - 0.12)
            t = min(p_end, g[-1]["t1"] + 0.12)
            if gi > 0:
                s = C.snap_to_dip(audio, s, p_start, t)
            if gi < len(merged) - 1:
                t = C.snap_to_dip(audio, t, s, min(p_end, t + 0.3))
            if t - s < 1.0:
                continue
            clip = audio[int(s * C.SR):int(t * C.SR)]
            body = re.sub(r"^[，。！？；：、]+", "", "".join(x["text"] for x in g)).strip()
            name = "%s_%02d_%06.1f-%06.1f.wav" % (pid, gi + 1, s, t)
            C.write_wav(os.path.join(dst, name), clip)
            dur = round(len(clip) / float(C.SR), 3)
            flags = list(e.get("quality_flags") or [])
            if pid in kept:
                flags = list(set(flags) | {"check"})
            new_entries.append({
                "id": "%s_%02d" % (pid, gi + 1),
                "audio": "%s/%s/%s" % (os.path.basename(os.path.normpath(args.out)), args.clip_dirname, name),
                "text": e["text"].split("<asr_text>")[0] + "<asr_text>" + body,
                "duration": dur,
                "speaker_id": e.get("speaker_id", "spk_host"),
                "source": e.get("source", ""),
                "start": round(s, 3),
                "end": round(t, 3),
                "parent_id": pid,
                "duration_bucket": C.bucket(dur),
                "quality_flags": flags,
            })
            report.append({"id": "%s_%02d" % (pid, gi + 1), "parent": pid, "start": round(s, 2),
                           "end": round(t, 2), "dur": dur, "chars": len(C.normalize(body)), "text": body})

    with open(os.path.join(args.out, "manifest_split.jsonl"), "w", encoding="utf-8") as f:
        for e in new_entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(os.path.join(args.out, "切分时间轴.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "parent", "start", "end", "dur", "chars", "text"])
        w.writeheader()
        w.writerows(report)

    ds = [e["duration"] for e in new_entries]
    print("切分后 %d 条，总 %.1fs，均 %.2fs，范围 %.2f~%.2fs" % (
        len(ds), sum(ds), sum(ds) / max(len(ds), 1), min(ds), max(ds)))
    c = Counter(e["duration_bucket"] for e in new_entries)
    for k in ["word_0.3_1.5s", "short_1.5_3s", "medium_3_10s", "long_10s+"]:
        print("  %-14s %2d 条" % (k, c.get(k, 0)))
    print("  >20s: %d 条" % sum(d > 20 for d in ds))
    if kept:
        print("  !! 字级对齐退化、整段保留（需人工复核）:", ", ".join(kept))
    for r in report:
        print("  %-12s %s-%s %5.2fs %3d字 %s" % (r["id"], C.fmt(r["start"]), C.fmt(r["end"]),
                                                  r["dur"], r["chars"], r["text"][:24]))


if __name__ == "__main__":
    main()
