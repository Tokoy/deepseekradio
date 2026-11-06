#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把台本里的长事实（facts）派生出「短要点 points + 可展开详情 details + 链接卡 link」。

对齐 myradio 的 monoradio/news-1 格式：
  - points[]  阅读区里可点的短标题
  - details[] 点击要点后展开的详细说明（这里直接复用检索到的事实原文，不改写）
  - link{}    播放到该条时显示的 OGP 风格卡片
本脚本不触碰 lines[].start/end，所以时间轴与音频保持完全一致。

用法：
  python3 tools/enrich_news.py
  python3 tools/enrich_news.py --date 2026-11-06
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是中文科技电台的编辑。输入是若干条新闻，每条含若干「事实长句」。
请把每条事实长句压缩成一个 8~16 个汉字的短要点，作为新闻阅读区里可点击的条目标题。

硬性要求：
1. 只压缩、概括，不得添加任何新事实、数字或推断。
2. 短要点要能独立看懂，保留关键主体和数字（如「1.6 万亿参数」「2027 年启用」）。
3. 输出严格 JSON（不要 markdown 代码块、不要解释文字），格式：
   {"01": ["短要点1", "短要点2"], "02": ["..."]}
   键是话题 id，值的数组长度必须与该话题输入的事实条数完全相同，顺序一一对应。
4. 每个短要点不要以句号结尾。
"""


def get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    cfg = Path.home() / ".deepseek-balance" / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8")).get("apiKey", "").strip()
        except Exception:
            pass
    sys.exit("缺少 DeepSeek API key：请设置 DEEPSEEK_API_KEY 环境变量")


def call_deepseek(api_key: str, payload: dict) -> dict:
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return json.loads(data["choices"][0]["message"]["content"])


def site_of(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc.replace("www.", "")


def fallback_point(fact: str) -> str:
    """本地兜底：取第一个分句，避免把英文单词从中间截断。"""
    head = re.split(r"[，,。；;：:]", fact.strip())[0]
    if len(head) > 18:
        cut = head[:18]
        # 结尾若是半个英文单词，退到最后一个空格
        if re.search(r"[A-Za-z0-9\-]$", cut) and " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut.rstrip(" ·-")
    return head


def align_points(pts, facts):
    """模型偶尔多给/少给几条，按事实条数一一对齐，不让阅读区出现断头文本。"""
    out = []
    for i, fact in enumerate(facts):
        p = pts[i] if i < len(pts) else ""
        p = (p or "").strip().rstrip("。.")
        out.append(p if 4 <= len(p) <= 30 else fallback_point(fact))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-11-06")
    args = ap.parse_args()

    path = ROOT / "episodes" / f"{args.date}-zh.json"
    ep = json.loads(path.read_text(encoding="utf-8"))
    news = [t for t in ep["topics"] if t.get("facts") and t.get("url")]

    payload = {t["id"]: t["facts"] for t in news}
    print(f"→ 调用 DeepSeek 为 {len(news)} 条新闻提炼短要点 ...")
    points_map = call_deepseek(get_api_key(), payload)

    for t in news:
        facts = t["facts"]
        raw = points_map.get(t["id"], [])
        if len(raw) != len(facts):
            print(f"  ! 话题 {t['id']} 条数不符（{len(raw)} vs {len(facts)}），已按事实逐条对齐")
        pts = align_points(raw, facts)
        t["points"] = pts
        t["details"] = facts
        t["link"] = {
            "url": t["url"],
            "title": t["title"],
            "site": site_of(t["url"]),
            "description": facts[0],
            "image": "",   # 留空时用本地生成的图卡；填入 OGP 图 URL 即热链显示（不落地图片）
            "icon": "",
        }
        print(f"  [{t['id']}] " + " / ".join(pts))

    path.write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 已写回 {path}（时间轴未改动）")


if __name__ == "__main__":
    main()
