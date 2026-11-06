#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐句合成语音 → 拼成一期 mp3 → 把精确时间轴写回台本 JSON。

对齐 myradio 的做法：不做语音识别、不做强制对齐，
而是「一句一句分别合成、量出时长、累加」，所以每句起止时间天然准确。

依赖（全部是系统已有工具，不额外安装）：
  macOS say、afconvert、lame、Python 3 标准库
注：本机 ffmpeg 7.1.1 因 x265 动态库版本不匹配而损坏，此处刻意不依赖它。

用法：
  python3 tools/build_audio.py
  python3 tools/build_audio.py --date 2026-11-06 --voice Tingting --rate 190
"""
import argparse
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_RATE = 44100
GAP_LINE = 0.22      # 句间停顿（秒）
GAP_TOPIC = 0.52     # 话题间停顿（秒）


def synth_one(text: str, out_aiff: Path, voice: str, rate: int) -> None:
    subprocess.run(
        ["say", "-v", voice, "-r", str(rate), "-o", str(out_aiff), text],
        check=True, capture_output=True,
    )


def to_wav(src: Path, dst: Path) -> None:
    # macOS 自带，避开本机已损坏的 ffmpeg
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1",
         str(src), str(dst)],
        check=True, capture_output=True,
    )


def wav_frames(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SAMPLE_RATE, f"采样率不符: {path}"
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        return w.readframes(w.getnframes())


def silence(seconds: float) -> bytes:
    n = int(SAMPLE_RATE * seconds)
    return b"\x00\x00" * n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-11-06")
    ap.add_argument("--voice", default="Tingting")
    ap.add_argument("--rate", type=int, default=190)
    args = ap.parse_args()

    ep_path = ROOT / "episodes" / f"{args.date}-zh.json"
    episode = json.loads(ep_path.read_text(encoding="utf-8"))
    mp3_path = ROOT / "audio" / f"{args.date}-zh.mp3"
    mp3_path.parent.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="dsradio-"))
    chunks = []          # PCM 片段
    cursor = 0.0         # 当前累计秒数

    try:
        for ti, topic in enumerate(episode["topics"]):
            topic_start = cursor
            for li, line in enumerate(topic["lines"]):
                aiff = tmp / f"t{ti:02d}l{li:02d}.aiff"
                wavf = tmp / f"t{ti:02d}l{li:02d}.wav"
                synth_one(line["say"], aiff, args.voice, args.rate)
                to_wav(aiff, wavf)
                pcm = wav_frames(wavf)

                start = cursor
                chunks.append(pcm)
                cursor += len(pcm) / 2 / SAMPLE_RATE
                end = cursor
                line["start"] = round(start, 3)
                line["end"] = round(end, 3)

                if li < len(topic["lines"]) - 1:
                    chunks.append(silence(GAP_LINE))
                    cursor += GAP_LINE
                print(f"  [{ti:02d}.{li:02d}] {start:6.2f}–{end:6.2f}s  {line['show'][:28]}")

            topic["start"] = round(topic_start, 3)
            topic["end"] = round(cursor, 3)
            if ti < len(episode["topics"]) - 1:
                chunks.append(silence(GAP_TOPIC))
                cursor += GAP_TOPIC

        # 尾部留一点余韵
        chunks.append(silence(0.35))
        cursor += 0.35
        episode["duration"] = round(cursor, 3)

        full_wav = tmp / "full.wav"
        with wave.open(str(full_wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(b"".join(chunks))

        subprocess.run(
            ["lame", "--silent", "-b", "64", "-m", "m", str(full_wav), str(mp3_path)],
            check=True, capture_output=True,
        )

        # 换声音时同步更新署名，避免页脚还写着旧音色
        if isinstance(episode.get("credits"), dict):
            episode["credits"]["voice"] = f"macOS 本地语音合成 · {args.voice}"
        ep_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
        size_kb = mp3_path.stat().st_size / 1024
        print(f"✓ 音频：{mp3_path}  {cursor:.1f}s / {size_kb:.0f} KB")
        print(f"✓ 时间轴已写回：{ep_path}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
