#!/usr/bin/env python3

import subprocess
from pathlib import Path
import re
import sys
from collections import defaultdict

README_HEADER = """# 🧁 bitcoin-notes

Welcome! This is my personal stash of notes on Bitcoin Core and some related C++ things I run into while digging around. These are mostly for myself, but you're welcome to snoop around.

Notes may be _wrong_, _outdated_, or just me thinking out loud. Don't trust, verify! :)

## Table of Contents
"""

README_FOOTER = """
---

Built with 🧁☕, curiosity, and a lot of `git grep`.

(Plus a little AI help to keep things organized.)

"""

DESC_PATTERN = re.compile(r"<!--\s*desc:\s*(.*?)\s*-->", re.IGNORECASE)

def get_committed_md_files():
    result = subprocess.run(["git", "ls-files", "*.md"], capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ Error: Failed to run git ls-files", file=sys.stderr)
        sys.exit(1)
    return [Path(f) for f in result.stdout.strip().split("\n") if f.strip()]

def extract_desc(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        for _ in range(10):  # only check first 10 lines
            line = f.readline()
            if not line:
                break
            match = DESC_PATTERN.search(line)
            if match:
                return match.group(1).strip()
    return None

def group_by_directory(files):
    grouped = defaultdict(list)
    for f in files:
        grouped[f.parent].append(f)
    return grouped

def generate_readme():
    files = get_committed_md_files()
    grouped_files = group_by_directory(files)

    readme_lines = [README_HEADER]

    for directory, files in sorted(grouped_files.items()):
        if str(directory) == ".":
            continue
        dir_label = f"{directory}/"
        readme_lines.append(f"### 🫧 {dir_label}")
        for f in sorted(files):
            if f.name.lower() == "readme.md":
                continue
            desc = extract_desc(f)
            if not desc:
                print(f"❌ Error: Missing desc in {f}", file=sys.stderr)
                sys.exit(1)
            readme_lines.append(f"- [`{f.name}`]({f}): {desc}")
        readme_lines.append("")  # spacing

    readme_lines.append(README_FOOTER)

    Path("README.md").write_text("\n".join(readme_lines), encoding="utf-8")
    print("✅ README.md generated successfully.")

if __name__ == "__main__":
    generate_readme()

