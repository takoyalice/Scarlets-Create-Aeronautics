import json
import re
import sys
import time
import zipfile
import argparse
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MODRINTH_API = "https://api.modrinth.com/v2"
USER_AGENT = "scarlets-create-aeronautics-modlist/1.0"

CATEGORY_ORDER = [
    "Mods",
    "Mods (Overrides)",
    "Resource Packs",
    "Resource Packs (Overrides)",
    "Shader Packs",
    "Shader Packs (Overrides)",
    "Data Packs",
]


def fetch_json(url, retries=3, backoff=1.0):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError):
            if attempt == retries - 1:
                raise
            time.sleep(backoff * (attempt + 1))


def categorize(path):
    p = path.lower()
    if p.startswith(("shaderpacks/", "shaders/")):
        return "Shader Packs"
    if p.startswith(("resourcepacks/", "resource-packs/")):
        return "Resource Packs"
    if p.startswith("datapacks/") or "/datapacks/" in p:
        return "Data Packs"
    return "Mods"


def filename_to_name(path):
    name = Path(path).stem
    name = re.sub(r"[-_](v?\d[\w.+\-]*)$", "", name)
    return name.replace("-", " ").replace("_", " ").title()


def lookup_version(sha1):
    if not sha1:
        return None
    try:
        return fetch_json(f"{MODRINTH_API}/version_file/{sha1}?algorithm=sha1")
    except HTTPError as e:
        if e.code == 404:
            return None
        raise


def lookup_project(project_id):
    try:
        return fetch_json(f"{MODRINTH_API}/project/{project_id}")
    except HTTPError as e:
        if e.code == 404:
            return None
        raise


def resolve_entry(entry):
    path = entry.get("path", "")
    sha1 = (entry.get("hashes") or {}).get("sha1")
    name = filename_to_name(path)
    url = None
    version = None

    info = lookup_version(sha1)
    if info:
        version = info.get("version_number")
        project_id = info.get("project_id")
        if project_id:
            project = lookup_project(project_id)
            if project:
                name = project.get("title") or name
                slug = project.get("slug")
                ptype = project.get("project_type", "mod")
                if slug:
                    url = f"https://modrinth.com/{ptype}/{slug}"

    if not url:
        downloads = entry.get("downloads") or []
        if downloads:
            url = downloads[0]

    return categorize(path), name, url, version


def parse_mrpack(mrpack_path):
    with zipfile.ZipFile(mrpack_path) as zf:
        with zf.open("modrinth.index.json") as f:
            index = json.load(f)

        pack_name = index.get("name", mrpack_path.stem)
        pack_version = index.get("versionId", "unknown")
        files = index.get("files", [])

        entries = []
        total = len(files)
        for i, entry in enumerate(files, 1):
            print(f"[{i}/{total}] {entry.get('path', '')}", file=sys.stderr)
            entries.append(resolve_entry(entry))

        for name in zf.namelist():
            if name.startswith("overrides/mods/") and name.endswith(".jar"):
                entries.append(("Mods (Overrides)", filename_to_name(name), None, None))
            elif name.startswith("overrides/shaderpacks/"):
                entries.append(("Shader Packs (Overrides)", filename_to_name(name), None, None))
            elif name.startswith("overrides/resourcepacks/"):
                entries.append(("Resource Packs (Overrides)", filename_to_name(name), None, None))

    return pack_name, pack_version, entries


def render_markdown(pack_name, pack_version, entries):
    grouped = {}
    for cat, name, url, ver in entries:
        grouped.setdefault(cat, []).append((name, url, ver))

    def cat_key(c):
        return CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99, c

    total = sum(len(v) for v in grouped.values())
    lines = [
        f"# Mod List - {pack_name} {pack_version}",
        "",
        f"Total entries: **{total}**",
        "",
    ]

    for cat in sorted(grouped.keys(), key=cat_key):
        items = sorted(grouped[cat], key=lambda x: x[0].lower())
        lines.append(f"## {cat} ({len(items)})")
        lines.append("")
        for name, url, ver in items:
            suffix = f" - `{ver}`" if ver else ""
            if url:
                lines.append(f"- [{name}]({url}){suffix}")
            else:
                lines.append(f"- {name}{suffix}")
        lines.append("")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Generate MODLIST.md from a .mrpack file")
    ap.add_argument("mrpack", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("MODLIST.md"))
    args = ap.parse_args()

    if not args.mrpack.exists():
        print(f"error: {args.mrpack} not found", file=sys.stderr)
        sys.exit(1)

    pack_name, pack_version, entries = parse_mrpack(args.mrpack)
    md = render_markdown(pack_name, pack_version, entries)
    args.output.write_text(md, encoding="utf-8")
    print(f"\nwrote {len(entries)} entries to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()