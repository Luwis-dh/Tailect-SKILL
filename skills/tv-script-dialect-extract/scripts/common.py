"""共享工具：文本归一化、拼音代价、单调/局部 DP 对齐、音频 I/O。

依赖：numpy, pypinyin
"""
import re
import wave

import numpy as np
from pypinyin import lazy_pinyin

PUNCT = set("，。！？、；：\"'“”‘’《》（）()【】…—·,.!?;: \t\r\n　|~～-")
NUM_MAP = str.maketrans("０１２３４５６７８９", "0123456789")
SR = 16000
INITIALS = ["zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l",
            "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w"]
RATE = 4.2          # 绍兴话播报语速（字/秒），用于外推与护栏


def normalize(text):
    """去掉标点与空白，全角数字转半角。"""
    text = text.translate(NUM_MAP)
    return "".join(ch for ch in text if ch not in PUNCT)


def py_code(ch):
    """把汉字拆成 (声母, 韵母)，用于近似音匹配。"""
    if not ch:
        return ("", "")
    try:
        p = lazy_pinyin(ch)[0]
    except Exception:
        return (ch, "")
    if not p:
        return (ch, "")
    for ini in INITIALS:
        if p.startswith(ini):
            return (ini, p[len(ini):])
    return ("", p)


def sub_cost(a, b, ca, cb):
    """替换代价。无关字必须 > gap_a+gap_b，否则会乱配。"""
    if a == b:
        return 0.0
    ia, fa = ca
    ib, fb = cb
    if ia and ia == ib and fa and fa == fb:
        return 0.12
    if fa and fa == fb:
        return 0.30
    if ia and ia == ib:
        return 0.50
    return 1.60


def align(A, B, pyA, pyB, gap_a=1.0, gap_b=0.35):
    """全局带状 DP。A=台本字，B=ASR 字。返回 A 每字对应的 B 下标（-1 未对齐）。
    gap_a: 跳过台本字（贵，台本基本都会念）
    gap_b: 跳过 ASR 字（便宜，广告/采访本来就没有对应台本）
    """
    n, m = len(A), len(B)
    if n == 0 or m == 0:
        return [-1] * n
    INF = 1e9
    ratio = m / n
    band = max(200, int(0.12 * m))
    prev = [INF] * (m + 1)
    prev[0] = 0.0
    ptrs = []
    for i in range(1, n + 1):
        cur = [INF] * (m + 1)
        ptr = bytearray(m + 1)
        center = int(i * ratio)
        lo, hi = max(1, center - band), min(m, center + band)
        a, ca = A[i - 1], pyA[i - 1]
        for j in range(lo, hi + 1):
            s = prev[j - 1] + sub_cost(a, B[j - 1], ca, pyB[j - 1])
            u = prev[j] + gap_a
            l = cur[j - 1] + gap_b
            if s <= u and s <= l:
                cur[j], ptr[j] = s, 0
            elif u <= l:
                cur[j], ptr[j] = u, 1
            else:
                cur[j], ptr[j] = l, 2
        ptrs.append(ptr)
        prev = cur
    i, j = n, m
    mapping = [-1] * n
    while i > 0 and j > 0:
        t = ptrs[i - 1][j]
        if t == 0:
            mapping[i - 1] = j - 1
            i -= 1
            j -= 1
        elif t == 1:
            i -= 1
        else:
            j -= 1
    return mapping


def sim_score(a, b, ca, cb):
    if a == b:
        return 1.0
    ia, fa = ca
    ib, fb = cb
    if ia and ia == ib and fa and fa == fb:
        return 0.75
    if fa and fb and fa == fb:
        return 0.45
    if ia and ia == ib:
        return 0.25
    return -0.9


def local_align(A, B, pyA, pyB, gap=-1.0):
    """Smith-Waterman 局部对齐，返回 (mapping, score, i0, i1)。
    用于在窗口内找"台本真正被念到的那一段"，自动跳过前后混入的广告/采访。"""
    n, m = len(A), len(B)
    if n == 0 or m == 0:
        return [-1] * n, 0.0, 0, 0
    prev = [0.0] * (m + 1)
    ptrs = []
    best = (0.0, 0, 0)
    for i in range(1, n + 1):
        cur = [0.0] * (m + 1)
        ptr = bytearray(m + 1)
        a, ca = A[i - 1], pyA[i - 1]
        for j in range(1, m + 1):
            diag = prev[j - 1] + sim_score(a, B[j - 1], ca, pyB[j - 1])
            up = prev[j] + gap
            left = cur[j - 1] + gap
            v, t = diag, 0
            if up > v:
                v, t = up, 1
            if left > v:
                v, t = left, 2
            if v <= 0:
                v, t = 0.0, 3
            cur[j], ptr[j] = v, t
            if v > best[0]:
                best = (v, i, j)
        ptrs.append(ptr)
        prev = cur
    score, i, j = best
    mapping = [-1] * n
    i0 = i
    while i > 0 and j > 0:
        t = ptrs[i - 1][j]
        if t == 0:
            mapping[i - 1] = j - 1
            i -= 1
            j -= 1
            i0 = i
        elif t == 1:
            i -= 1
        elif t == 2:
            j -= 1
        else:
            break
    return mapping, score, i0, best[1]


# ---------------- 音频 ----------------

def read_wav(path, sr=16000):
    with wave.open(path, "rb") as f:
        assert f.getnchannels() == 1 and f.getframerate() == sr and f.getsampwidth() == 2, \
            "需要 16k/单声道/16bit wav: %s" % path
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).copy()


def write_wav(path, samples, sr=16000):
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(samples.tobytes())


def energy_frame(samples, sr=16000, win_ms=10):
    win = int(sr * win_ms / 1000)
    n = len(samples) // win
    if n == 0:
        return np.zeros(1)
    return np.abs(samples[:n * win].reshape(n, win)).mean(axis=1)


def trim(samples, sr=16000, thr_db=-38.0, pad=0.12):
    """按能量裁掉首尾静音，返回 (clip, 相对起点秒, 相对终点秒)。"""
    e = energy_frame(samples, sr)
    db = 20 * np.log10(e / 32768.0 + 1e-9)
    voiced = np.where(db > thr_db)[0]
    if len(voiced) == 0:
        return samples, 0.0, len(samples) / sr
    win = int(sr * 0.01)
    a = max(0, voiced[0] * win - int(pad * sr))
    b = min(len(samples), (voiced[-1] + 1) * win + int(pad * sr))
    return samples[a:b], a / sr, b / sr


def snap_to_dip(samples, t_abs, lo, hi, sr=16000, radius=0.3):
    """把切点吸附到 ±radius 内能量最低的帧，避免切在字中间。"""
    e = energy_frame(samples, sr)
    c = int(t_abs / 0.01)
    a = max(int(lo / 0.01), c - int(radius / 0.01), 1)
    b = min(int(hi / 0.01), c + int(radius / 0.01), len(e) - 1)
    if b <= a:
        return t_abs
    return (a + int(np.argmin(e[a:b]))) * 0.01


def bucket(d):
    if d < 1.5:
        return "word_0.3_1.5s"
    if d < 3:
        return "short_1.5_3s"
    if d < 10:
        return "medium_3_10s"
    return "long_10s+"


def fmt(t):
    return "%02d:%05.2f" % (int(t // 60), t % 60)


def bigram_sim(a, b):
    a, b = normalize(a), normalize(b)
    A = {a[i:i + 2] for i in range(len(a) - 1)}
    B = {b[i:i + 2] for i in range(len(b) - 1)}
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def split_clauses(text):
    """按标点断句，返回 [(句子, 是否句末强标点)]。"""
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in PUNCT:
            out.append((buf, ch in "。！？"))
            buf = ""
    if buf.strip():
        out.append((buf, True))
    return out


def classify_paragraphs(docx_path):
    """把串词 docx 拆成段落并分类：speech / title / meta / ad。"""
    import docx
    d = docx.Document(docx_path)
    out = []
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        if re.match(r"^广告\s*\d*\s*[:：]", t) or re.fullmatch(r"[0-9\s]+", t):
            kind = "ad"
        elif re.match(r"^记者", t):
            kind = "meta"
        elif ("《" in t and "》" in t and ("记者" in t or len(t) < 40)) or t.startswith("《"):
            kind = "title"
        else:
            kind = "speech"
        if kind == "speech":
            t = re.sub(r"^（口播）", "", t).strip()
        out.append({"kind": kind, "text": t})
    return out
