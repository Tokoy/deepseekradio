#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成本地 SVG 新闻图卡（零依赖、零外部请求、零积分消耗）。

风格统一：渐变底 + 抽象几何图标 + 大编号 + 栏目字样。
输出 assets/news/00.svg（开场/片尾通用）与 01.svg ~ 05.svg。
想换成 AI 精修图时，直接替换同名文件即可，播放器不需要改代码。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "news"
OUT.mkdir(parents=True, exist_ok=True)

# id: (主色, 辅色, 英文标签, 图标类型)
THEMES = [
    ("00", "#1D3B8C", "#3D5AFE", "WHALE NEWS / AI DAILY", "wave"),
    ("01", "#16307A", "#4D7CFF", "OPEN SOURCE AGENT", "nodes"),
    ("02", "#0F6E8C", "#31B0C8", "FOUNDATION MODEL", "rings"),
    ("03", "#4A3A8C", "#7A5AF8", "DEV CONFERENCE", "chip"),
    ("04", "#8C3A4A", "#D9646E", "TRAINING SIGNAL", "shield"),
    ("05", "#16684F", "#3DBE8B", "COMPUTER USE", "cursor"),
]


def icon(kind: str) -> str:
    w = 'rgba(255,255,255,.30)'
    f = 'rgba(255,255,255,.10)'
    s = 'rgba(255,255,255,.55)'
    if kind == "wave":
        return f'''
  <path d="M760 250 Q830 190 900 250 T1040 250 T1180 250" fill="none" stroke="{w}" stroke-width="9"/>
  <path d="M760 300 Q830 240 900 300 T1040 300 T1180 300" fill="none" stroke="{w}" stroke-width="9"/>
  <circle cx="955" cy="140" r="62" fill="{f}" stroke="{s}" stroke-width="3"/>
  <circle cx="978" cy="128" r="7" fill="{s}"/>'''
    if kind == "nodes":
        pts = [(800, 130), (960, 100), (1110, 175), (860, 280), (1040, 310)]
        lines = "".join(
            f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="{w}" stroke-width="3"/>'
            for i, (ax, ay) in enumerate(pts) for bx, by in pts[i + 1:]
        )
        dots = "".join(
            f'<circle cx="{x}" cy="{y}" r="20" fill="{f}" stroke="{s}" stroke-width="3"/>'
            for x, y in pts
        )
        return f"\n  {lines}\n  {dots}"
    if kind == "rings":
        return f'''
  <circle cx="960" cy="200" r="160" fill="none" stroke="{w}" stroke-width="3"/>
  <circle cx="960" cy="200" r="112" fill="{f}" stroke="{s}" stroke-width="3"/>
  <circle cx="960" cy="200" r="60" fill="none" stroke="{w}" stroke-width="3"/>
  <circle cx="960" cy="200" r="18" fill="{s}"/>
  <path d="M960 20v40M960 340v40M780 200h40M1100 200h40" stroke="{w}" stroke-width="4"/>'''
    if kind == "chip":
        cells = "".join(
            f'<rect x="{820 + c * 62}" y="{110 + r * 62}" width="46" height="46" rx="6" fill="{f}" stroke="{w}" stroke-width="2"/>'
            for r in range(3) for c in range(5)
        )
        return f'''
  <rect x="795" y="85" width="340" height="230" rx="14" fill="none" stroke="{s}" stroke-width="4"/>
  {cells}'''
    if kind == "shield":
        return f'''
  <path d="M960 60 L1125 130 V245 Q1125 330 960 370 Q795 330 795 245 V130 Z"
        fill="{f}" stroke="{s}" stroke-width="5"/>
  <path d="M885 215 l50 55 95 -110" fill="none" stroke="{w}" stroke-width="14"
        stroke-linecap="round" stroke-linejoin="round"/>'''
    if kind == "cursor":
        return f'''
  <rect x="800" y="90" width="330" height="220" rx="12" fill="{f}" stroke="{s}" stroke-width="4"/>
  <path d="M800 140h330" stroke="{w}" stroke-width="4"/>
  <circle cx="826" cy="115" r="7" fill="{s}"/><circle cx="850" cy="115" r="7" fill="{s}"/>
  <rect x="835" y="175" width="120" height="14" rx="7" fill="{w}"/>
  <rect x="835" y="205" width="190" height="14" rx="7" fill="{w}"/>
  <rect x="835" y="235" width="150" height="14" rx="7" fill="{w}"/>
  <path d="M1010 200 l0 105 28 -30 20 42 22 -11 -20 -41 40 -3 z"
        fill="#FFFFFF" stroke="{s}" stroke-width="3"/>'''
    return ""


def svg(num: str, c1: str, c2: str, label: str, kind: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="400" viewBox="0 0 1200 400">
<defs>
  <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>
  </linearGradient>
  <pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="1.2" fill="rgba(255,255,255,.14)"/>
  </pattern>
</defs>
<rect width="1200" height="400" fill="url(#g)"/>
<rect width="1200" height="400" fill="url(#dots)"/>
<circle cx="975" cy="205" r="185" fill="rgba(255,255,255,.06)"/>
{icon(kind)}
<text x="56" y="192" font-family="ui-monospace,Menlo,monospace" font-size="148" font-weight="700"
      fill="rgba(255,255,255,.92)" letter-spacing="-4">{num}</text>
<rect x="60" y="222" width="62" height="5" fill="rgba(255,255,255,.75)"/>
<text x="60" y="270" font-family="-apple-system,PingFang SC,Helvetica,sans-serif" font-size="27"
      font-weight="600" fill="rgba(255,255,255,.90)" letter-spacing="2">{label}</text>
<text x="60" y="344" font-family="ui-monospace,Menlo,monospace" font-size="17"
      fill="rgba(255,255,255,.55)" letter-spacing="3">WHALE NEWS  /  DAILY AI BRIEF</text>
</svg>
'''


def main():
    for num, c1, c2, label, kind in THEMES:
        p = OUT / f"{num}.svg"
        p.write_text(svg(num, c1, c2, label, kind), encoding="utf-8")
        print(f"✓ {p.relative_to(ROOT)}  {p.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
