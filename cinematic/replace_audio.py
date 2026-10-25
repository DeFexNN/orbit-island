"""Replace only the film soundtrack, preserving the compressed video packets.

The first original stays in output/previous/. The default MP4 is updated only
after FFmpeg succeeds and a video-packet SHA256 comparison passes.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
VIDEO = ROOT / "output" / "Dynamic_Island_ORBIT.mp4"
AUDIO = ROOT / "audio" / "soundtrack.wav"


def packet_hash(path):
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c:v", "copy",
         "-f", "hash", "-hash", "sha256", "-"],
        check=True, capture_output=True, text=True).stdout.strip()


def main():
    original = VIDEO.parent / "previous" / "Dynamic_Island_ORBIT_original_sound.mp4"
    original.parent.mkdir(exist_ok=True)
    if not original.exists():
        shutil.copy2(VIDEO, original)
    before = packet_hash(VIDEO)
    temporary = VIDEO.with_name("Dynamic_Island_ORBIT_audio_update.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(VIDEO),
         "-i", str(AUDIO), "-map", "0:v:0", "-map", "1:a:0", "-map_metadata", "0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
         "-t", "32", "-movflags", "+faststart", "-metadata",
         "comment=Original film; revised clean tonal transitions and original score. Offline native UI demo.",
         str(temporary)], check=True)
    after = packet_hash(temporary)
    if before != after:
        raise RuntimeError("Video packet hash changed; original film has been preserved")
    temporary.replace(VIDEO)
    revised = VIDEO.with_name("Dynamic_Island_ORBIT_v2.mp4")
    shutil.copy2(VIDEO, revised)
    manifest_path = VIDEO.parent / "render_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.update({
        "sha256": hashlib.sha256(VIDEO.read_bytes()).hexdigest(),
        "audio_revision": "Clean tonal glides and resonant glass accents; noise-based transition sweeps removed",
        "audio": "Original stereo synthesis; revised tonal transitions; no third-party recordings",
        "video_packets_preserved": True,
        "video_packet_sha256": before.split("=")[-1],
        "original_film_backup": str(original),
        "revised_delivery_file": str(revised),
    })
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"file": str(revised), "canonical_file": str(VIDEO), "video_packets_preserved": True,
                      "video_packet_hash": before, "original_backup": str(original)}, indent=2))


if __name__ == "__main__":
    main()
