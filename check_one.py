#!/usr/bin/env python3
"""
Simple read-only test: for given project(s), show ci_config_path, the CI file
content (first lines + 'sysdig' matches), and latest pipeline jobs.

Usage:
  cp .env.example .env   # fill GL_HOST, GL_TOKEN
  python3 check_one.py smartfren/mysf-backend/smartpoin
  python3 check_one.py smartfren/mysf-backend/smartpoin smartfren/dis/dos-web --branch tencent-staging

Env (or .env next to this file, see .env.example): GL_HOST, GL_TOKEN, GL_VERIFY_SSL=false if internal cert.
GET requests only.
"""
import argparse
import os
import sys
import urllib.parse

import requests

# load .env (KEY=value lines); real env vars win
_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env):
    for line in open(_env):
        k, sep, v = line.strip().partition("=")
        if sep and not k.startswith("#"):
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

HOST = os.environ.get("GL_HOST", "").rstrip("/")
TOKEN = os.environ.get("GL_TOKEN")
VERIFY = os.environ.get("GL_VERIFY_SSL", "true").lower() != "false"
if not HOST or not TOKEN:
    sys.exit("ERROR: set GL_HOST and GL_TOKEN (cp .env.example .env)")
if not VERIFY:
    requests.packages.urllib3.disable_warnings()

S = requests.Session()
S.headers["PRIVATE-TOKEN"] = TOKEN
S.verify = VERIFY


def q(s):
    return urllib.parse.quote(s, safe="")


def get(path, params=None, raw=False, quiet=False):
    r = S.get(f"{HOST}/api/v4{path}", params=params, timeout=30)
    if r.status_code != 200:
        if not quiet:
            print(f"   ! HTTP {r.status_code} on {path}")
        return None
    return r.text if raw else r.json()


def show_file(project, file_path, ref):
    txt = get(f"/projects/{q(project)}/repository/files/{q(file_path)}/raw",
              {"ref": ref}, raw=True)
    if txt is None:
        return
    lines = txt.splitlines()
    print(f"   file: {project} : {file_path} @ {ref} ({len(lines)} lines)")
    print("   --- first 25 lines ---")
    for ln in lines[:25]:
        print("   | " + ln)
    hits = [(i + 1, ln) for i, ln in enumerate(lines) if "sysdig" in ln.lower()]
    print(f"   --- 'sysdig' matches: {len(hits)} ---")
    for i, ln in hits:
        print(f"   {i:4d}: {ln.strip()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="+", help="full path, e.g. smartfren/mysf-backend/smartpoin")
    ap.add_argument("--branch", default="tencent-staging")
    a = ap.parse_args()

    for proj in a.projects:
        print(f"\n=== {proj} ===")
        d = get(f"/projects/{q(proj)}")
        if not d:
            continue
        ci_path = d.get("ci_config_path") or ""
        print(f"   default_branch : {d.get('default_branch')}")
        print(f"   ci_config_path : {ci_path or '(empty = .gitlab-ci.yml in repo)'}")

        # Resolve where the CI file lives
        if "@" in ci_path:
            fpath, other = ci_path.split("@", 1)
            show_file(other, fpath, d.get("default_branch") or "master")
        else:
            show_file(proj, ci_path or ".gitlab-ci.yml", a.branch)

        # Latest pipeline + jobs on the branch
        pls = get(f"/projects/{q(proj)}/pipelines",
                  {"ref": a.branch, "per_page": 1, "order_by": "id", "sort": "desc"})
        if not pls:
            print(f"   pipeline @ {a.branch}: none")
            continue
        pl = pls[0]
        print(f"   latest pipeline @ {a.branch}: #{pl['id']} {pl['status']} {pl['created_at'][:10]}")
        jobs = get(f"/projects/{q(proj)}/pipelines/{pl['id']}/jobs", {"per_page": 100}) or []
        for j in jobs:
            mark = "  <== SYSDIG" if "sysdig" in j["name"].lower() else ""
            print(f"     - [{j['stage']}] {j['name']}: {j['status']}{mark}")


if __name__ == "__main__":
    main()