"""Package a reviewable source archive using an explicit allowlist."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "CampusPulse_AI_source.zip"
FILES = ["README.md", ".gitignore", ".env.example", "requirements.txt", "requirements-cloud.txt", "requirements.lock.txt", "start.cmd", "mcp-config.example.json"]
DIRECTORIES = ["campuspulse", "web", "tests", "scripts", "docs", "examples"]


def main():
    files = [ROOT / name for name in FILES]
    for name in DIRECTORIES:
        files.extend(file for file in (ROOT / name).rglob("*") if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc")
    files.extend([ROOT / "output" / "CampusPulse_AI.pptx", ROOT / "output" / "campuspulse-preview.jpg"])
    missing = [str(file.relative_to(ROOT)) for file in files if not file.is_file()]
    if missing:
        raise SystemExit(f"Missing deliverables: {missing}")
    OUTPUT.parent.mkdir(exist_ok=True)
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        for file in sorted(set(files)):
            if file.is_symlink() or not file.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError("Unexpected link or file outside the project")
            archive.write(file, "CampusPulse_AI/" + file.relative_to(ROOT).as_posix())
    with ZipFile(OUTPUT) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive integrity check failed")
        names = archive.namelist()
        assert not any("/.venv/" in name or "credentials" in name.lower() or name.endswith("/.env") for name in names)
    print(f"{OUTPUT}\n{len(files)} files; {OUTPUT.stat().st_size} bytes; archive verified")


if __name__ == "__main__":
    main()
