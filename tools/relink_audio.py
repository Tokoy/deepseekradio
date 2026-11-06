#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把用户手工生成的一整段配音接入番组：转码 + 重新对齐 19 句时间轴。

整段 TTS 没有逐句时间戳，所以这里用「文本字数 × 静音锚点」的动态规划做近似强制对齐：
  1. 20ms 窗口算 RMS，找出所有 ≥0.25s 的静音段，取中点作候选句边界。
  2. DP 选 18 个边界，使每句的「有声时长 / 有效字数」尽量一致（语速一致），
     并优先把边界放在更长的静音上。
  3. 段内再找首个/末个有声窗口，得到更贴合发音的 start / end。
比单纯按静音切分或按字数均分都准，且不依赖任何第三方库。

依赖：系统自带 afconvert + lame（本机 ffmpeg 已损坏，刻意不用）。

用法：
  python3 tools/relink_audio.py --input "/path/to/配音.wav"
  python3 tools/relink_audio.py --input "/path/to/配音.m4a" --voice "MiniMax 漫游少女"
"""
import argparse
import json
import math
import re
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEP = 0.02          # RMS 窗口 20ms
MIN_SILENCE = 0.25   # 候选句边界的最短静音


def to_pcm_wav(src: Path, dst: Path) -> None:
    """任意 CoreAudio 可读格式 → 44.1k / 16bit / mono WAV。"""
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16@44100", "-c", "1",
         str(src), str(dst)],
        check=True, capture_output=True,
    )


def read_pcm(path: Path):
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, "需要单声道 16bit WAV"
        data = w.readframes(w.getnframes())
    return struct.unpack("<%dh" % (len(data) // 2), data), sr


def rms_envelope(samples, sr):
    win = max(1, int(sr * STEP))
    rms = []
    for i in range(0, len(samples) - win, win):
        seg = samples[i:i + win]
        rms.append(math.sqrt(sum(v * v for v in seg) / len(seg)))
    return rms, win / sr


def pick_threshold(rms):
    s = sorted(rms)
    return max(35.0, s[int(len(s) * 0.20)] * 2.0)


def find_silences(rms, step, th):
    quiet = [v < th for v in rms]
    segs, st = [], None
    for i, q in enumerate(quiet):
        if q and st is None:
            st = i
        if not q and st is not None:
            segs.append((st * step, i * step))
            st = None
    if st is not None:
        segs.append((st * step, len(quiet) * step))
    return [(a, b) for a, b in segs if b - a >= MIN_SILENCE]


def eff_chars(say):
    """有效发音字数：去掉空白与标点，英文字母逐字计。"""
    return len(re.sub(r"[\s，。！？、～,.!?;；：:\-]", "", say or ""))


def align(rms, step, th, dur, chars):
    sils = find_silences(rms, step, th)
    # 候选边界 = 静音中点；记录该处静音长度用于给 DP 加权
    B = [0.0]
    gap = [0.0]
    for a, b in sils:
        mid = (a + b) / 2
        if 0.35 < mid < dur - 0.35:
            B.append(mid)
            gap.append(b - a)
    B.append(dur)
    gap.append(0.0)
    m = len(B)

    voiced = [1 if v >= th else 0 for v in rms]
    pref = [0] * (len(voiced) + 1)
    for i, v in enumerate(voiced):
        pref[i + 1] = pref[i] + v

    def voiced_dur(t0, t1):
        i0 = max(0, min(len(voiced), int(t0 / step)))
        i1 = max(0, min(len(voiced), int(t1 / step)))
        return (pref[i1] - pref[i0]) * step

    n = len(chars)
    total_chars = max(1, sum(chars))
    rate = voiced_dur(0, dur) / total_chars
    path = None

    for _ in range(4):                       # 迭代重估平均语速
        INF = float("inf")
        dp = [[INF] * m for _ in range(n + 1)]
        pre = [[-1] * m for _ in range(n + 1)]
        dp[0][0] = 0.0
        for j in range(1, n + 1):
            for i in range(j, m):
                for k in range(j - 1, i):
                    if dp[j - 1][k] == INF:
                        continue
                    d = voiced_dur(B[k], B[i])
                    c = chars[j - 1]
                    if c <= 0 or d < 0.8:   # 一句话不可能短于 0.8 秒有声
                        continue
                    cost = (d / c - rate) ** 2 - 0.00012 * min(1.0, gap[k] / 0.6)
                    v = dp[j - 1][k] + cost
                    if v < dp[j][i]:
                        dp[j][i] = v
                        pre[j][i] = k
        if dp[n][m - 1] == INF:
            return None, None, None
        cur, p = m - 1, [m - 1]
        for j in range(n, 0, -1):
            k = pre[j][cur]
            if k < 0:
                return None, None, None
            p.append(k)
            cur = k
        p.reverse()
        path = p
        ds = [voiced_dur(B[p[j]], B[p[j + 1]]) for j in range(n)]
        rate = sum(ds) / total_chars

    def voiced_bounds(t0, t1):
        i0, i1 = int(t0 / step), int(t1 / step)
        first = last = None
        for i in range(max(0, i0), min(len(rms), i1)):
            if rms[i] >= th:
                if first is None:
                    first = i
                last = i
        if first is None:
            return t0, t1
        return max(0.0, first * step - 0.04), min(dur, (last + 1) * step + 0.06)

    spans = [voiced_bounds(B[path[j]], B[path[j + 1]]) for j in range(n)]
    return spans, sils, B


def export_texts(ep, date):
    topics = ep["topics"]
    out = [
        f"小鲸电台 · {ep['title']}",
        f"{date} ｜ 中文 ｜ 台本 v2（元气版）",
        f"共 {len(topics)} 段 / {sum(len(t['lines']) for t in topics)} 句",
        "",
        f"配音：{ep.get('credits', {}).get('voice', '—')}",
        f"总时长：{ep['duration']:.2f}s ｜ 时间轴已按新音频重新对齐",
        "",
    ]
    n = 0
    for t in topics:
        out.append("━" * 46)
        out.append(f"【{t['id']}】{t['title']}   ·   {t.get('kicker', '')}")
        if t.get("url"):
            out.append(f"  原文：{t['url']}")
        out.append("")
        for l in t["lines"]:
            n += 1
            out.append(f"  {n:02d}  {l['start']:6.2f}–{l['end']:6.2f}s")
            out.append(f"      朗读｜{l['say']}")
            out.append(f"      字幕｜{l['show']}")
        out.append("")
    (ROOT / f"台本-{date}.txt").write_text("\n".join(out), encoding="utf-8")
    (ROOT / f"台词-逐句-{date}.txt").write_text(
        "\n".join(l["say"] for t in topics for l in t["lines"]) + "\n",
        encoding="utf-8",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="用户生成的整段配音文件")
    ap.add_argument("--date", default="2026-11-06")
    ap.add_argument("--voice", default="MiniMax 漫游少女")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.exists():
        raise SystemExit(f"找不到音频：{src}")
    ep_path = ROOT / "episodes" / f"{args.date}-zh.json"
    ep = json.loads(ep_path.read_text(encoding="utf-8"))
    topics = ep["topics"]
    lines = [l for t in topics for l in t["lines"]]
    chars = [eff_chars(l["say"]) for l in lines]

    tmp = Path(tempfile.mkdtemp(prefix="dsrelink-"))
    try:
        pcm = tmp / "pcm.wav"
        print(f"→ 转码并分析音频：{src.name}")
        to_pcm_wav(src, pcm)
        samples, sr = read_pcm(pcm)
        rms, step = rms_envelope(samples, sr)
        th = pick_threshold(rms)
        dur = len(samples) / sr
        print(f"  时长 {dur:.2f}s ｜ 采样 {sr}Hz ｜ 静音阈值 RMS {th:.0f}")

        spans, sils, B = align(rms, step, th, dur, chars)
        if spans is None:
            raise SystemExit("对齐失败：找不到能分成 19 句的边界，建议逐句生成音频或加大句间停顿")
        print(f"  候选静音 {len(sils)} 段 / 边界 {len(B)} 个 → 已选出 {len(lines)} 句")

        for l, (a, b) in zip(lines, spans):
            l["start"] = round(a, 3)
            l["end"] = round(b, 3)
        for t in topics:
            t["start"] = t["lines"][0]["start"]
            t["end"] = t["lines"][-1]["end"]
        ep["duration"] = round(dur, 3)
        ep["credits"]["voice"] = args.voice
        ep.pop("audioStatus", None)
        ep.pop("audioNote", None)

        out_mp3 = ROOT / "audio" / f"{args.date}-zh.mp3"
        subprocess.run(
            ["lame", "--silent", "-b", "64", "-m", "m", str(pcm), str(out_mp3)],
            check=True, capture_output=True,
        )
        ep_path.write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")
        export_texts(ep, args.date)

        print(f"✓ 音频：{out_mp3}  {out_mp3.stat().st_size / 1024:.0f} KB")
        print(f"✓ 时间轴已写回：{ep_path}")
        print("  句  字数  起–止")
        for i, (l, c) in enumerate(zip(lines, chars), 1):
            print(f"  {i:02d}  {c:3d}   {l['start']:6.2f}–{l['end']:6.2f}s  {l['show'][:26]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
