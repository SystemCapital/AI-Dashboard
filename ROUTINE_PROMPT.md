# The daily update routine

The dashboard is refreshed by a claude.ai cloud routine (a scheduled trigger), not by anything in GitHub.

- **Name:** AI Dashboard daily update
- **Schedule:** every day at 08:52 Sydney time (`CRON_TZ=Australia/Sydney 52 8 * * *`); a fresh cloud session per run
- **Environment:** the claude.ai cloud environment this repository was set up in. Its network reaches every host
  `update.py` reads (README, "Deploying to GitHub")
- **Repository:** SystemCapital/AI-Dashboard must be attached in the routine's settings on claude.ai. That is what
  gives each run push access; a run without it can clone this public repository but cannot push
- **Pushes to:** `main`, one commit per run ("Daily update YYYY-MM-DD: ...")
- **Artifact:** https://claude.ai/artifact/XdMsrTPzKDVHMP1tLmsUBA, a private claude.ai page holding the latest
  `dashboard.html`, republished after each successful push

To change what the routine does, edit the routine itself on claude.ai (Routines), then update this file to match.
The instructions it runs, verbatim:

```
Daily refresh of the "1 GW Blackwell: rent or serve" AI dashboard in the GitHub repository SystemCapital/AI-Dashboard, then republish of its artifact. This is an unattended scheduled run: nobody is watching, so do not ask questions. Finish the run and report.

1. Repository. The routine attaches SystemCapital/AI-Dashboard to this session, so it should already be cloned in your working directory with push access. If it is not, stop and report "the routine has no repository attached: add SystemCapital/AI-Dashboard to this routine's repositories on claude.ai". Do not clone it yourself: a plain clone of this public repository cannot push (the git proxy refuses it with 403). Work from the latest main: `git fetch origin main && git checkout -B main origin/main`. README.md ("Deploying to GitHub") and ROUTINE_PROMPT.md give background; this prompt is the procedure.

2. Refresh. From the repository root run `PYTHONDONTWRITEBYTECODE=1 python3 update.py --scheduled` with a 10-minute Bash timeout (it takes about 4-5 minutes; standard library only, no installs, no API keys). It fetches every market input (OpenRouter, InferenceX, the rental vendors, Silicon Data, Ornn, GetDeploying, news, deals), rebuilds dashboard.html, index.html and infographic/infographic.html, and appends to update.log and data/. update.py dates the run on Sydney time by itself. A step that cannot reach its source keeps the last good data and the run carries on; that is expected. Do not edit the engine, the data files or assumptions.json by hand, and do not try to repair collectors.
   Then check the result: the lines update.log gained in this run must include a "build: dashboard.html ..." line and end with a "done. ..." line (note any "failed: <steps>" it lists), and `grep -o '"built_at":"[^"]*"' dashboard.html | head -1` must show today's Sydney date (`TZ=Australia/Sydney date +%F`). If the build step failed or dashboard.html was not rebuilt today, do not commit or publish; stop and report this run's update.log lines.

3. Commit and push to main. Run `git add dashboard.html index.html infographic/infographic.html update.log data/` (never commit __pycache__ or any other file). Commit with the message "Daily update YYYY-MM-DD: <summary>", using today's Sydney date and a short summary from the build line, for example "ROIC rent 20.3%, Anthropic 39.0%, OpenAI 29.0%, open 46.1%, AWS 53.3%; all steps clean". Push it straight to main with `git push origin HEAD:main`. This routine is authorised to push to main every day. Do not open a pull request and do not push to any other branch. If the push is rejected because main has moved, run `git pull --rebase origin main` and push again; if that rebase conflicts, run `git rebase --abort`, then `git fetch origin main && git reset --hard origin/main`, run step 2 once more, and commit and push once more. If git refuses the push for any other reason, stop and report the exact error.

4. Republish the dashboard artifact. Do this only when step 3 pushed successfully and `git status --porcelain -- dashboard.html` prints nothing. Skip it otherwise.
   a. Every line of dashboard.html must be read before it is published, and a pattern search or a scan never stands in for reading. It is about 1.4 MB (roughly 650k tokens); two of its lines (the embedded `const INPUTS = ...` and `const PY = ...` data) are several hundred KB each, too long for the Read tool. Make a wrapped copy that keeps every character: `fold -w 1000 dashboard.html > <your scratchpad directory>/dashboard.folded.txt && wc -l <that file>` (about 3,000 lines). Split the reading across 6 subagents (Agent tool, general-purpose), started together in one message: give each one consecutive range of lines, so that the 6 ranges cover line 1 to the last line with no gap. Tell each subagent: read every line of its range with the Read tool on the folded file in parts of 40 lines (offset/limit, allow_large: true), and re-read a part that is refused as too large in halves; then report the first and last line it read, whether it read every line of the range, and anything that must not be published: credentials, keys or tokens, personal contact details of private individuals, or harmful content (market data, prices, vendor names, public news headlines and source URLs are expected). Publish only when every subagent has reported its whole range read and nothing of concern. If any range was not read in full, or anything of concern was found, do not publish; report which lines and what.
   b. Use the Artifact tool (load it with ToolSearch if it is deferred). First read the existing artifact with action "read" and url "https://claude.ai/artifact/XdMsrTPzKDVHMP1tLmsUBA". Then publish to that same url: action "publish", url "https://claude.ai/artifact/XdMsrTPzKDVHMP1tLmsUBA", file_path the absolute path of the repository's dashboard.html. It replaces the whole page, so publish it as is. Do not pass files, capabilities, icon or force, and never publish without the url, which would create a separate artifact.
   c. If the publish is refused or asks for approval, do not retry; report the exact message.

5. Report. End with a short summary:
   - the build date and the six scenario ROICs (rent, Anthropic, OpenAI, open-only, open-peak, AWS) from this run's build line, with the change from the last build line dated before today in update.log;
   - steps that failed or kept old data (this run's update.log lines containing "FAILED", "kept" or "failed:");
   - rental price changes, new pricing notices, lab list-price moves and new deal candidates reported in this run's log;
   - the latest complete week's OpenRouter token revenue from this run's "token revenue:" log line (week, revenue, tokens, $/M, and the chart estimate if it gives one);
   - the commit SHA pushed to main, or why nothing was pushed;
   - the artifact version published and the line ranges the subagents read, or why it was not republished.
```
