#!/usr/bin/env python3
"""Extract shot candidates and representative frames for video shot analysis."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def require_bin(name: str) -> None:
    proc = run(["/usr/bin/env", "bash", "-lc", f"command -v {name}"])
    if proc.returncode != 0:
        raise SystemExit(f"Missing required binary: {name}")


def ffprobe_duration(video: Path) -> float:
    proc = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ]
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "ffprobe failed")
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise SystemExit(f"Cannot parse video duration: {proc.stdout!r}") from exc


def detect_scene_times(video: Path, threshold: float) -> list[float]:
    vf = f"select='gt(scene,{threshold})',showinfo"
    proc = run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", vf, "-f", "null", "-"])
    text = proc.stderr or ""
    times = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", text):
        times.append(float(match.group(1)))
    return sorted(set(times))


def dedupe_times(times: list[float], duration: float, min_gap: float) -> list[float]:
    cleaned = [0.0]
    for t in sorted(times):
        if 0.0 < t < duration and t - cleaned[-1] >= min_gap:
            cleaned.append(t)
    if duration - cleaned[-1] >= 0.08:
        cleaned.append(duration)
    else:
        cleaned[-1] = duration
    return cleaned


def fallback_times(duration: float, interval: float) -> list[float]:
    if interval <= 0:
        interval = 2.0
    count = max(1, math.ceil(duration / interval))
    points = [min(i * interval, duration) for i in range(count)]
    if points[0] != 0:
        points.insert(0, 0.0)
    if points[-1] < duration:
        points.append(duration)
    return points


def limit_segments(bounds: list[float], max_shots: int) -> list[float]:
    segment_count = max(0, len(bounds) - 1)
    if max_shots <= 0 or segment_count <= max_shots:
        return bounds
    step = math.ceil(segment_count / max_shots)
    kept = [bounds[0]]
    for i in range(step, segment_count, step):
        kept.append(bounds[i])
    if kept[-1] != bounds[-1]:
        kept.append(bounds[-1])
    return kept


def fmt_time(seconds: float) -> str:
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def extract_frame(video: Path, timestamp: float, output: Path, width: int) -> None:
    scale = f"scale='min({width},iw)':-2"
    proc = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            scale,
            "-q:v",
            "2",
            str(output),
        ]
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or f"Failed to extract {output}")


def write_prompt(out_dir: Path, rows: list[dict[str, object]], video: Path) -> None:
    lines = [
        "# 拉片分析工作稿",
        "",
        f"- 视频：{video}",
        f"- 镜头候选数：{len(rows)}",
        "",
        "逐张查看 `frame_path`，补全概述、叙事作用、景别、运镜、声音/字幕、倒推提示词，再写入飞书 Base。",
        "",
    ]
    for row in rows:
        lines.append(
            f"{row['镜头序号']}. {row['起止时间码']} / {row['时长']}s / {row['frame_path']}"
        )
    (out_dir / "analysis_prompt.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract shot candidates from a video.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("lapian_output"))
    parser.add_argument("--threshold", type=float, default=0.32)
    parser.add_argument("--min-gap", type=float, default=0.45)
    parser.add_argument("--fallback-interval", type=float, default=2.0)
    parser.add_argument("--max-shots", type=int, default=160)
    parser.add_argument("--width", type=int, default=720)
    args = parser.parse_args()

    require_bin("ffmpeg")
    require_bin("ffprobe")

    video = args.video.expanduser().resolve()
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")

    out_dir = args.out_dir.expanduser().resolve()
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    duration = ffprobe_duration(video)
    detected = detect_scene_times(video, args.threshold)
    if len(detected) < 1:
        bounds = fallback_times(duration, args.fallback_interval)
        detection_mode = "fallback_interval"
    else:
        bounds = dedupe_times(detected, duration, args.min_gap)
        detection_mode = "scene_detection"
    bounds = limit_segments(bounds, args.max_shots)

    rows: list[dict[str, object]] = []
    for idx, (start, end) in enumerate(zip(bounds[:-1], bounds[1:]), start=1):
        if end <= start:
            continue
        mid = start + (end - start) / 2
        frame = frames_dir / f"shot_{idx:03d}.jpg"
        extract_frame(video, mid, frame, args.width)
        rows.append(
            {
                "镜头序号": idx,
                "起止时间码": f"{fmt_time(start)} - {fmt_time(end)}",
                "时长": round(end - start, 2),
                "frame_path": str(frame),
                "概述": "",
                "叙事作用": "",
                "景别": "",
                "画面元素": "",
                "镜头运动": "",
                "转场/剪辑": "",
                "字幕/台词": "",
                "声音/音乐": "",
                "情绪/节奏": "",
                "视觉风格": "",
                "倒推生成分镜提示词": "",
                "倒推生成视频提示词": "",
                "备注/置信度": "",
            }
        )

    meta = {
        "video": str(video),
        "duration": round(duration, 3),
        "detection_mode": detection_mode,
        "threshold": args.threshold,
        "min_gap": args.min_gap,
        "shot_count": len(rows),
    }
    (out_dir / "shots.json").write_text(
        json.dumps({"meta": meta, "shots": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (out_dir / "shots.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["镜头序号"])
        writer.writeheader()
        writer.writerows(rows)

    write_prompt(out_dir, rows, video)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
