# Sysdig audit

Read-only check of which GitLab projects have Sysdig scanning in their CI.

## Setup

1. Buat Python virtual environment:
   ```bash
   python3 -m venv venv
   ```

2. Copy `.env` lalu isi `GL_HOST` dan `GL_TOKEN` (`GL_VERIFY_SSL=false` kalau sertifikatnya internal):
   ```bash
   cp .env.example .env
   ```

3. Install requirements:
   ```bash
   venv/bin/pip install -r requirements.txt
   ```

## Run

1. Cek satu project (verbose):
   ```bash
   venv/bin/python check_one.py smartfren/mysf-backend/smartpoin
   ```

2. Audit satu atau beberapa group (output: satu sheet xlsx per group):
   ```bash
   venv/bin/python audit_group.py 10326 smartfren/mysf-backend
   ```

3. Audit top group beserta semua subgroup:
   ```bash
   venv/bin/python audit_group.py smartfren
   ```

4. Inventaris repo (output: `Repo Inventory.xlsx`):
   ```bash
   venv/bin/python list_repos.py
   ```

Branch order and stale cutoff: edit `BRANCH_PRIORITY` / `STALE_DAYS` at the top of `audit_group.py`.

## Logic

```
BRANCH_PRIORITY = [tencent-master, sit-tencent, staging, master, prod-tencent]   # top of audit_group.py
                                                         # scan branches first: e.g. sisternet only scans on sit/staging

for each group:
    for each non-archived project in group (incl. subgroups):
        ci_cfg = project.ci_config_path                   # "" | "file" | "file@group/proj[:ref]"
        external = "@" in ci_cfg                          # CI file lives in a shared template repo

        # 1. pick branch
        branch = None
        for b in BRANCH_PRIORITY:
            if not branch_exists(b):            checked += "b ✗";       continue
            if ci_file_readable(ref=b):         checked += "b ✓";       branch = b; break
            checked += "b (no CI)"              # branch exists but no CI file
        if branch is None:
            last = latest pipeline on any ref
            if last:   branch = last.ref;       checked += "→ fallback: last pipeline"
            else:      branch = default_branch; checked += "→ fallback: default branch, never ran"

        # 2. read CI file
        if external: read file from template repo @ template ref (or its default branch)
        else:        read file from project @ branch
        ci_has_sysdig = "sysdig" in file
        if not ci_has_sysdig and file has "include:": note "check includes manually"

        # 3. latest pipeline on that branch
        pl   = latest pipeline where ref == branch
        job  = first job in pl whose name contains "sysdig"
        stale = pl.created_at older than 90 days

        # 4. status: any sign of sysdig = Yes; health goes to its own column
        sysdig = "Yes" if (ci_has_sysdig or job) else "No"
        if   job and job.status == success:    health = "OK"
        elif job:                              health = "Job " + job.status     # failed / canceled / skipped
        elif ci_has_sysdig:                    health = "Configured, not run"   # no pipeline / stage never reached
        else:                                  health = ""
        if stale:  note "last pipeline > 90d"
        if not pl: note "no pipeline on <branch>"

        write row: App, Service, Sysdig, Sysdig Notes, Link Repo, Branch, Branches Checked,
                   Link CI, CI/CD, Pipeline, Sysdig job, Notes
```

Notes
- With an external template (`file@group/proj`), the CI file is the same on every branch, so
  the branch only decides which pipeline gets checked.
- Sysdig is "Yes" whenever it's in the CI or a sysdig job ran. Whether it actually ran OK is in "Sysdig Notes".
