"""步骤 1：从视频里切出"演播室镜头"块，同时抽取 16k 单声道音频。

原理：演播室是整片唯一固定不动的画面（背景板/屏风）。取一帧参考，只比较左右两侧
（避开人物和右下角字幕条），与参考帧的平均像素差低于阈值即为演播室。

用法：
    python detect_studio.py --video 节目.mp4 --work work
    python detect_studio.py --video 节目.mp4 --work work --ref-time 30 --threshold 25

产出：
    work/full16k.wav        16k/单声道/16bit 音频
    work/fps1/              1fps 缩略图（160x90）
    work/studio_runs.json   [[起, 止], ...] 秒
"""
import argparse
import json
import os
import subprocess

import numpy as np
from PIL import Image


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_audio(video, wav):
    if os.path.exists(wav) and os.path.getsize(wav) > 1000:
        return
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", video,
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])


def ensure_frames(video, frames_dir, fps=1, w=160, h=90):
    os.makedirs(frames_dir, exist_ok=True)
    if os.listdir(frames_dir):
        return sorted(os.listdir(frames_dir))
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", video,
         "-vf", "fps=%d,scale=%d:%d" % (fps, w, h), os.path.join(frames_dir, "p_%05d.jpg")])
    return sorted(os.listdir(frames_dir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--work", default="work")
    ap.add_argument("--ref-time", type=float, default=30.0, help="参考帧时间(秒)，必须是纯演播室画面")
    ap.add_argument("--threshold", type=float, default=25.0, help="像素差阈值，越小越严")
    ap.add_argument("--min-run", type=int, default=3, help="最短镜头块(秒)")
    ap.add_argument("--max-gap", type=int, default=5, help="块内允许的断点(秒)，用于合并抖动")
    ap.add_argument("--ref-index", type=int, default=None, help="直接指定第几帧(0起)作为参考")
    args = ap.parse_args()

    os.makedirs(args.work, exist_ok=True)
    wav = os.path.join(args.work, "full16k.wav")
    ensure_audio(args.video, wav)
    frames_dir = os.path.join(args.work, "fps1")
    files = ensure_frames(args.video, frames_dir)

    idx = args.ref_index if args.ref_index is not None else int(args.ref_time)
    idx = max(0, min(idx, len(files) - 1))
    ref = np.asarray(Image.open(os.path.join(frames_dir, files[idx])).convert("RGB"), dtype=np.float32)
    H, W, _ = ref.shape

    # 只比较左右两侧竖条：演播室背景静止，人物在中间，右下角有字幕条
    mask = np.zeros((H, W), bool)
    mask[:, :int(W * 0.16)] = True
    mask[:, int(W * 0.84):] = True
    mask[:int(H * 0.15), :] = False
    mask[int(H * 0.85):, :] = False

    diffs = []
    for f in files:
        im = np.asarray(Image.open(os.path.join(frames_dir, f)).convert("RGB"), dtype=np.float32)
        diffs.append(float(np.abs(im - ref).mean(axis=2)[mask].mean()))
    diffs = np.array(diffs)

    hit = diffs < args.threshold
    runs, s = [], None
    for i, v in enumerate(hit):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s >= args.min_run:
                runs.append((s, i))
            s = None
    if s is not None and len(hit) - s >= args.min_run:
        runs.append((s, len(hit)))

    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= args.max_gap and (a - merged[-1][0]) < 90:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))

    out = os.path.join(args.work, "studio_runs.json")
    json.dump([[a, b] for a, b in merged], open(out, "w"))

    total = sum(b - a for a, b in merged)
    print("参考帧 t=%ds  阈值=%.1f  共 %d 帧" % (idx, args.threshold, len(files)))
    print("检出演播室块 %d 个，总时长 %.1fs" % (len(merged), total))
    for a, b in merged:
        print("  %7.1f - %7.1f  (%5.1fs)" % (a, b, b - a))
    if not merged:
        print("!! 一个都没检出：参考帧可能不是演播室画面，或阈值太严")
    print("-> " + out)


if __name__ == "__main__":
    main()
