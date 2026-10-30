#!/usr/bin/env python3
"""
Inventory: every repo per GitLab group -> xlsx (Summary sheet + one sheet per top-level group).

Usage:
  cp .env.example .env   # fill GL_HOST, GL_TOKEN
  python3 list_repos.py                       # all top-level groups the token can see
  python3 list_repos.py smartfren sisternet   # only these
GET requests only.
"""
import argparse
from collections import Counter

import openpyxl

from audit_group import paged
from check_one import get, q

COLS = ["App", "Subgroup", "Service", "Repo path", "Link Repo", "Default branch", "Last activity", "Archived"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("groups", nargs="*", help="top-level group paths/ids; default = all visible")
    ap.add_argument("--xlsx", default="Repo Inventory.xlsx")
    a = ap.parse_args()

    groups = [get(f"/groups/{q(g)}") for g in a.groups] if a.groups else \
        list(paged("/groups", {"top_level_only": "true", "order_by": "path"}))

    wb = openpyxl.Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["Group", "App", "Repos"])

    for grp in filter(None, groups):
        root = grp["full_path"]
        rows = []
        for p in paged(f"/groups/{grp['id']}/projects",
                       {"include_subgroups": "true", "with_shared": "false", "order_by": "path", "sort": "asc"}):
            sub = p["namespace"]["full_path"][len(root):].strip("/")
            rows.append([sub.split("/")[0] or "(root)", sub or "(root)", p["name"],
                         p["path_with_namespace"], p["web_url"], p.get("default_branch") or "",
                         (p.get("last_activity_at") or "")[:10], "Yes" if p.get("archived") else ""])
        rows.sort(key=lambda r: (r[0], r[1], r[2].lower()))
        print(f"{root:25} {len(rows):5} repos")

        ws = wb.create_sheet(grp["path"][:31])
        ws.append(COLS)
        for r in rows:
            ws.append(r)
        for app, n in sorted(Counter(r[0] for r in rows).items()):
            summary.append([root, app, n])
        summary.append([root, "TOTAL", len(rows)])

    wb.save(a.xlsx)
    print(f"\nsaved {a.xlsx}")


if __name__ == "__main__":
    main()
