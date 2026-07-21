#!/usr/bin/env python3
"""逐页精确对比陈雨蝶论文与paper_v2的排版参数"""

import fitz
import json

CHEN = '/Users/zhouleixishu/Zotero/storage/AYDB6KXP/陈雨蝶 等 _ 2025 _ 双碳背景下复杂冷链物流模型及求解算法.pdf'
MINE = '/Volumes/移动硬盘（512G）/ReSETP/docs/paper_v2/paper_main.pdf'

def analyze_pdf(path, label):
    doc = fitz.open(path)
    pages_info = []
    for pg_idx in range(doc.page_count):
        page = doc[pg_idx]
        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if b[6] == 0]
        
        # Count formulas (blocks containing math symbols)
        formula_count = 0
        table_count = 0
        for b in text_blocks:
            text = b[4]
            if any(kw in text for kw in ['∑', '∏', '∫', 'frac', 'sqrt', 'min', 'max']):
                formula_count += 1
            if '表' in text and 'toprule' not in text:
                pass
        
        # Get text content
        text = page.get_text()
        lines = [l for l in text.split('\n') if l.strip()]
        
        pages_info.append({
            'page': pg_idx + 1,
            'text_blocks': len(text_blocks),
            'text_lines': len(lines),
            'text_chars': len(text),
            'formula_indicators': formula_count,
        })
    
    doc.close()
    return pages_info

print("=" * 70)
print("逐页排版密度对比")
print("=" * 70)

chen_pages = analyze_pdf(CHEN, "陈雨蝶")
mine_pages = analyze_pdf(MINE, "你的V3")

print(f"{'页码':<6} {'陈-行数':<10} {'你-行数':<10} {'陈-字符':<10} {'你-字符':<10} {'密度比':<8}")
print("-" * 55)

for cp, mp in zip(chen_pages, mine_pages):
    density_ratio = mp['text_chars'] / max(cp['text_chars'], 1)
    print(f"{cp['page']:<6} {cp['text_lines']:<10} {mp['text_lines']:<10} "
          f"{cp['text_chars']:<10} {mp['text_chars']:<10} {density_ratio:.2f}")

print(f"\n陈雨蝶总页数: {len(chen_pages)}, 总字符: {sum(p['text_chars'] for p in chen_pages)}")
print(f"你的总页数: {len(mine_pages)}, 总字符: {sum(p['text_chars'] for p in mine_pages)}")

# Key section analysis
print("\n" + "=" * 70)
print("关键章节定位")
print("=" * 70)

chen_doc = fitz.open(CHEN)
mine_doc = fitz.open(MINE)

for label, doc in [("陈雨蝶", chen_doc), ("你的V3", mine_doc)]:
    print(f"\n--- {label} ---")
    for pg in range(doc.page_count):
        text = doc[pg].get_text()
        for kw in ['引言', '模型建立', '问题描述', '目标函数', '模型建立', '算法设计', '数值实验', '结语']:
            if kw in text and kw not in ['符号', '两层模型']:
                # Find first occurrence
                idx = text.find(kw)
                context = text[max(0,idx-10):idx+30].replace('\n',' ')
                print(f"  p{pg+1}: ...{context}...")
                break
    doc.close()

chen_doc.close()
mine_doc.close()
