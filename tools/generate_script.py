#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 DeepSeek 生成一期「NEWS 番组」台本。

设计要点（对齐 myradio 的做法）：
  - 新闻事实由本文件内的 NEWS 常量提供，模型只负责「改写成口语播报稿」，
    避免大模型凭空编造新闻。
  - 每句拆成 say / show：say 交给语音合成（英文缩写写成中文读法，
    避免 TTS 把 "DeepSeek" 读成字母），show 是屏幕上显示的正确表记。
  - 输出严格 JSON，再由 build_audio.py 写入精确时间轴。

用法：
  export DEEPSEEK_API_KEY=sk-xxxx      # 或不设，自动读 ~/.deepseek-balance/config.json
  python3 tools/generate_script.py
  python3 tools/generate_script.py --date 2026-11-07
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

# 2026-11-02 ~ 11-05 期间公开报道的 AI 新闻。事实部分只在这里维护。
NEWS = [
    {
        "id": "01",
        "kicker": "开源 · 智能体",
        "title": "DeepSeek 开源 Super-agent 研究原型",
        "expression": "竖食指开",
        "url": "https://www.zhihu.com/pin/2100551711727294368",
        "facts": [
            "11 月 2 日，DeepSeek 开放 Super-agent 研究原型并公布架构思路，代码以 DeepSeek Harness 组件包提供，采用 MIT 许可。",
            "架构上由常驻 Router 层统一分派交互、Worker 层隔离并发，原型面向单个 GitHub 仓库，可监听飞书消息。",
            "获授权人员提出任务后建立工作项，用独立会话和目录执行，完成后回到原对话反馈结果，例如提交拉取请求。",
            "官方强调公开代码经过调整，属于研究代码，不是正式产品。",
        ],
    },
    {
        "id": "02",
        "kicker": "大模型 · 国产算力",
        "title": "美团 LongCat-2.5：1.6 万亿参数",
        "expression": "圈圈眼",
        "url": "https://thinkbar.blog.csdn.net/article/details/169905182",
        "facts": [
            "11 月 2 日，美团发布 LongCat-2.5，总参数 1.6 万亿，是面向长程智能体任务的原生多模态模型。",
            "训练全程由国产算力完成，强化了原生视觉理解与智能体编程能力。",
            "多项主流基准评测表现介于 Claude Opus 4.8 与 Claude Opus 5 之间，部分评测超过后者。",
            "用户可在 longcat.ai 体验，开发者可通过同步上线的 API 调用。",
        ],
    },
    {
        "id": "03",
        "kicker": "开发者大会 · 硬件",
        "title": "微软开发者大会连发 AI 新品",
        "expression": "＞＜",
        "url": "https://thinkbar.blog.csdn.net/article/details/169905182",
        "facts": [
            "11 月 2 日，微软年度开发者大会在旧金山开幕，一口气发布首款 AI 编程模型、推理模型、AI 搜索引擎与个人助手。",
            "现场还展示了内置 1200 亿参数 AI 模型、搭载英伟达芯片的个人电脑，以及新一代量子芯片。",
            "微软给出的目标是 2029 年前造出实用的量子计算机。",
        ],
    },
    {
        "id": "04",
        "kicker": "标准 · 合规",
        "title": "四大厂商统一 AI 训练退出信号",
        "expression": "屑屑眼",
        "url": "https://www.zhihu.com/pin/2100551711727294368",
        "facts": [
            "OpenAI、谷歌、微软、Anthropic 宣布共同支持统一的训练偏好信号。",
            "网站在 robots.txt 里写一次 __usage_ai-training 标记，就能声明内容是否可用于生成式 AI 训练，不必逐家配置规则。",
            "草案由 Anthropic 提交给 IETF 工作组，目前仍是个人草案；该信号只表达用途偏好，不影响搜索引擎收录。",
            "谷歌称未单独声明时按 Google-Extended 拦截，微软定于 2027 年 2 月 1 日启用、3 月 1 日停用旧标签。",
        ],
    },
    {
        "id": "05",
        "kicker": "工具 · 正式可用",
        "title": "谷歌 Computer Use 转入正式可用",
        "expression": "爱心眼",
        "url": "https://www.zhihu.com/pin/2100551711727294368",
        "facts": [
            "谷歌把 Computer Use 工具推入正式可用阶段，支持两类 Gemini API。",
            "模型读取截图后给出点击、滚动或键盘输入等操作，再按新截图继续任务，官方示例包括填表和网页流程测试。",
            "客户端需要自备执行环境、操作处理器与截图回传逻辑；官方提供可配置安全策略与截图提示注入检测，需确认的动作应等待批准。",
        ],
    },
]

SYSTEM_PROMPT = """你是一家中文科技电台的编导。请把提供的新闻事实，改写成由虚拟主播播报的口语台本。

硬性要求：
1. 只使用给定的事实，不得补充、推测或编造任何数字、公司名、日期、产品名。
2. 输出严格 JSON（不要 markdown 代码块、不要任何解释文字），结构如下：
{
  "headline": "本期一句话标题，不超过 20 字",
  "topics": [
    {
      "id": "原样保留",
      "lines": [
        {"say": "朗读用文本", "show": "字幕用文本"}
      ]
    }
  ]
}
3. 每个话题写 3 句；另在第一个话题前加 2 句开场（id 为 "00"，放在 topics 数组最前），
   在最后一个话题后加 2 句结尾（id 为 "99"，放在数组最后）。开场与结尾的 lines 也是数组。
4. 每句 14~26 个汉字，口语、轻快、像在跟听众聊天，不要书面语和长定语从句。
5. say 与 show 的区别至关重要：
   - say 是给中文语音合成朗读的：所有英文品牌、型号、缩写都要写成中文读法或全称，
     例如 DeepSeek 写成「深度求索」、Super-agent 写成「超级智能体」、
     Claude Opus 写成「克劳德 欧帕斯」、robots.txt 写成「robots 点 t x t」、
     IETF 写成「I E T F」、API 写成「A P I」、AI 写成「A I」、GitHub 写成「吉特哈布」、
     Gemini 写成「杰米奈」、LongCat 写成「长猫」。
   - show 是屏幕字幕：保留正确的英文原写法与标点，专业读者要能一眼认出。
   - 两者说的是同一句话，只是表记不同。
6. 开场第一句必须用固定口头禅：「Deepdeep 耶！～(∠・ω< )⌒☆ 大家早上好呀，我是小鲸，今天是X号，欢迎收听小鲸新闻！」
   其中颜文字与感叹号只放 show（字幕），say 写成纯口语「Deepdeep 耶！大家早上好呀，我是小鲸…」，
   避免语音合成把符号念出来。结尾提醒可以在下方看台本全文和原文链接。
7. 不要使用「首先/其次/最后」之外的连接词重复堆砌，串场自然一点。
"""

USER_TEMPLATE = """日期：{date}

以下是本期要播报的新闻事实（按话题分组，id 必须原样保留）：

{news}

请输出严格 JSON。"""


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


def call_deepseek(api_key: str, prompt: str) -> str:
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 1.1,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


def build_episode(script: dict, date: str) -> dict:
    by_id = {t["id"]: t for t in script["topics"]}
    topics = []
    for n in NEWS:
        lines = by_id.get(n["id"], {}).get("lines", [])
        if not lines:
            raise ValueError(f"DeepSeek 没有为话题 {n['id']} 生成台词")
        topics.append({
            "id": n["id"], "kicker": n["kicker"], "title": n["title"],
            "url": n["url"], "image": "", "expression": n["expression"],
            "facts": n["facts"], "lines": lines,
        })
    # 开场 / 结尾作为独立话题，播放器里不做链接卡片
    if "00" in by_id:
        topics.insert(0, {
            "id": "00", "kicker": "开场", "title": "今日开播", "url": "",
            "image": "", "expression": "脸红", "facts": [],
            "lines": by_id["00"]["lines"],
        })
    if "99" in by_id:
        topics.append({
            "id": "99", "kicker": "片尾", "title": "明天见", "url": "",
            "image": "", "expression": "脸红", "facts": [],
            "lines": by_id["99"]["lines"],
        })
    return {
        "date": date, "lang": "zh",
        "title": script.get("headline", "AI 早报"),
        "duration": 0,
        "credits": {
            "script": "DeepSeek " + MODEL,
            "caster": "DeepSeek-chan (Live2D Cubism 4)",
            "voice": "macOS 本地语音合成 · Tingting",
        },
        "topics": topics,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-11-06")
    args = ap.parse_args()

    news_block = "\n\n".join(
        f"### id={n['id']}｜{n['title']}\n" + "\n".join("- " + f for f in n["facts"])
        for n in NEWS
    )
    prompt = USER_TEMPLATE.format(date=args.date, news=news_block)
    print("→ 调用 DeepSeek 生成台本 ...")
    raw = call_deepseek(get_api_key(), prompt)
    script = parse_json(raw)
    episode = build_episode(script, args.date)

    out = ROOT / "episodes" / f"{args.date}-zh.json"
    out.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")

    index_path = ROOT / "episodes.json"
    entries = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    entries = [e for e in entries if e.get("date") != args.date]
    entries.insert(0, {
        "date": args.date, "lang": "zh", "title": episode["title"],
        "file": f"episodes/{args.date}-zh.json",
        "audio": f"audio/{args.date}-zh.mp3",
    })
    entries.sort(key=lambda e: e["date"], reverse=True)
    index_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    n_lines = sum(len(t["lines"]) for t in episode["topics"])
    print(f"✓ 台本已生成：{out}")
    print(f"  标题：{episode['title']}｜{len(episode['topics'])} 个段落｜{n_lines} 句")


if __name__ == "__main__":
    main()
