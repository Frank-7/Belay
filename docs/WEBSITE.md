# Public website

The GitHub Pages site introduces Belay, explains the recovery problem,
and links to recorded, interactive operator and research walkthroughs. After the first successful
deployment, its address is <https://frank-7.github.io/Belay/>.

`site/` holds the HTML, CSS, JavaScript and local assets. There is no framework,
package installation, API key, analytics service or backend required to build
or use the site. GitHub Pages serves static files; it does not run the separate
[live Recovery Desk](INTEGRATION.md) or the earlier local prototype.

The main CTA opens `desk/`, an explicit recording using the same UI and
validator path as `python -m recovery_app.server`. It shows six local
simulator cases, including conflicting sources, and disables model, wallet
and mutation controls. `recovery-desk.html` remains the separate research
viewer with recorded POSIX crash experiments. Both are recordings; neither
is a hosted Python application. Run the local app for fresh investigations
and user-signed Arc Testnet transfers.

## Build and preview

Python 3.10+ and Git are required. Use Linux, macOS or WSL: generating the
recorded Recovery Desk runs the repository's real SIGKILL sandbox scenarios.
From the repository root:

```sh
python3 tests/test_build_site.py
python3 scripts/build_site.py --out _site
python3 -m http.server 8000 --bind 127.0.0.1 --directory _site
```

Open <http://localhost:8000/>. The **Recovery Desk** link opens
`recovery-desk.html` from that same build. It contains recorded sandbox events
and a simulated adjudicator; browser clicks inspect those recordings. They do
not execute payments or call a live model.

The build also accepts an isolated output such as
`--out tmp-runs/pages-public`. Outputs must be `_site` or a directory below
`tmp-runs/` in this checkout. Existing nonempty directories are replaced only
when they contain the builder's marker. A failed generation leaves the prior
build intact. Source symlinks, hidden assets and reserved generated filenames
are rejected. Missing local HTML links/assets and root-relative URLs fail the
build, so the same files can be served below the `/Belay/` project path.
Only the site assets, recorded operator cases, generated viewer and public evidence
summary enter the output directory.

## Evidence and claims

The builder creates `evidence.json` from the **committed** `HEAD` versions of
`results/matrix.json`, `results/findings.json` and `results/adjudication.json`.
It checks the summaries against the raw trial and adjudication records and
adds GitHub links pinned to the full source commit. Uncommitted experiment
results cannot silently replace the published baseline. The build replaces
the page's metric fields and evidence links from this audited data; the
published figures and their provenance work even without JavaScript.

The current committed observations are 960 confirmed process crashes across
four runtimes, **0 violations in 240 anchored-runtime trials**, and **90
resolved cases out of 200 validated adjudications, with 0 false resolutions**.
The remaining 110 validated cases abstained. These are synthetic experiment
counts, not production loss rates, a success rate for live models, or evidence
of universal correctness. Availability is deliberately sacrificed when the
available evidence cannot determine an outcome. The authoritative scope is
[CONTRACT.md](../CONTRACT.md); details and limitations are in
[FINDINGS.md](../FINDINGS.md).

The Recovery Desk is freshly recorded during each site build, independently
of those committed aggregate results. It uses temporary sandbox state and
does not overwrite `results/` or the source viewer.

## Publishing

The separate [Pages workflow](../.github/workflows/pages.yml) leaves the
existing CI workflow intact. Relevant pull requests build and upload a Pages
artifact without deployment permissions. Relevant pushes to `main`, or a
manual workflow dispatch on `main`, build and deploy using the `github-pages`
environment. Other manually selected branches only build.

In repository **Settings → Pages**, select **GitHub Actions** as the build
source before the first deployment. Keep the `github-pages` environment
restricted to `main`. Then run the `pages` workflow on `main` or push a site
change. Its deploy job exposes the published URL. An Actions build artifact
on a pull request is downloadable evidence, not a public preview URL.

Only the deployment job receives `pages: write` and `id-token: write`.
`configure-pages`, `upload-pages-artifact` and `deploy-pages` are the official
GitHub actions; see GitHub's
[custom Pages workflow guide](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
