"""Package a self-contained, reproducible project without logs or caches."""
from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parent
APP = ROOT.parent
OUT = ROOT / "output" / "ORBIT_project.zip"


def main():
    files = list(APP.glob("*.py")) + [APP / "requirements.txt"]
    files += list((APP / "tests").glob("test_*.py"))
    files += list(ROOT.glob("*.py")) + list(ROOT.glob("*.md"))
    files += [ROOT / "index.html", ROOT / "requirements-cinematic.txt"]
    files += [ROOT / "audio" / name for name in
              ("sound_design.py", "soundtrack.wav", "soundtrack_preview.m4a",
               "soundtrack_metrics.json", "transition_comparison.json", "CUE_SHEET.md", "LICENSE.txt")]
    files += [ROOT / "output" / name for name in
              ("Dynamic_Island_ORBIT.mp4", "render_manifest.json", "verification.json", "storyboard.jpg")]
    files += list((ROOT / "output" / "frames").glob("*.png"))
    files = sorted(set(p for p in files if p.is_file()))
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("START_HERE.md", "# ORBIT project\n\nOpen cinematic/README.md for the film, source, rebuild commands and fidelity notes.\n\nThe application Python files are an unmodified capture-time snapshot.\nThe film is cinematic/output/Dynamic_Island_ORBIT.mp4.\n")
        for path in files:
            archive.write(path, path.relative_to(APP).as_posix())
    with zipfile.ZipFile(OUT) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Archive integrity failed: {bad}")
    print(json.dumps({"file": str(OUT), "bytes": OUT.stat().st_size,
                      "files": len(files)+1, "integrity": "passed"}, indent=2))


if __name__ == "__main__":
    main()
