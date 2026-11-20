#!/usr/bin/env python3
"""Measure real frame intervals in a rendered packaged match on macOS."""
import argparse
import csv
import math
from pathlib import Path
import statistics
import subprocess
import sys

DEFAULT_APP = Path(__file__).resolve().parents[1] / "Build/Packaged/Mac/HeatCheck.app"
BUDGET = 1000 / 120


def capture(args):
    binary = args.app / "Contents/MacOS/HeatCheck"
    command = [
        str(binary), "-windowed", "-ResX=1920", "-ResY=1080", "-ForceRes",
        "-NoVSync", "-FixedSeed", "-hcautopilot" if args.player else "-hcwatch",
        "-ExitAfterCsvProfiling",
    ]
    if args.match:
        command.extend(["-hcprofilematch", "-hcquarter=1"])
    else:
        command.append(f"-csvCaptureFrames={args.frames}")
    path = None
    scored = False
    finished = False
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors="replace") as game:
        for line in game.stdout:
            if "Capture Ended. Writing CSV to file :" in line:
                path = Path(line.split("Writing CSV to file :", 1)[1].strip())
            if "EVENT [" in line and "SCORE " in line:
                scored = True
            if "EVENT [" in line and any(event in line for event in ("Quarter end", "GAME OVER", "ON FIRE")):
                print(line[line.index("EVENT ["):].strip(), flush=True)
            if "GAME OVER " in line:
                finished = True
        if game.wait() or not path or not scored or (args.match and not finished):
            sys.exit("Capture did not complete with a scored basket. Check the game log.")
    return path


def report(path, warmup, expected):
    csv.field_size_limit(sys.maxsize)
    times = []
    gpu_times = []
    with path.open(newline="") as source:
        for row in csv.DictReader(source):
            try:
                value = float(row["FrameTime"])
            except (TypeError, ValueError):
                continue  # repeated CSV header and trailing Unreal metadata
            times.append(value)
            if len(times) > warmup:
                gpu = float(row.get("GPUTime") or 0)
                if gpu > 0:
                    gpu_times.append(gpu)
    if (expected is not None and len(times) != expected) or len(times) <= warmup:
        sys.exit(f"Incomplete capture ({len(times)} frames).")
    frames = sorted(times[warmup:])
    print(f"{path}\n{len(frames)} measured frames after {warmup} warm-up frames")
    print(f"Mean throughput {1000 / statistics.mean(frames):.1f} FPS")
    for q in (0.5, 0.95, 0.99):
        print(f"p{100*q:.0f} frame time {frames[math.ceil(q * len(frames))-1]:.2f} ms")
    if gpu_times:
        print(f"Median GPU time {statistics.median(gpu_times):.2f} ms")
    on_time = sum(v <= BUDGET for v in frames)
    print(f"Within {BUDGET:.2f} ms: {100 * on_time / len(frames):.1f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=DEFAULT_APP)
    parser.add_argument("--match", action="store_true", help="capture tip-off through game over, one-minute quarters")
    parser.add_argument("--frames", type=int, default=3600)
    parser.add_argument("--warmup", type=int, default=600)
    parser.add_argument("--player", action="store_true", help="play through the one-player controls")
    args = parser.parse_args()
    if not args.match and not 0 <= args.warmup < args.frames:
        parser.error("warmup must be nonnegative and smaller than frames")
    report(capture(args), 0 if args.match else args.warmup, None if args.match else args.frames)
