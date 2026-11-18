#!/usr/bin/env python3
"""Search template page labels and source text; results are candidates, not visual verification."""
import argparse,json,re,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('terms',nargs='*',help='关键词，多个词空格分隔');p.add_argument('--items',type=int,help='标签中标明的项目或图片数量（自动推断，可能漏检）');p.add_argument('--section',default='',help='分区名的一部分');p.add_argument('--pages',default='',help='范围，如 39-261');p.add_argument('--animation',choices=['yes','no']);p.add_argument('--limit',type=int,default=15);p.add_argument('--json',action='store_true');p.add_argument('--index',type=Path,default=Path(__file__).resolve().parent.parent/'catalog/slides.json');a=p.parse_args()
d=json.loads(a.index.read_text(encoding='utf-8'));terms=[t.lower() for t in a.terms]; results=[]
for s in d['slides']:
 if a.section.lower() not in s['section'].lower():continue
 if a.items is not None and s.get('label_item_count')!=a.items:continue
 if a.pages:
  m=re.fullmatch(r'(\d+)(?:-(\d+))?',a.pages)
  if not m:sys.exit('--pages 格式应为 39-261 或 40')
  lo=int(m[1]);hi=int(m[2] or m[1]);
  if not lo<=s['slide']<=hi:continue
 if a.animation and s['has_timing']!=(a.animation=='yes'):continue
 label=' '.join(s['labels']).lower();content=' '.join(s['text']).lower();sec=s['section'].lower();score=0
 for t in terms:
  score+=8*(t in label)+5*(t in sec)+2*(t in content)
 if terms and not score:continue
 results.append((score,s))
results.sort(key=lambda x:(-x[0],x[1]['slide']));results=results[:max(0,a.limit)]
if a.json: print(json.dumps([s for _,s in results],ensure_ascii=False,indent=2))
else:
 for score,s in results:
  print(f"第{s['slide']}页 | {s['section']} | {'有动画结构' if s['has_timing'] else '无动画结构'} | 图片对象{s['pictures']} | "+' / '.join(s['labels'][:3]))
  print('  缩略图: '+str(a.index.parent/s['thumbnail']))
  print('  示例文本: '+ ' / '.join(s['text'][:4])[:180])
 print('注意：结果根据原始文字和对象自动检索；须视觉核实。',file=sys.stderr)
