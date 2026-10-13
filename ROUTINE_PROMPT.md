# The daily update routine

The dashboard is refreshed by a claude.ai cloud routine (a scheduled trigger), not by anything in GitHub.

- **Name:** AI Dashboard daily update
- **Schedule:** every day at 08:52 Sydney time (`CRON_TZ=Australia/Sydney 52 8 * * *`); a fresh cloud session per run
- **Environment:** the claude.ai cloud environment this repository was set up in. Its network reaches every host
  `update.py` reads (README, "Deploying to GitHub")
- **Pushes to:** `main`, one commit per run ("Daily update YYYY-MM-DD: ...")
- **Artifact:** https://claude.ai/artifact/XdMsrTPzKDVHMP1tLmsUBA, a private claude.ai page holding the latest
  `dashboard.html`, republished after each successful push

To change what the routine does, edit the routine itself on claude.ai (Routines), then update this file to match.
The instructions it runs, verbatim:

```
Daily refresh of the "1 GW Blackwell: rent or serve" AI dashboard in the GitHub repository SystemCapital/AI-Dashboard, then republish of its artifact. This is an unattended scheduled run: nobody is watching, so do not ask questions. Finish the run and report.

1. Repository. Push access comes only from the add_repo tool: a plain `git clone` of this public repository works, but the git proxy refuses its push (403, "not in this session's authorized repository set"). So before anything else call the tool `mcp__claude-code-remote__add_repo` directly, with owner "SystemCapital", repo "AI-Dashboard" and access "push". It is already in your tool list; ToolSearch only finds deferred tools, so a ToolSearch miss does not mean add_repo is missing. Then clone with the command its result gives (or keep an existing clone of the repository). If add_repo is not in your tools or refuses, stop and report its exact message; do not run the update without it. Work from the latest main: `git fetch origin main && git checkout -B main origin/main`. README.md ("Deploying to GitHub") and ROUTINE_PROMPT.md give background; this prompt is the procedure.

2. Refresh. From the repository root run `PYTHONDONTWRITEBYTECODE=1 python3 update.py --scheduled` with a 10-minute Bash timeout (it takes about 4-5 minutes; standard library only, no installs, no API keys). It fetches every market input (OpenRouter, InferenceX, the rental vendors, Silicon Data, Ornn, GetDeploying, news, deals), rebuilds dashboard.html, index.html and infographic/infographic.html, and appends to update.log and data/. update.py dates the run on Sydney time by itself. A step that cannot reach its source keeps the last good data and the run carries on; that is expected. Do not edit the engine, the data files or assumptions.json by hand, and do not try to repair collectors.
   Then check the result: the lines update.log gained in this run must include a "build: dashboard.html ..." line and end with a "done. ..." line (note any "failed: <steps>" it lists), and `grep -o '"built_at":"[^"]*"' dashboard.html | head -1` must show today's Sydney date (`TZ=Australia/Sydney date +%F`). If the build step failed or dashboard.html was not rebuilt today, do not commit or publish; stop and report this run's update.log lines.

3. Commit and push to main. Run `git add dashboard.html index.html infographic/infographic.html update.log data/` (never commit __pycache__ or any other file). Commit with the message "Daily update YYYY-MM-DD: <summary>", using today's Sydney date and a short summary from the build line, for example "ROIC rent 20.3%, Anthropic 39.0%, OpenAI 29.0%, open 46.1%, AWS 53.3%; all steps clean". Push it straight to main with `git push origin HEAD:main`. This routine is authorised to push to main every day. Do not open a pull request and do not push to any other branch. If the push is rejected because main has moved, run `git pull --rebase origin main` and push again; if that rebase conflicts, run `git rebase --abort`, then `git fetch origin main && git reset --hard origin/main`, run step 2 once more, and commit and push once more. If git refuses the push for any other reason, stop and report the exact error.

4. Republish the dashboard artifact. Do this only when step 3 pushed successfully and `git status --porcelain -- dashboard.html` prints nothing. Skip it otherwise.
   a. Read the whole of dashboard.html before publishing it. It is about 1.2 MB, and two of its lines (the embedded `const INPUTS = ...` and `const PY = ...` data) are several hundred KB each, too long for the Read tool, so make a wrapped copy that keeps every character: `fold -w 1000 dashboard.html > <your scratchpad directory>/dashboard.folded.txt && wc -l <that file>`. Read the folded file from its first line to its last in consecutive parts of about 100 lines (offset/limit, allow_large: true), leaving no gaps; if a part is refused as too large, re-read it in smaller pieces. Check it for anything that must not be published: credentials, keys or tokens, personal contact details of private individuals, or harmful content. Market data, prices, vendor names, public news headlines and source URLs are expected. If you find something of concern, do not publish; report what and where.
   b. Use the Artifact tool (load it with ToolSearch if it is deferred). First read the existing artifact with action "read" and url "https://claude.ai/artifact/XdMsrTPzKDVHMP1tLmsUBA". Then publish to that same url: action "publish", url "https://claude.ai/artifact/XdMsrTPzKDVHMP1tLmsUBA", file_path the absolute path of the repository's dashboard.html. It replaces the whole page, so publish it as is. Do not pass files, capabilities, icon or force, and never publish without the url, which would create a separate artifact.
   c. If the publish is refused or asks for approval, do not retry; report the exact message.

5. Report. End with a short summary:
   - the build date and the six scenario ROICs (rent, Anthropic, OpenAI, open-only, open-peak, AWS) from this run's build line, with the change from the last build line dated before today in update.log;
   - steps that failed or kept old data (this run's update.log lines containing "FAILED", "kept" or "failed:");
   - rental price changes, new pricing notices, lab list-price moves and new deal candidates reported in this run's log;
   - the commit SHA pushed to main, or why nothing was pushed;
   - the artifact version published, or why it was not republished.
```
