# Monthly refresh automation — `scripts/refresh_month.py`

Keeps the Toronto Airbnb SQL project current without manual work. Once a month
it detects the newest Inside Airbnb Toronto release and, if it hasn't been
processed yet, runs the whole pipeline end to end: download → SQLite build →
exploration + analysis queries → 6 charts → auto-generated findings report →
README update → local git commit → GitHub push.

## What it does, step by step

1. **Release detection.** Probes
   `https://data.insideairbnb.com/canada/on/toronto/<YYYY-MM-DD>/data/listings.csv.gz`
   for days 15, 16, 14, 13, 17, 12, 18 of the current month, then the two
   previous months. First 2xx wins. If nothing is found the script logs
   "no release available" and **exits 0** (not an error — releases simply
   aren't published yet).
2. **Idempotency.** Skips cleanly if `data/listings-<month>.csv.gz` or
   `docs/findings-<month>.md` already exists — re-running is always safe.
3. **Download + validation.** Downloads with one retry. Validates gzip
   integrity and requires the CSV header to match the known 90-column
   snapshot header byte-for-byte (a schema change stops the run instead of
   silently corrupting the analysis). Corrupt download → retry once → exit 1.
4. **Database build.** Generates `sql/01_setup-<month>.sql` from the
   September template (new CSV path, release date, run instructions), builds
   `data/airbnb_toronto_<YYYY_MM>.db`, then runs `02_exploration.sql` and
   `03_analysis.sql` unchanged (schema verified identical at the header
   level; any sqlite3 error → exit 1).
5. **Charts.** Runs `scripts/make_charts_month.py --db … --outdir docs/charts/<month> --label …`
   and requires all 6 PNGs to exist.
6. **Metrics + findings.** Collects headline metrics with the same
   window-function median semantics as `sql/03_analysis.sql`, saves them to
   `docs/metrics-<month>.json` (this JSON is what powers month-over-month
   diffs on the next run), and writes `docs/findings-<month>.md` with a
   **"auto-generated draft"** banner. Numbers are real; prose is a skeleton
   for a human pass.
7. **README.** Appends the month's row to the *Monthly snapshots* table and
   adds the new files to the project-structure listing. Skipped with
   `--dry-run`.
8. **Local git commit** (`git add` + `git commit`; no-op if nothing changed).
9. **GitHub push.** One commit via the GitHub REST API: blobs → tree →
   commit → `PATCH /git/refs/heads/main`, then verifies the remote tree
   contains every pushed path. Skipped with `--dry-run`.

Calendar (`calendar.csv`) and reviews (`reviews.csv`) are **not** refreshed
by this script — only the listings pipeline. Those tables exist only for
the August 2026 database and would need a separate, heavier job.

## Usage

```bash
# normal monthly run
python3 scripts/refresh_month.py

# test idempotency for an already-processed month
python3 scripts/refresh_month.py --month 2026-09 --dry-run

# full test without publishing anything
python3 scripts/refresh_month.py --dry-run
```

Dependencies: Python stdlib + `sqlite3` CLI + the repo's existing matplotlib
(for the chart script). No pip installs.

## Suggested cron schedule

Monthly on the **20th at 09:00 America/Toronto** — after the mid-month
release (Toronto releases have landed on the 14th, 15th, and 16th, so the
20th leaves margin), and well after the previous month's data is settled:

```bash
# crontab -e
0 9 20 * * cd ~/workspace/projects/airbnb-toronto-sql-analysis && /usr/bin/python3 scripts/refresh_month.py >> logs/cron.log 2>&1
```

Run logs land in `logs/refresh-<YYYY-MM>.log` (gitignored).

## Recovery

| Symptom | Cause | Fix |
|---|---|---|
| "no release available", exit 0 | Inside Airbnb hasn't published this month's release | Wait; the next run will pick it up. |
| Header mismatch, exit 1 | Inside Airbnb changed the listings schema | Inspect the new header, adapt the setup SQL template manually, re-run. |
| sqlite3 error, exit 1 | Query vs schema mismatch or disk full | Read the tail of the log (`logs/refresh-*.log`), fix, re-run (idempotent — but delete a partial `.db` first if the build failed mid-import). |
| GitHub API 403/409 on push | Rate limit or ref race | Re-run; pushes are idempotent. If a 401/403 persists, check `custom.github` via the github skill. |
| Partial month processed | Run died after download but before report | Safe to re-run: it skips already-present files, or remove `docs/findings-<month>.md` to regenerate the report. |

## Known quirk: GitHub push over HTTPS does not work

The stored credential (`custom.github`) is exchanged for the real token only
on **api.github.com** requests through the surrogate mechanism
(`add_surrogate_to_request` from
`/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py`). A plain
`git push` over HTTPS sends the surrogate to github.com, which rejects it as
invalid credentials. That's why this script pushes through the REST
git-database API instead.

A second quirk: passing base64'd PNGs through a subprocess (`bin/ghapi`)
hits the ~128 KB single-argument limit, so the script calls the credential
mechanism **directly via urllib** — same auth flow as the skill, just no
argv bottleneck.
