# The daily update routine

The dashboard is refreshed by a claude.ai cloud routine (a scheduled trigger), not by anything in GitHub.

- **Name:** AI Dashboard daily update
- **Schedule:** every day at 08:52 Sydney time (`CRON_TZ=Australia/Sydney 52 8 * * *`); a fresh cloud session per run
- **Environment:** the claude.ai cloud environment this repository was set up in. Its network reaches every host
  `update.py` reads (README, "Deploying to GitHub")
- **Pushes to:** `main`, one commit per run ("Daily update YYYY-MM-DD: ...")
- **Artifact:** ARTIFACT_URL, a private claude.ai page holding the latest `dashboard.html`, republished after each
  successful push

To change what the routine does, edit the routine itself on claude.ai (Routines), then update this file to match.
The instructions it runs, verbatim:

```
ROUTINE_PROMPT_TEXT
```
