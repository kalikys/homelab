#!/usr/bin/env python3
"""Writes the Terraform inventory (local.site_inventory) to services/public/site/data/homelab.json."""
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
# `terraform console` evaluates the configuration without touching state or provider APIs.
raw = subprocess.run(
    ["terraform", "console"], input="jsonencode(local.site_inventory)\n",
    cwd=ROOT / "terraform", check=True, capture_output=True, text=True,
).stdout.strip()
data = json.loads(json.loads(raw))

out = ROOT / "services/public/site/data/homelab.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
print(f"wrote {out.relative_to(ROOT)} ({len(data['guests'])} guests)")
