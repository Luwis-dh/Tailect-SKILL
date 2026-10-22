"""步骤 5：生成切分审阅网页（单文件，无外部依赖）。

每条给：上下文波形（切点前后各 pad 秒，绿色高亮=实际切出的区间）+ 两个播放键
（只听片段 / 带上下文）+ 一键打标，状态存浏览器 localStorage，可导出。

用法：
    python make_review.py --manifest 产出/manifest_split.jsonl --work work --out 产出/审阅

产出：
    <out>/切分审阅.html
    <out>/ctx/<id>.wav
"""
import argparse
import json
import os

import numpy as np

import common as C

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f6f7f8;color:#1d2329;padding:0 0 80px}
header{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #e3e6e8;padding:14px 22px}
h1{font-size:17px;font-weight:650}
.sub{color:#6b7680;font-size:12.5px;margin-top:2px}
.bar{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
button{font:inherit;border:1px solid #d7dce0;background:#fff;border-radius:7px;padding:5px 11px;cursor:pointer;color:#2b333a}
button:hover{border-color:#9fb0bb;background:#fafbfc}
button.on{background:#2f7f5f;border-color:#2f7f5f;color:#fff}
button.play{background:#2f7f5f;border-color:#2f7f5f;color:#fff;min-width:74px}
button.play.ghost{background:#fff;color:#2f7f5f}
.stat{color:#6b7680;font-size:12.5px;margin-left:auto}
.stat b{color:#1d2329}
main{max-width:940px;margin:0 auto;padding:18px 16px}
.card{background:#fff;border:1px solid #e3e6e8;border-radius:10px;padding:14px 16px;margin-bottom:12px}
.card.focus{border-color:#2f7f5f;box-shadow:0 0 0 3px rgba(47,127,95,.10)}
.card.pass{border-left:4px solid #2f7f5f}
.card.fail{border-left:4px solid #d9534f;background:#fffafa}
.card.hidden{display:none}
.row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.id{font-weight:650;font-size:13.5px;color:#2f7f5f}
.meta{color:#7b858e;font-size:12.5px}
.badge{font-size:11.5px;padding:1px 7px;border-radius:20px;background:#eef3f1;color:#3c6b58}
.badge.warn{background:#fdecea;color:#b03a35}
.badge.long{background:#fff3e0;color:#a86412}
.badge.short{background:#eef1fa;color:#42508f}
.wavebox{margin:9px 0 7px;border:1px solid #eef1f2;border-radius:7px;overflow:hidden;background:#fcfdfd}
.wave{width:100%;height:78px;display:block}
.cut{stroke:#2f7f5f;stroke-width:1.5;stroke-dasharray:3 3;opacity:.75}
.text{font-size:13.5px;color:#39424a;background:#fbfcfc;border:1px solid #eef1f2;border-radius:7px;padding:8px 10px;margin-top:8px}
.acts{display:flex;gap:7px;margin-top:10px;flex-wrap:wrap}
.tip{color:#8b959d;font-size:12px;margin-top:6px}
kbd{background:#eef1f2;border-radius:4px;padding:1px 5px;font-size:11.5px;font-family:inherit}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%) translateY(80px);background:#2b333a;color:#fff;padding:11px 16px;border-radius:9px;font-size:13px;opacity:0;transition:.25s;max-width:680px}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
#toast code{background:#414b54;padding:1px 5px;border-radius:4px}
"""

JS = """
const DATA = __DATA__;
const KEY = 'review_split_v1';
const LS = (()=>{ try{ localStorage.setItem('__t','1'); localStorage.removeItem('__t'); return localStorage; }
                  catch(e){ return {getItem:()=>null, setItem:()=>{}}; } })();
let state = JSON.parse(LS.getItem(KEY) || '{}');
let cur = -1, filter = 'all';
const list = document.getElementById('list');
function bucketCls(b){ return b==='long_10s+'?'long':(b==='short_1.5_3s'||b==='word_0.3_1.5s')?'short':''; }
function esc(s){ return s.replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function fmt(t){ const m=Math.floor(t/60), s=t-m*60; return String(m).padStart(2,'0')+':'+s.toFixed(2).padStart(5,'0'); }
function render(){
  list.innerHTML='';
  DATA.forEach((d,i)=>{
    const st = state[d.id] || '';
    const card = document.createElement('div');
    card.className='card '+(st==='pass'?'pass':st==='fail'?'fail':'');
    card.dataset.i=i; card.dataset.status=st; card.dataset.dur=d.dur;
    card.innerHTML = `
      <div class="row">
        <span class="id">${d.id}</span>
        <span class="meta">${fmt(d.start)} – ${fmt(d.end)} · ${d.dur.toFixed(2)}s · ${d.chars}字 · ${d.rate.toFixed(1)}字/秒</span>
        <span class="badge ${bucketCls(d.bucket)}">${d.bucket}</span>
        ${d.flags.includes('check')?'<span class="badge warn">需复核</span>':''}
        <span style="flex:1"></span>
        <button class="play" data-play="${i}">▶ 片段</button>
        <button class="play ghost" data-ctx="${i}">▶ 带上下文</button>
      </div>
      <div class="wavebox">${d.svg}</div>
      <div class="text">${esc(d.text)}</div>
      <div class="acts"><button data-mark="pass" data-i="${i}">✓ 切得对</button><button data-mark="fail" data-i="${i}">✗ 有问题</button></div>`;
    list.appendChild(card);
  });
  bind(); applyFilter(); updateStat();
}
let audio=null, playingBtn=null;
function toast(msg){ let t=document.getElementById('toast'); if(!t){t=document.createElement('div');t.id='toast';document.body.appendChild(t);} t.innerHTML=msg; t.className='show'; clearTimeout(window.__tt); window.__tt=setTimeout(()=>t.className='',9000); }
function play(src, btn){
  if(audio){ audio.pause(); audio=null; }
  if(playingBtn) playingBtn.textContent = playingBtn.dataset.label;
  audio = new Audio(src);
  audio.addEventListener('ended', ()=>{ if(playingBtn) playingBtn.textContent = playingBtn.dataset.label; });
  audio.addEventListener('error', ()=>{ toast('音频加载失败：若用 file:// 打不开，请在本目录执行 <code>python -m http.server 8800</code> 再访问'); });
  audio.play(); playingBtn=btn; if(!btn.dataset.label) btn.dataset.label=btn.textContent; btn.textContent='⏸ 停止';
}
function bind(){
  list.querySelectorAll('[data-play]').forEach(b=>b.onclick=e=>{e.stopPropagation(); play(DATA[+b.dataset.play].clip,b);});
  list.querySelectorAll('[data-ctx]').forEach(b=>b.onclick=e=>{e.stopPropagation(); play(DATA[+b.dataset.ctx].ctx,b);});
  list.querySelectorAll('[data-mark]').forEach(b=>b.onclick=e=>{
    e.stopPropagation(); const i=+b.dataset.i, id=DATA[i].id;
    state[id] = (state[id]===b.dataset.mark) ? '' : b.dataset.mark;
    LS.setItem(KEY, JSON.stringify(state));
    const card=b.closest('.card');
    card.className='card '+(state[id]==='pass'?'pass':state[id]==='fail'?'fail':'');
    card.dataset.status=state[id]; updateStat(); applyFilter();
  });
  list.querySelectorAll('.card').forEach(c=>c.onclick=()=>focusCard(+c.dataset.i));
}
function focusCard(i){ cur=i; document.querySelectorAll('.card').forEach(c=>c.classList.remove('focus'));
  const c=document.querySelector(`.card[data-i="${i}"]`); if(c){c.classList.add('focus'); c.scrollIntoView({block:'center',behavior:'smooth'});} }
function applyFilter(){ document.querySelectorAll('.card').forEach(c=>{
  const st=c.dataset.status, d=parseFloat(c.dataset.dur); let show=true;
  if(filter==='todo') show=!st; else if(filter==='fail') show=st==='fail';
  else if(filter==='long') show=d>8; else if(filter==='short') show=d<3.5;
  c.classList.toggle('hidden',!show);}); }
function updateStat(){ const n=DATA.length, pass=DATA.filter(d=>state[d.id]==='pass').length, fail=DATA.filter(d=>state[d.id]==='fail').length;
  document.getElementById('stat').innerHTML=`共 <b>${n}</b> 条 · 已确认 <b>${pass}</b> · 有问题 <b>${fail}</b> · 未审 <b>${n-pass-fail}</b>`; }
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); filter=b.dataset.filter; applyFilter(); });
document.getElementById('export').onclick=()=>{
  const out=DATA.map(d=>({id:d.id,status:state[d.id]||'',dur:+d.dur.toFixed(2),text:d.text}));
  const fail=out.filter(x=>x.status==='fail').map(x=>x.id);
  const txt=JSON.stringify({summary:{total:out.length,pass:out.filter(x=>x.status==='pass').length,fail:fail.length},fail_ids:fail,items:out},null,1);
  navigator.clipboard.writeText(txt).then(()=>alert('已复制（'+out.length+' 条，问题 '+fail.length+' 条）'))
    .catch(()=>{const w=window.open(); w.document.write('<pre>'+esc(txt)+'</pre>');}); };
document.addEventListener('keydown', e=>{
  if(e.target.tagName==='INPUT') return;
  if(e.key==='j'||e.key==='ArrowDown'){ e.preventDefault(); focusCard(cur<0?0:Math.min(cur+1,DATA.length-1)); }
  if(e.key==='k'||e.key==='ArrowUp'){ e.preventDefault(); if(cur>0) focusCard(cur-1); }
  if(e.key==='1'&&cur>=0){ state[DATA[cur].id]='pass'; LS.setItem(KEY,JSON.stringify(state)); render(); focusCard(cur); }
  if(e.key==='2'&&cur>=0){ state[DATA[cur].id]='fail'; LS.setItem(KEY,JSON.stringify(state)); render(); focusCard(cur); }
  if(e.key===' '&&cur>=0){ e.preventDefault(); play(DATA[cur].clip); }
});
render();
"""


def envelope(samples, n=420):
    if len(samples) == 0:
        return [0.0] * n
    idx = np.linspace(0, len(samples), n + 1).astype(int)
    env = np.zeros(n)
    for i in range(n):
        a, b = idx[i], max(idx[i + 1], idx[i] + 1)
        seg = np.abs(samples[a:b])
        env[i] = seg.max() if len(seg) else 0
    return (env / (env.max() or 1)).tolist()


def svg_wave(env, ca, cb, w=680, h=78):
    n = len(env)
    X = lambda i: w * i / (n - 1)
    Y = lambda v: h - 4 - v * (h - 12)
    top = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(env))
    bot = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in reversed(list(enumerate(env))))
    a, b = ca * w, cb * w
    return ('<svg viewBox="0 0 %d %d" preserveAspectRatio="none" class="wave">' % (w, h)
            + '<rect x="%.1f" y="0" width="%.1f" height="%d" fill="#e8f5ef"/>' % (a, max(b - a, 1), h)
            + '<line x1="%.1f" y1="0" x2="%.1f" y2="%d" class="cut"/>' % (a, a, h)
            + '<line x1="%.1f" y1="0" x2="%.1f" y2="%d" class="cut"/>' % (b, b, h)
            + '<polygon points="%s %s" fill="#2f7f5f" fill-opacity="0.55"/>' % (top, bot)
            + "</svg>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="产出/manifest_split.jsonl")
    ap.add_argument("--work", default="work")
    ap.add_argument("--out", default="产出/审阅")
    ap.add_argument("--pad", type=float, default=2.5, help="上下文秒数")
    args = ap.parse_args()

    os.makedirs(os.path.join(args.out, "ctx"), exist_ok=True)
    rows = [json.loads(l) for l in open(args.manifest, encoding="utf-8")]
    full = C.read_wav(os.path.join(args.work, "full16k.wav"))
    total = len(full) / float(C.SR)

    data = []
    for r in rows:
        s, e = float(r["start"]), float(r["end"])
        ca, cb = max(0.0, s - args.pad), min(total, e + args.pad)
        seg = full[int(ca * C.SR):int(cb * C.SR)]
        ctx_name = r["id"] + ".wav"
        C.write_wav(os.path.join(args.out, "ctx", ctx_name), seg)

        text = r["text"].split("<asr_text>", 1)[-1]
        chars = len(C.normalize(text))
        data.append({
            "id": r["id"], "start": s, "end": e, "dur": e - s,
            "chars": chars, "rate": chars / max(e - s, 0.01),
            "bucket": r.get("duration_bucket", C.bucket(e - s)),
            "flags": r.get("quality_flags", []),
            "text": text,
            "clip": os.path.relpath(os.path.abspath(r["audio"]), os.path.abspath(args.out)).replace("\\", "/"),
            "ctx": "ctx/" + ctx_name,
            "svg": svg_wave(envelope(seg), (s - ca) / (cb - ca), (e - ca) / (cb - ca)),
        })

    html = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>切分审阅</title><style>%s</style></head><body>
<header>
  <h1>切分审阅</h1>
  <div class="sub">灰色波形 = 切点前后各 %.1f 秒上下文；绿色高亮 = 实际切出的区间。听「片段」判断有没有吃字。</div>
  <div class="bar">
    <button data-filter="all" class="on">全部</button>
    <button data-filter="todo">未审</button>
    <button data-filter="fail">有问题</button>
    <button data-filter="long">&gt;8s</button>
    <button data-filter="short">&lt;3.5s</button>
    <button id="export">导出结果</button>
    <span id="stat" class="stat"></span>
  </div>
  <div class="tip">快捷键：<kbd>J</kbd>/<kbd>K</kbd> 上下条 · <kbd>空格</kbd> 播放 · <kbd>1</kbd> 对 · <kbd>2</kbd> 有问题</div>
</header>
<main><div id="list"></div></main>
<script>%s</script></body></html>""" % (CSS, args.pad, JS.replace("__DATA__", json.dumps(data, ensure_ascii=False)))

    out_html = os.path.join(args.out, "切分审阅.html")
    open(out_html, "w", encoding="utf-8").write(html)
    print("entries %d -> %s (%.1f KB)" % (len(data), out_html, os.path.getsize(out_html) / 1024))


if __name__ == "__main__":
    main()
