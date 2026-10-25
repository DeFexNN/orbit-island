"""Build public release assets from tracked source and the approved film.

Run after committing: python tools/build_release.py
No local logs, environments, internal captures, or historical backups are copied.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release-assets"


def public_report(value):
    """Keep verification data while removing machine-specific absolute paths."""
    if isinstance(value, dict):
        return {k: public_report(v) for k, v in value.items()
                if k not in {"original_film_backup", "revised_delivery_file"}}
    if isinstance(value, list):
        return [public_report(x) for x in value]
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        prefix = ROOT.as_posix().rstrip("/") + "/"
        if normalized.casefold().startswith(prefix.casefold()):
            return normalized[len(prefix):]
    return value


def main():
    OUT.mkdir(exist_ok=True)
    film = ROOT / "cinematic/output/Dynamic_Island_ORBIT.mp4"
    audio = ROOT / "cinematic/audio/soundtrack.wav"
    for path in (film, audio):
        if not path.exists():
            raise SystemExit(f"Missing generated artifact: {path.relative_to(ROOT)}")
    verification = ROOT / "cinematic/output/verification.json"
    report = json.loads(verification.read_text(encoding="utf-8"))
    if not report.get("passed"):
        raise SystemExit("Run cinematic/verify.py successfully before packaging")
    if report["sha256"] != hashlib.sha256(film.read_bytes()).hexdigest():
        raise SystemExit("The film changed after verification")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    tracked = [p for p in tracked if p]
    if not tracked:
        raise SystemExit("No tracked source files")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    public_video = OUT / "ORBIT-Cinematic-Intro.mp4"
    public_audio = OUT / "ORBIT-Soundtrack.wav"
    shutil.copy2(film, public_video)
    shutil.copy2(audio, public_audio)
    package = OUT / "ORBIT-Project.zip"
    generated = [
        film, audio,
        ROOT / "cinematic/audio/soundtrack_preview.m4a",
        ROOT / "cinematic/audio/soundtrack_metrics.json",
        ROOT / "cinematic/audio/transition_comparison.json",
        ROOT / "cinematic/output/render_manifest.json",
        verification,
        ROOT / "cinematic/output/storyboard.jpg",
        ROOT / "cinematic/output/frames/frame_28.5.png",
    ]
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative in tracked:
            path = ROOT / relative
            if not path.is_file():
                raise RuntimeError(f"Tracked source is missing: {relative}")
            archive.write(path, "orbit-island/" + relative)
        for path in generated:
            relative = path.relative_to(ROOT).as_posix()
            name = "orbit-island/" + relative
            if path.suffix == ".json":
                cleaned = public_report(json.loads(path.read_text(encoding="utf-8")))
                archive.writestr(name, json.dumps(cleaned, indent=2))
            else:
                archive.write(path, name)
        archive.writestr("orbit-island/SOURCE-REVISION.txt", revision + "\n")
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Release archive integrity check failed")
        names = archive.namelist()
        forbidden = ("/previous/", "/previous_sound/", "/.venv", "/__pycache__/", "/.git/", "/shots/", "/designs/")
        if any(any(part in name for part in forbidden) for name in names):
            raise RuntimeError("A private or generated-history directory entered the release")
    (OUT / "verification.json").write_text(json.dumps(public_report(report), indent=2), encoding="utf-8")
    assets = [public_video, public_audio, package, OUT / "verification.json"]
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in assets)
    (OUT / "SHA256SUMS.txt").write_text(sums, encoding="ascii")
    print(json.dumps({"revision": revision, "assets": [{"name":p.name,"bytes":p.stat().st_size} for p in assets],
                      "source_files":len(tracked),"archive_integrity":"passed"}, indent=2))


if __name__ == "__main__":
    main()
