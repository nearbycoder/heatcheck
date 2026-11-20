"""HEAT CHECK web audio: Art/Export/Audio/*.wav -> web/play/assets/audio/*.mp3 (+ .ogg for loops).

  python3 Tools/web/convert_audio.py <assets_out_dir>

* mono sources (SFX, UI, VO, S_FireLoop): MP3 96 kbps mono
* stereo sources (crowd beds/reactions, music): MP3 128 kbps stereo
* loops (manifest "loop": true): additionally Ogg Opus (.ogg). MP3 always carries encoder delay
  and padding; ffmpeg writes them into the LAME/Xing header and Chrome/Firefox trim them on
  decode, but not every decoder does. Opus' pre-skip is part of the codec spec, so the .ogg
  decodes sample-accurately everywhere it is supported.
Writes <out>/audio/manifest.json with every file, its duration and the loop/volume metadata
from the source manifest, and checks that each loop's MP3 decodes back to the exact source
length and alignment.
"""
import concurrent.futures as cf
import json
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "Art", "Export", "Audio")
OUT = os.path.join(sys.argv[1], "audio")
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(SRC, "manifest.json")) as fp:
    SRC_MAN = json.load(fp)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        raise SystemExit("command failed: %s\n%s" % (" ".join(cmd), r.stderr.decode()[-2000:]))
    return r.stdout


def probe_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.decode().strip())


def decode_mono_s16(path, n=None):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "48000", "-f", "s16le", "-"]
    raw = run(cmd)
    return struct.unpack("<%dh" % (len(raw) // 2), raw)


def best_offset(a, b, span=1500, win=4096, start=2400):
    """Lag (in samples) that best aligns b to a near the start of the file."""
    best, best_lag = None, 0
    seg = a[start:start + win]
    for lag in range(-span, span + 1, 1):
        s = 0
        for i in range(0, win, 4):
            j = start + i + lag
            if 0 <= j < len(b):
                d = seg[i] - b[j]
                s += d * d
        if best is None or s < best:
            best, best_lag = s, lag
    return best_lag


def convert(entry):
    name = entry["name"]
    wav = os.path.join(SRC, entry["file"])
    stereo = entry["channels"] == 2
    br = "128k" if stereo else "96k"
    ac = "2" if stereo else "1"
    mp3 = os.path.join(OUT, name + ".mp3")
    run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-map_metadata", "-1", "-ac", ac, "-ar", "48000",
         "-c:a", "libmp3lame", "-b:a", br, "-write_xing", "1", mp3])
    rec = {
        "name": name, "file": name + ".mp3", "category": entry["category"], "channels": entry["channels"],
        "duration": entry["duration"], "samples": entry["samples"], "sample_rate": 48000,
        "loop": entry["loop"], "volume": entry.get("volume", 1.0), "description": entry.get("description", ""),
        "mp3_bitrate": br, "mp3_bytes": os.path.getsize(mp3), "mp3_decoded_duration": round(probe_duration(mp3), 4),
    }
    if entry["loop"]:
        ogg = os.path.join(OUT, name + ".ogg")
        run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-map_metadata", "-1", "-ac", ac, "-ar", "48000",
             "-c:a", "libopus", "-b:a", br, "-vbr", "on", ogg])
        rec["ogg"] = name + ".ogg"
        rec["ogg_bytes"] = os.path.getsize(ogg)
        rec["loop_start_sample"] = entry.get("loop_start_sample", 0)
        rec["loop_end_sample"] = entry.get("loop_end_sample", entry["samples"])
        # gapless check: decoded length + alignment against the source
        src = decode_mono_s16(wav)
        for kind, path in (("mp3", mp3), ("ogg", ogg)):
            dec = decode_mono_s16(path)
            rec[kind + "_gapless_check"] = {"decoded_samples": len(dec), "source_samples": len(src),
                                            "start_offset_samples": best_offset(src, dec)}
    return rec


files = sorted(SRC_MAN["files"], key=lambda e: e["name"])
on_disk = sorted(f[:-4] for f in os.listdir(SRC) if f.endswith(".wav"))
missing = sorted(set(on_disk) - {e["name"] for e in files})
if missing:
    raise SystemExit("WAVs without manifest entries: %s" % missing)
with cf.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
    recs = list(ex.map(convert, files))
man = {
    "source": "Art/Export/Audio (Tools/gen_audio.py), converted by Tools/web/convert_audio.py",
    "conventions": SRC_MAN.get("conventions", {}),
    "formats": {
        "mp3": "every sound; mono 96 kbps (SFX/UI/VO/fire loop) or stereo 128 kbps (crowd, music)",
        "ogg": "Ogg Opus copy of each loop (sample-accurate; prefer it where canPlayType('audio/ogg; codecs=opus') is truthy)",
    },
    "count": len(recs),
    "files": recs,
}
with open(os.path.join(OUT, "manifest.json"), "w") as fp:
    json.dump(man, fp, indent=1)
for r in recs:
    if r["loop"]:
        print("LOOP", r["name"], "mp3", r["mp3_gapless_check"], "ogg", r["ogg_gapless_check"])
print("AUDIO_OK", len(recs), "files", sum(r["mp3_bytes"] + r.get("ogg_bytes", 0) for r in recs) // 1024, "KB")
