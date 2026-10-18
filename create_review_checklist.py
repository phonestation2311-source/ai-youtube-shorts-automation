import json
from pathlib import Path

OUTPUT = Path("output")
metadata_files = sorted(OUTPUT.glob("short_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

if not metadata_files:
    raise SystemExit("No video metadata found in output/.")

meta_path = metadata_files[0]
metadata = json.loads(meta_path.read_text(encoding="utf-8"))

video = metadata.get("video_file", "")
thumbnail = metadata.get("thumbnail", "")
checks = [
    ("Video plays from beginning to end without errors", video),
    ("Hindi narration is clear and matches the story", video),
    ("Hindi subtitles are readable, correctly timed, and spelled correctly", video),
    ("Story is suitable for children and has a clear ending", video),
    ("Thumbnail is clear and represents the actual video", thumbnail),
    ("Title is accurate, attractive, and not misleading", ""),
    ("Description and hashtags are accurate", ""),
    ("Footage and music usage rights have been checked", ""),
    ("Made for Kids audience setting has been checked", ""),
    ("Final video has been watched and manually approved", ""),
]

lines = [
    "# YouTube Short — Manual Review",
    "",
    f"- Video: `{video}`",
    f"- Thumbnail: `{thumbnail or 'Not found'}`",
    f"- Metadata: `{meta_path.name}`",
    f"- Created: {metadata.get('created', 'Unknown')}",
    f"- Review status: **PENDING — NOT APPROVED**",
    f"- Upload status: **NOT UPLOADED**",
    "",
    "## Review checklist",
    "",
]
for label, filename in checks:
    lines.append(f"- [ ] {label}" + (f" — `{filename}`" if filename else ""))

lines += [
    "",
    "## Decision",
    "",
    "- [ ] Approved for consideration after every check passes",
    "- [ ] Needs changes",
    "",
    "Notes / changes required:",
    "",
    " ",
    "",
    "**Important:** Completing this checklist does not upload or publish the video. "
    "Keep `UPLOAD_ENABLED=false` and `UPLOAD_APPROVED=false` until a separate, "
    "explicit publishing decision is made.",
]

review_path = OUTPUT / f"review_{meta_path.stem}.md"
review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Review checklist created: {review_path}")
print("Status: PENDING — no upload performed.")
