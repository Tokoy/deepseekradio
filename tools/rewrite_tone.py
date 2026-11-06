#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把台本台词改写成「可爱 / 活泼 / 元气」口吻，事实一字不改。

设计要点：
  - 只改语气词、连接词、句式活泼度；日期 / 数字 / 公司名 / 产品名 / 技术名词强制保留。
  - 逐句做「数字 + 英文专名」校验，任何事实 token 丢失就回退该句原文，并在终端报告。
  - 保留 lines[].start/end（旧音频时间轴），另标记 audioStatus 等新音频到位后重算。
  - 导出两份纯文本：阅读版台本、可直接粘进 TTS 的逐句朗读稿。

用法：
  python3 tools/rewrite_tone.py
  python3 tools/rewrite_tone.py --date 2026-11-06 --tone 元气
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

SYSTEM_PROMPT = """你是中文科技电台的编导。把输入的这期 AI 新闻台本，改写成「可爱、活泼、元气满满」的口吻，
像元气满满的少女主播在跟朋友聊天，但依然专业、不油不腻。

硬性要求（违反即失败）：
1. 事实零改动。所有日期、数字、公司名、产品名、技术名词、协议名、组织名必须与原文完全一致，
   不得增删、替换、推测、补充。只改语气词、连接词、称呼和句式的活泼程度。
2. 保持结构：话题 id、每个话题的句子条数、句子顺序完全不变，总句数不变。
3. 每句长度尽量贴近原句（±12 字以内），否则配音时长会大幅变化。
4. 每句仍输出 say / show 两个版本，且是同一句话：
   - say：给中文语音合成朗读。**沿用输入里已有的英文读法**，不要自创：
     深度求索(DeepSeek)、超级智能体(Super-agent)、长猫(LongCat)、克劳德欧帕斯(Claude Opus)、
     欧喷 A I(OpenAI)、安思罗匹克(Anthropic)、吉特哈布(GitHub)、杰米奈(Gemini)、
     robots 点 t x t(robots.txt)、I E T F、A I、A P I、M I T。
     say 里禁止出现波浪号、emoji、颜文字、括号注释（TTS 会读错或读出来）。
   - show：屏幕字幕，保留正确的英文原写法与数字，专业读者要一眼认出。
     show 里可以用「～」「！」「呀」「哦」等活泼表记。
5. **风格重点是整体语气，不是给每句套语气词**。当前最常见的失败是「每句结尾都加呀/哦/呢/啦」，
   看起来机械又假。请这样做：
   - 语气词只用在约 1/3 的句子里，禁止连续两句用同一个句尾语气词，禁止每句都有。
   - 多用口语动词和短串场替换书面连接词：「放大招」「超」「好厉害」「重点来啦」「接着看」、
     「一口气」「别忘了」「听我慢慢说」「是不是很酷」。串场要融进原句，不能另起新句子。
   - 允许调整句式顺序（比如把主语提前、把长句拆成两个短分句），但事实 token 一个都不能少。
   - 开场要像元气主播打招呼（仍须报日期和电台名），结尾轻快收尾（仍须提醒台本全文和原文链接）。
   - 禁止卖萌拟声词、禁止 emoji、禁止加任何与事实无关的新信息。
   下面是**本期台本里的真实句子**改写示范，请按这个力度改写全部句子：
     原 show：同一天，美团发布LongCat-2.5，总参数1.6万亿，是原生多模态模型。
     改 show：同一天美团也放大招啦！LongCat-2.5，总参数1.6万亿，是原生多模态模型哦～
     改 say ：同一天美团也放大招啦！长猫二点五，总参数一点六万亿，是原生多模态模型哦。
     原 show：训练全程用国产算力完成，强化了原生视觉理解和智能体编程能力。
     改 show：而且哦，训练全程用的可是国产算力，原生视觉理解和智能体编程也一起变强啦！
     改 say ：而且哦，训练全程用的可是国产算力，原生视觉理解和智能体编程也一起变强啦。
     原 show：网站在robots.txt里写一次__usage_ai-training标记，就能声明内容是否可用于生成式AI训练。
     改 show：网站只要在robots.txt里写一次__usage_ai-training标记，就能声明内容能不能用于生成式 A I 训练，超方便！
     改 say ：网站只要在 robots 点 t x t 里写一次标记，就能声明内容能不能用于生成式 A I 训练，超方便。
     原 show：今天的科技新鲜事就聊到这里，感谢收听小鲸电台。
     改 show：今天的科技新鲜事就聊到这儿啦，谢谢收听小鲸电台，明天也要来听哦～
     改 say ：今天的科技新鲜事就聊到这儿啦，谢谢收听小鲸电台，明天也要来听哦。
   **力度自检**：逐句对比你的输出与原句。若差异仅仅是「句尾多了呀/哦/呢/啦」或「句号换成！～」，
   就是不合格——每句至少要换掉一个书面词、或重排句式、或加一个短串场短语。
   差异小于 6 个字的句子请重写。
6. 开场要报出日期和电台名；结尾要提醒可以看台本全文和原文链接。
7. 输出严格 JSON（不要 markdown 代码块、不要解释文字）：
   {"headline": "元气一点的本期标题，20 字内",
    "00": [{"say":"...","show":"..."}], "01": [...], ...}
   键是话题 id，值的数组长度必须与输入一致。
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
        "temperature": 1.0,
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
    return json.loads(data["choices"][0]["message"]["content"])


# 人工定稿：模型对下面几句仍只加句尾语气词，这里再润色一次。
# 键为 "话题id:句中序号(0 起)"。事实 token 与 say 的英文读法必须与原文一致。
MANUAL_OVERRIDES = {
    # 用户手工指定的开场白（音频里念的是「小鲸电台」，与页面台名不同，待确认）
    "00:0": {
        "say": "观众朋友们好呀，今天是十一月六号，欢迎收听小鲸电台。",
        "show": "观众朋友们好呀，今天是11月6号，欢迎收听小鲸电台！",
    },
    "01:1": {
        "say": "代码打包成深度求索哈尼斯组件，还是 M I T 许可哦，路由器层专门负责分派任务呢。",
        "show": "代码打包成DeepSeek Harness组件，还是MIT许可哦，Router层专门负责分派任务呢～",
    },
    "03:1": {
        "say": "现场还搬出了内置一千二百亿参数 A I 模型的个人电脑，搭载的可是英伟达芯片哦。",
        "show": "现场还搬出了内置1200亿参数AI模型的个人电脑，搭载的可是英伟达芯片哦～",
    },
    "03:2": {
        "say": "更厉害的是新一代量子芯片！微软的目标是二零二九年前造出实用的量子计算机哦。",
        "show": "更厉害的是新一代量子芯片！微软的目标是2029年前造出实用的量子计算机哦～",
    },
    "04:2": {
        "say": "这份草案是安思罗匹克交给 I E T F 工作组的，目前还是个人草案，而且完全不影响搜索收录哦。",
        "show": "这份草案是Anthropic交给IETF工作组的，目前还是个人草案，而且完全不影响搜索收录哦～",
    },
    "99:0": {
        "say": "今天的科技新鲜事就聊到这儿啦，谢谢收听小鲸电台，明天也要来听哦。",
        "show": "今天的科技新鲜事就聊到这儿啦，谢谢收听小鲸电台，明天也要来听哦～",
    },
    "05:0": {
        "say": "接着看谷歌！计算机使用工具正式可用啦，一口气支持两类杰米奈 A P I 哦。",
        "show": "接着看谷歌！Computer Use工具正式可用啦，一口气支持两类Gemini API哦～",
    },
    "05:2": {
        "say": "不过客户端得自己准备执行环境和截图回传逻辑，碰到敏感动作还要等批准才行哦。",
        "show": "不过客户端得自己准备执行环境和截图回传逻辑，碰到敏感动作还要等批准才行哦～",
    },
    "99:1": {
        "say": "想细看哪条新闻，往下翻就有台本全文和原文链接，别忘了点开看看呀。",
        "show": "想细看哪条新闻，往下翻就有台本全文和原文链接，别忘了点开看看呀～",
    },
}


def apply_overrides(topics):
    n = 0
    for t in topics:
        for i, line in enumerate(t["lines"]):
            ov = MANUAL_OVERRIDES.get(f"{t['id']}:{i}")
            if ov:
                line.update(ov)
                n += 1
    return n


def fact_tokens(text: str):
    """从字幕里抽出必须保留的事实 token：数字串 + 英文/下划线专名。"""
    nums = set(re.findall(r"\d+(?:\.\d+)?", text))
    words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_.\-]*", text))
    return nums, words


def safe_line(old: dict, new: dict):
    """校验新句是否丢了事实；丢了就回退原文，返回 (结果, 是否回退)。"""
    if not isinstance(new, dict):
        return old, True
    say, show = (new.get("say") or "").strip(), (new.get("show") or "").strip()
    if not say or not show:
        return old, True
    on, ow = fact_tokens(old["show"])
    nn, nw = fact_tokens(show)
    missing = (on - nn) | (ow - nw)
    if missing:
        return old, True
    # say 里不许出现波浪号 / emoji（TTS 会读错）
    say = re.sub(r"[~\uFF5E]", "", say)
    return {"say": say, "show": show}, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-11-06")
    ap.add_argument("--tone", default="元气")
    ap.add_argument("--finalize", action="store_true",
                    help="不调 API，只应用人工润色并重新导出（定稿用）")
    args = ap.parse_args()

    path = ROOT / "episodes" / f"{args.date}-zh.json"
    ep = json.loads(path.read_text(encoding="utf-8"))
    topics = ep["topics"]

    reverted = 0
    if args.finalize:
        print("→ 跳过 API，应用人工润色并重新导出")
    else:
        payload = {
            t["id"]: [{"say": l["say"], "show": l["show"]} for l in t["lines"]]
            for t in topics
        }
        print(f"→ 调用 DeepSeek 改写 {sum(len(v) for v in payload.values())} 句台词（{args.tone}风）...")
        result = call_deepseek(get_api_key(), payload)

        for t in topics:
            arr = result.get(t["id"], [])
            for i, old in enumerate(t["lines"]):
                new, bad = safe_line(old, arr[i] if i < len(arr) else None)
                if bad:
                    reverted += 1
                    print(f"  ! [{t['id']}.{i+1:02d}] 事实 token 缺失或格式异常，保留原文")
                t["lines"][i] = dict(old, **new)   # 保留 start / end 等其它字段

        if result.get("headline"):
            ep["title"] = result["headline"]
            idx_path = ROOT / "episodes.json"
            if idx_path.exists():
                entries = json.loads(idx_path.read_text(encoding="utf-8"))
                for e in entries:
                    if e.get("date") == args.date:
                        e["title"] = ep["title"]
                idx_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    n_over = apply_overrides(topics)

    # 只有真正调 API 改了台词才标记「音频待替换」；--finalize 仅重导出，不动状态
    if not args.finalize:
        ep["audioStatus"] = "pending-replacement"
        ep["audioNote"] = "台本已改；audio/ 下仍是旧录音，替换音频后需重算 lines[].start/end"
    path.write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 导出 1：人类可读台本 ----
    out_lines = [
        f"小鲸电台 · {ep['title']}",
        f"{args.date} ｜ 中文 ｜ 台本 v2（{args.tone}版）",
        f"共 {len(topics)} 段 / {sum(len(t['lines']) for t in topics)} 句",
        "",
        f"配音：{ep.get('credits', {}).get('voice', '—')} ｜ 总时长：{ep['duration']:.2f}s",
        "时间轴以 episodes/*.json 为准；替换音频后运行 tools/relink_audio.py 重新对齐。",
        "",
    ]
    n = 0
    for t in topics:
        out_lines.append("━" * 46)
        out_lines.append(f"【{t['id']}】{t['title']}   ·   {t.get('kicker','')}")
        if t.get("url"):
            out_lines.append(f"  原文：{t['url']}")
        out_lines.append("")
        for i, l in enumerate(t["lines"], 1):
            n += 1
            out_lines.append(f"  {n:02d}  朗读｜{l['say']}")
            out_lines.append(f"      字幕｜{l['show']}")
        out_lines.append("")
    readable = ROOT / f"台本-{args.date}.txt"
    readable.write_text("\n".join(out_lines), encoding="utf-8")

    # ---- 导出 2：纯逐句朗读稿（无任何头部，方便整段粘进 TTS） ----
    tts = ROOT / f"台词-逐句-{args.date}.txt"
    tts.write_text(
        "\n".join(l["say"] for t in topics for l in t["lines"]) + "\n",
        encoding="utf-8",
    )

    print(f"✓ 台本已改写：{path}")
    print(f"  事实校验回退 {reverted} 句 ／ 人工润色 {n_over} 句")
    print(f"✓ 阅读版台本：{readable}")
    print(f"✓ 逐句朗读稿：{tts}")
    if not args.finalize:
        print("  提示：时间轴仍属旧音频，替换音频后运行 tools/relink_audio.py 重新对齐。")


if __name__ == "__main__":
    main()
