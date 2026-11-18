#!/usr/bin/env python3
"""Extract a reproducible, explicitly unverified index from a PowerPoint file."""
import argparse, collections, hashlib, json, re, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','p14':'http://schemas.microsoft.com/office/powerpoint/2010/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
SECTIONS=[(1,2,'无标题节'),(3,5,'使用指南'),(6,38,'封面&目录&过渡'),(39,261,'图文模板'),(262,298,'截图展示'),(299,356,'荣誉证书'),(357,368,'logo展示'),(369,408,'人物排版'),(409,430,'产品介绍'),(431,458,'发展历程'),(459,606,'地图展示')]
def section(n): return next((name for a,b,name in SECTIONS if a<=n<=b),'未分类')
def build(src,out):
 digest=hashlib.sha256()
 with src.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):digest.update(b)
 with zipfile.ZipFile(src) as z:
  files=sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)),key=lambda n:int(re.search(r'\d+',n).group()))
  items=[]
  for path in files:
   n=int(re.search(r'\d+',path).group());r=ET.fromstring(z.read(path));paras=[]
   for p in r.findall('.//a:p',NS):
    s=''.join(t.text or '' for t in p.findall('.//a:t',NS)).strip()
    if s:paras.append(s)
   labels=[s for s in paras if len(s)<=70 and re.search(r'排版|目录|封面|过渡|截图|证书|荣誉|人物|团队|产品介绍|发展历程|地图展示|Logo展示|logo展示',s,re.I)]
   labels=list(dict.fromkeys(labels))[:8]
   joined=' '.join(labels); m=re.search(r'(?<![0-9])([0-9]{1,2}|[一二三四五六七八九十两])(?:张|位|个|幅)?(?:图|图片|人物|人|证书|奖状|截图|产品)',joined)
   num={'一':1,'两':2,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
   count=(int(m.group(1)) if m.group(1).isdigit() else num.get(m.group(1))) if m else None
   tags=[x for x in ['并列','对比','流程','时间','人物','团队','组织架构','地图','证书','荣誉','截图','产品','目录','封面','环形','扇形','三维','纵向','横向','错位','瀑布流'] if x in joined]
   items.append({'slide':n,'section':section(n),'labels':labels,'inferred_tags':tags, 'label_item_count':count, 'text':paras,'pictures':len(r.findall('.//p:pic',NS)),'shapes':len(r.findall('.//p:sp',NS)),'groups':len(r.findall('.//p:grpSp',NS)),'has_timing':r.find('p:timing',NS) is not None,'thumbnail':f'thumbnails/slide-{n:03d}.jpg','evidence':'OOXML 自动提取；未逐页视觉核实或播放动画'})
  result={'source_file':src.name,'sha256':digest.hexdigest(),'slide_count':len(files),'dimensions_emu':ET.fromstring(z.read('ppt/presentation.xml')).find('p:sldSz',NS).attrib,'notes':'页码基于该版本 PowerPoint 幻灯片顺序；对象数量并不等于可替换图片数；标签和示例文本不是事实。','slides':items}
  out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print('indexed',len(items),'slides; animation timing',sum(s['has_timing'] for s in items),'sha256',digest.hexdigest())
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('pptx',type=Path);p.add_argument('output',type=Path);a=p.parse_args();build(a.pptx,a.output)
