#!/usr/bin/env python3
"""
Walk every project under GitLab group(s) (incl. subgroups) and check Sysdig.
Writes one sheet per group into the xlsx (sheet replaced if it exists).
Logic is described in README.md.

Usage:
  cp .env.example .env   # fill GL_HOST, GL_TOKEN
  python3 audit_group.py 10326                      # group id or full path
  python3 audit_group.py smartfren/mysf-backend smartfren/dis

GET requests only (writes only the local xlsx).
"""
# First branch that exists (and has a CI file) wins. Edit to change the order.
BRANCH_PRIORITY = [
    "tencent-master",
    "sit-tencent",
    "staging",
    "master",
    "prod-tencent",
]
STALE_DAYS = 90

import argparse
import os
import sys
from datetime import datetime, timezone

import openpyxl

from check_one import HOST, get, q

COLS = ["App", "Service", "Sysdig", "Sysdig Notes", "Link Repo", "Branch", "Branches Checked",
        "Link CI", "CI/CD", "Pipeline", "Sysdig job", "Notes"]


def paged(path, params):
    page = 1
    while True:
        items = get(path, {**params, "per_page": 100, "page": page}) or []
        yield from items
        if len(items) < 100:
            return
        page += 1


def ci_location(p, ref):
    """-> (project, file, ref) where the CI file actually lives."""
    ci = p.get("ci_config_path") or ""
    if "@" in ci:  # file@group/project[:ref]
        fpath, other = ci.split("@", 1)
        proj, _, tref = other.partition(":")
        return proj, fpath, tref or (get(f"/projects/{q(proj)}") or {}).get("default_branch") or "master"
    return p["path_with_namespace"], ci or ".gitlab-ci.yml", ref


def read_ci(p, ref):
    proj, fpath, fref = ci_location(p, ref)
    txt = get(f"/projects/{q(proj)}/repository/files/{q(fpath)}/raw", {"ref": fref}, raw=True, quiet=True)
    return txt, f"{HOST}/{proj}/-/blob/{fref}/{fpath}"


def pick_branch(p):
    """-> (branch, ci_text, ci_link, trail). trail = human-readable list of what was tried."""
    trail = []
    for b in BRANCH_PRIORITY:
        if get(f"/projects/{p['id']}/repository/branches/{q(b)}", quiet=True) is None:
            trail.append(f"{b} ✗")
            continue
        txt, link = read_ci(p, b)
        if txt is not None:
            trail.append(f"{b} ✓")
            return b, txt, link, trail
        trail.append(f"{b} (no CI)")

    last = get(f"/projects/{p['id']}/pipelines", {"per_page": 1}) or []
    if last:
        b, how = last[0]["ref"], "last pipeline"
    else:
        b, how = p.get("default_branch") or "master", "default branch, never ran"
    trail.append(f"→ fallback: {how}")
    txt, link = read_ci(p, b)
    return b, txt, link, trail


def check(p, group_full):
    notes = []
    branch, txt, ci_link, trail = pick_branch(p)
    if txt is None:
        notes.append("CI file not found")
        txt = ""
    ci_hit = "sysdig" in txt.lower()
    if not ci_hit and "include" in txt:
        notes.append("has include: (sysdig may be in included file)")

    pls = get(f"/projects/{p['id']}/pipelines", {"ref": branch, "per_page": 1}) or []
    pl_txt, job = "", None
    if pls:
        pl = pls[0]
        pl_txt = f"#{pl['id']} {pl['status']} {pl['created_at'][:10]}"
        age = datetime.now(timezone.utc) - datetime.fromisoformat(pl["created_at"].replace("Z", "+00:00"))
        if age.days > STALE_DAYS:
            notes.append(f"last pipeline > {STALE_DAYS}d")
        jobs = get(f"/projects/{p['id']}/pipelines/{pl['id']}/jobs", {"per_page": 100}) or []
        job = next((j for j in jobs if "sysdig" in j["name"].lower()), None)
    else:
        notes.append(f"no pipeline on {branch}")

    if job and job["status"] == "success":
        health = "OK"
    elif job:
        health = f"Job {job['status']}"
    elif ci_hit:
        health = "Configured, not run"
    else:
        health = ""

    # App = first subgroup under the audited group, e.g. "mysf-backend"
    rel = p["namespace"]["full_path"][len(group_full):].strip("/")
    return [
        rel.split("/")[0] or group_full.split("/")[-1],
        p["name"],
        "Yes" if ci_hit or job else "No",
        health,
        p["web_url"],
        branch,
        ", ".join(trail),
        ci_link,
        p.get("ci_config_path") or ".gitlab-ci.yml",
        pl_txt,
        f"{job['name']}: {job['status']}" if job else "",
        "; ".join(notes),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("groups", nargs="+", help="group id or full path, e.g. 10326 or smartfren/sisternet")
    ap.add_argument("--xlsx", default="Sysdig Listing Deployment.xlsx")
    a = ap.parse_args()

    if os.path.exists(a.xlsx):
        wb = openpyxl.load_workbook(a.xlsx)
    else:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)  # drop the default empty "Sheet"
    for g in a.groups:
        grp = get(f"/groups/{q(g)}")
        if not grp:
            continue
        print(f"\n=== {grp['full_path']} ===")
        rows = []
        for p in paged(f"/groups/{grp['id']}/projects", {"include_subgroups": "true", "archived": "false"}):
            row = check(p, grp["full_path"])
            print(f"   {row[2]:3} {row[3]:20} {row[5]:16} {p['path_with_namespace']}  {row[-1]}")
            rows.append(row)
        rows.sort(key=lambda r: (r[0], r[1]))

        title = grp["path"][:31]
        if title in wb.sheetnames:
            del wb[title]
        ws = wb.create_sheet(title)
        ws.append(COLS)
        for r in rows:
            ws.append(r)
        yes = sum(r[2] == "Yes" for r in rows)
        print(f"   -> {yes}/{len(rows)} with sysdig, sheet '{title}'")
    if not wb.sheetnames:
        sys.exit("nothing to write (no group could be read)")
    wb.save(a.xlsx)
    print(f"\nsaved {a.xlsx}")


if __name__ == "__main__":
    main()
