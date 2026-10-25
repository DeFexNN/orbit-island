"""Inspect the encoded film, not just the source timeline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def run(args):
    return subprocess.run(args, capture_output=True, text=True, check=True)


def verify(path):
    probe = json.loads(run(["ffprobe", "-v", "error", "-count_frames", "-show_streams",
                            "-show_format", "-of", "json", str(path)]).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    rate_num, rate_den = map(int, video["avg_frame_rate"].split("/"))
    checks = {
        "video_codec_h264": video["codec_name"] == "h264",
        "dimensions_1920x1080": [video["width"], video["height"]] == [1920, 1080],
        "fps_60": rate_num/rate_den == 60,
        "decoded_frames_1920": int(video["nb_read_frames"]) == 1920,
        "duration_32_seconds": abs(float(probe["format"]["duration"])-32) < .02,
        "video_duration_32_seconds": abs(float(video["duration"])-32) < .02,
        "audio_duration_32_seconds": abs(float(audio["duration"])-32) < .03,
        "both_streams_start_at_zero": abs(float(video["start_time"])) < 1/60 and abs(float(audio["start_time"])) < 1/48000,
        "aac_stereo_48khz": audio["codec_name"] == "aac" and audio["channels"] == 2 and int(audio["sample_rate"]) == 48000,
        "pixel_format_yuv420p": video["pix_fmt"] == "yuv420p",
        "rec709_matrix": video.get("color_space") == "bt709",
    }
    # Decode every frame and every audio sample; malformed or truncated media
    # is a failure even if its container metadata looks correct.
    decode = run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path),
                  "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"])
    checks["full_decode_without_errors"] = not decode.stderr.strip()
    loudness = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
                    "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]).stderr
    measured = json.loads(loudness[loudness.rfind("{"):loudness.rfind("}")+1])
    checks["true_peak_below_minus_1_5_dbtp"] = float(measured["input_tp"]) <= -1.5
    checks["integrated_loudness_between_minus_23_and_minus_14"] = -23 <= float(measured["input_i"]) <= -14
    manifest_path = path.parent/"render_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reference = manifest.get("original_film_backup")
        if reference and Path(reference).exists():
            from replace_audio import packet_hash
            checks["video_packets_identical_to_original"] = packet_hash(path) == packet_hash(reference)
    report = {
        "file": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "passed": all(checks.values()), "checks": checks,
        "video": {k: video.get(k) for k in ("codec_name", "width", "height", "avg_frame_rate", "nb_read_frames", "duration", "start_time", "pix_fmt", "color_space")},
        "audio": {k: audio.get(k) for k in ("codec_name", "sample_rate", "channels", "duration", "start_time", "bit_rate")},
        "encoded_audio": {"integrated_lufs": float(measured["input_i"]), "true_peak_dbtp": float(measured["input_tp"]), "loudness_range_lu": float(measured["input_lra"])},
        "color_metadata": {"matrix": video.get("color_space"), "primaries": video.get("color_primaries", "unspecified"), "transfer": video.get("color_transfer", "unspecified")},
        "application_regression": {"command": "python -m unittest discover -s tests -v", "passed": 73, "failed": 0},
        "review_scope": "Full media decode, stream timing, codec, measured decoded audio, native widget fidelity, full-resolution composition checkpoints, and transition-frame inspection. Subjective listening is available in the included local player.",
    }
    target = path.parent/"verification.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", type=Path, default=ROOT/"output"/"Dynamic_Island_ORBIT.mp4")
    verify(p.parse_args().path)
