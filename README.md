<img width="1478" height="861" alt="image" src="https://github.com/user-attachments/assets/f07b9a75-2c85-479a-974d-00803da5fccc" />

## GoodFirst

**Your first green square starts here.** GoodFirst helps beginners make their first open source
contribution. Paste a GitHub repo and (optionally) a question. GoodFirst answers the question from
the repo's own docs, maps out the files that matter, picks three good first issues, and shows the
evidence for every claim it makes. Anything it can't back up with what GitHub returned gets
crossed out. When your pull request's checks go red, it reads the failed log and explains what
broke.

The AI is **Gemma, an open-weight model, running on your own computer through Ollama**. There
are no API keys and no hosted LLM calls, and GitHub is only ever read, never written to.

Built for the DEV Hacktoberfest 2026 Weekend Challenge, **"Build for a Friend"**.

## Why I built this: Shivin

My friend Shivin wanted to make his first open source contribution. He had picked a project,
[AOSSIE-Org/DebateAI](https://github.com/AOSSIE-Org/DebateAI): a Go backend, a React frontend,
over a hundred open issues and a long README. He didn't know where to start. Which files matter?
How do I run it? Which issue is small enough for a first try?

So I built the first version of GoodFirst for him: paste the repo, ask your question, and get an
answer drawn from the project's own docs, a map of the important files, and three issues worth
trying, each with the evidence behind it.

He used it on DebateAI and opened his first pull request. Then the checks went red. The
failed CI log was about 2,500 lines long, and he couldn't tell which of them actually mattered.
That's a wall a lot of beginners hit, right after the hardest part is done. So I added **CI help**:
paste the pull request, and GoodFirst reads the failed checks, cuts the log down to the part around
the error, and explains in plain words what broke and how to fix it. Every log line it quotes is
checked against the real log.

A first pull request is a start, not a finish. So GoodFirst also has a page of open source programs
(GSoC, Outreachy, LFX and more) with their official dates, for the question that comes next: where
do I keep contributing?

I built it for Shivin, but nothing in it is specific to him. It works for anyone with a laptop and
a repo they want to contribute to.

## Who it's for

People who want to contribute to open source but don't know where to begin: students, career
switchers, anyone staring at a 2,000-file repo wondering which file to open. It's also for people
whose laptop is the only computer they have. GoodFirst is tuned for a Windows machine with 8 GB of
RAM and no GPU.

## Why local and open

- **No cost, no account, no key.** A beginner shouldn't need a credit card to get help reading a README.
- **Private.** Your questions and the repos you look at stay on your machine.
- **Works offline.** GitHub responses are cached, so a repo you've analyzed once keeps working without internet.
- **Honest by construction.** A small local model makes mistakes. Rather than hide that,
  GoodFirst checks every claim in plain Python and shows you what it removed and why. The model
  never fetches anything or picks tools itself. Code does all the fetching and checking.

## What it does

### 1. Repo explainer
Gemma reads the README, the contributing guide and the file list (cleaned and trimmed to fit an
8K-token context) and returns strict JSON: an answer to your question, a summary, setup steps,
important files, and questions worth asking the maintainers. If the docs don't answer your
question, it says so and writes a polite message for the maintainers that quotes it, instead of
guessing.

### 2. Issue picker
Code ranks the open good-first issues (unassigned, few comments, a clear description, skills
named in your question, recent activity). Gemma chooses three of the top six and explains why
each one fits and where to start. Titles, links, labels and comment counts always come from
GitHub, never from the model.

### 3. PR CI explainer (`/ci`)
Paste a pull request whose checks failed. GoodFirst fetches the failed GitHub Actions checks,
their annotations and job logs, and the files the PR changes. Code cuts the log down to the part
around the last error, and Gemma explains what failed, why, and how to fix it. The honesty check
removes quoted log lines that aren't really in the log and files that don't exist. It flags fix
commands that appear nowhere in the log, and cross-checks "was it my change?" against a fact
computed in code: does the error mention a file this PR changed? When confidence is low, it
writes a comment you can post on the PR yourself.

### 4. Honesty layer
Every claim becomes an evidence row with its source and a status: **verified**, **unchecked**
(from the docs, nothing to check against), **flagged**, or **removed** (shown struck through).

- Important files that don't exist in the repo are removed.
- Setup steps are removed when the repo has no contributing guide and no setup section in the README.
- Commands that aren't written word for word in the docs are flagged.
- Issue numbers that aren't in the fetched list are removed.
- Each invented file, log line or issue costs 10% confidence, up to 30%. With no README and no
  contributing guide, confidence is capped at 30%.
- Below the confidence floor (60% by default), the UI says so and offers a ready-to-copy question
  for the maintainers.
- If the model's JSON is invalid, GoodFirst retries once and then says plainly that it couldn't
  get a usable answer. It never invents a fallback.

### 5. Open source programs (`/programs`)
Hacktoberfest, Google Summer of Code, Outreachy, LFX Mentorship, MLH Fellowship, GSSoC, Summer of
Bitcoin and KWoC, each with official links and dates checked against the official site. The
status ("Applications open", "Live now", "Applications closed", "Next edition not announced") is
worked out from those dates and today's date. When a next edition has no official dates, the page
shows "Next edition not announced" rather than a guess.

## Architecture

<img width="1838" height="465" alt="image" src="https://github.com/user-attachments/assets/37ead323-0b24-473f-bf87-c59ecfc9f020" />


The CI explainer is a second fixed graph with the same shape: `fetch` (PR, checks, logs, changed
files) → `explain` (Gemma) → `honesty_check`. If there's neither a log nor an annotation to read,
the model isn't called at all.

- **Strict JSON:** each model call passes a JSON schema to Ollama's structured outputs, validates
  the reply with pydantic, and retries once.
- **Partial failure:** if the explainer fails, the issue picks are still shown, and vice versa.
- **Streaming:** the API runs the graph in a worker thread and streams one `step` event as each
  node starts and finishes, which drives the live timeline in the UI.

## Setup

### Requirements

- Windows 10/11 (these steps are written for Windows)
- 8 GB RAM is enough for the default `gemma3:4b` model; no GPU needed
- About 4 GB of free disk for the model, plus a few hundred MB for Python packages
  and about 500 MB for the web UI's Node packages
- Python **3.11 or newer**
- Node.js **20.9 or newer** (LTS) for the web UI: <https://nodejs.org>


### 1. Install Ollama and pull the model

1. Download and install Ollama from <https://ollama.com/download> (Windows installer).
   After installing, Ollama runs in the background (look for the llama icon in the system tray).
2. Open **PowerShell** and pull the model:

   ```powershell
   ollama pull gemma3:4b
   ```

   That is about 3.3 GB. If your laptop struggles, use the smaller model instead
   (about 815 MB, faster but less accurate):

   ```powershell
   ollama pull gemma3:1b
   ```

   and set `OLLAMA_MODEL=gemma3:1b` in `.env` (step 3).

3. Quick sanity check: `ollama run gemma3:4b "say hi"` should print a reply. Type `/bye` if it opens a chat.

### 2. Create a virtual environment and install packages

From the project folder (`D:\GoodFirst`):

```powershell
cd D:\GoodFirst
py -3.11 -m venv .venv            # or: python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1` ("running scripts is disabled"), run this once
and then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

(Using `cmd.exe` instead? Activate with `.venv\Scripts\activate.bat`.)

### 3. Configure

```powershell
copy .env.example .env
```

Every setting has a sensible default, so you can leave `.env` as is. Useful ones:

| Setting | Default | What it does |
|---|---|---|
| `OLLAMA_MODEL` | `gemma3:4b` | Which local model to use (`gemma3:1b` for low-RAM machines) |
| `OLLAMA_NUM_CTX` | `8192` | Context window; smaller = less RAM |
| `GITHUB_TOKEN` | *(empty)* | Optional. Raises the GitHub limit from 60 to 5000 requests/hour |
| `CONFIDENCE_FLOOR` | `0.6` | Below this, GoodFirst says it's unsure and suggests a question for the maintainers |

### 4. Check that Ollama works

```powershell
python scripts\check_ollama.py
```

This checks that Ollama is running, that the model is pulled, times one short answer,
and confirms the model can return valid JSON (GoodFirst depends on that).
The first answer is slower because the model is loaded into memory.

### 5. Run the tests

```powershell
pytest
```

(If a different pytest runs, use `python -m pytest` so the venv's own one is used.) Tests never touch the network or the
model; GitHub and the LLM are mocked.

### 6. Try the GitHub layer (no AI yet)

```powershell
python scripts\fetch_repo.py firstcontributions/first-contributions
python scripts\fetch_repo.py https://github.com/owner/repo --json   # full snapshot
```

This shows exactly what GoodFirst will later give the model: repo info, the cleaned and
truncated README/CONTRIBUTING, the file list, open "good first issue" issues, and notes
about anything missing. GitHub access is read-only (GET requests only). Responses are
cached in `.cache\` for an hour (`CACHE_TTL_S`), so repeat runs don't use up your rate limit.

### 7. Try it from the command line (local model)

```powershell
python scripts\explain_repo.py owner/repo --question "I know Python. How do I run the tests?"
python scripts\explain_repo.py owner/repo --lang hinglish
python scripts\explain_repo.py owner/repo --only issues     # just the Issue Picker (faster)
python scripts\explain_repo.py owner/repo --only explain    # just the Repo Explainer
python scripts\explain_repo.py owner/repo --show-prompt     # see exactly what the model reads
python scripts\explain_repo.py owner/repo --json -v         # full result + per-attempt logs
```

Your question is optional; when you give one, the whole analysis is aimed at it. The output lists
every change the honesty check made (see [Honesty layer](#4-honesty-layer)).

### 8. Run the web app

Two terminals. First the backend (FastAPI, from the project folder with the venv active):

```powershell
python -m goodfirst.api          # serves http://127.0.0.1:8000
```

Then the web UI (Next.js), in a second terminal:

```powershell
cd D:\GoodFirst\web
npm install                      # first time only; downloads ~500 MB of packages
npm run build
npm start                        # open http://localhost:3000
```

(`npm run dev` also works, for live reloading while editing.)

`POST /api/analyze` streams Server-Sent Events: one `step` event when each graph node starts
and finishes (`fetching`, `explaining`, `picking`, `honesty_check`, with timings), then one
`result` event (or `error`). The UI turns these into the progress timeline. `GET /api/health`
reports whether Ollama is running and the model is pulled. `POST /api/ci` works the same way for
the CI explainer (`fetching`, `explaining`, `honesty_check`).

**Offline:** GitHub responses are saved in `.cache\`. If GitHub can't be reached, GoodFirst uses
the saved copy even if it is older than `CACHE_TTL_S`, and says so in the results ("GitHub couldn't
be reached, so GoodFirst used data saved on ..."). Analyze a repo once while online and it will
work offline afterwards. The model already runs locally, and the UI's fonts are bundled.

### Deploying the web UI (optional)

The UI is a static Next.js app, so it can be hosted anywhere, for example on Vercel with the root
directory set to `web`. The model and the API still run on each visitor's own computer: the hosted
page calls `http://127.0.0.1:8000`. To allow that, add the hosted address to `CORS_ORIGINS` in
`.env`, for example `CORS_ORIGINS=http://localhost:3000,https://your-app.vercel.app`, and restart
the API. When the page can't reach a local backend, it shows a link to these setup steps.

### 9. Explain a failed pull request check

In the web app, open **CI help** (`http://localhost:3000/ci`). From the command line:

```powershell
python scripts\explain_ci.py https://github.com/owner/repo/pull/123
python scripts\explain_ci.py owner/repo#123 --lang hinglish
python scripts\explain_ci.py owner/repo#123 --show-prompt   # the trimmed log the model reads
python scripts\explain_ci.py owner/repo#123 --json
```

GitHub only gives job logs to signed-in users, so set `GITHUB_TOKEN` in `.env`. A fine-grained
token with no extra permissions is enough. Without one, GoodFirst falls back to the check's
annotations (the short error messages GitHub shows on the PR page). If neither exists, it says
so and doesn't ask the model to guess.

### 10. Mini eval

```powershell
python scripts\eval.py
```

Runs the full pipeline on the 10 repos in `eval\repos.txt` with your local model and writes
`eval\results.md` (a table: claims made, verified, flagged, removed by the honesty check, final
confidence, runtime) and `eval\results.json`. Every number comes from the real run; failed repos
are reported as failed. Without a `GITHUB_TOKEN` you may hit GitHub's 60 requests/hour limit
partway: run the same command again later and it resumes. Expect roughly 1 to 2 minutes per repo
on a CPU.

## Demo repos

These were used while building GoodFirst. Good first issues open and close all the time, so
your results will differ.

| Repo | Why it's a good demo | Try asking |
|---|---|---|
| `AOSSIE-Org/DebateAI` | The repo Shivin used. A real Go + React project with setup instructions in the README | "How do I run the backend and frontend locally?" |
| `freeCodeCamp/freeCodeCamp` | Detailed contributing docs and a `first timers only` label with open issues; the issue picker has real candidates | "How do I run this locally?" |
| `firstcontributions/first-contributions` | Built for first-timers; a clear, short README makes the explainer easy to follow. When tested it had no open good-first issues, which shows the "no beginner issues" path and its maintainer question | "What are the steps to make my first pull request?" |

For the CI explainer, use any public pull request with a failed GitHub Actions check (add a
`GITHUB_TOKEN` so GoodFirst can read the job log).

## Limitations

- **It's slow on a CPU.** On the author's 8 GB Windows laptop with `gemma3:4b`, the repo
  explainer took about 75 to 85 seconds and the issue picker about 30 to 37 seconds per run, with
  the model already loaded. The first run after starting Ollama also loads the model (about 25
  seconds). `gemma3:1b` is faster but less accurate.
- **Small-model mistakes still get through when they can't be checked.** The honesty layer can
  check files, issue numbers, quoted log lines and commands against real data. It can't check a
  summary sentence or an explanation of *why* something failed. Those are marked "unchecked", not
  "verified".
- **Hinglish is best-effort.** `gemma3:4b` sometimes answers in English when asked for Hinglish.
  GoodFirst detects this and shows a warning instead of hiding it.
- **Docs only.** The explainer reads the README, the contributing guide and the file list, not
  the source code. It can tell you where the backend lives, not how a function works.
- **Long docs are trimmed** to fit an 8K-token context (6,000 characters of README and 4,000 of
  contributing guide by default), so details near the end of a long README can be missed.
- **The CI explainer only reads GitHub Actions logs**, and only the part around the last error.
  Other CI services show just their summary. It looks at the first
  3 failed checks. It was built and tested against simulated GitHub responses; check
  its explanations against the real log, which is linked from every result.
- **GitHub rate limits.** Without a token, GitHub allows 60 requests an hour, which covers a few
  analyses. Cached responses don't count against the limit.
- **Program dates are a snapshot.** The programs page computes statuses automatically, but the
  dates themselves were checked by hand (see `VERIFIED_ON` in `web/lib/programs.ts`) and need
  updating when programs announce new editions.
- **Read-only by design.** GoodFirst never comments, forks or opens pull requests. The questions
  and comments it writes are for you to copy.

## Project layout

```
GoodFirst/
├── goodfirst/            # Python backend
│   ├── config.py         # all settings, read from .env
│   ├── cache.py          # on-disk cache for GitHub responses (offline fallback)
│   ├── github_client.py  # read-only GitHub fetching -> RepoSnapshot
│   ├── prompts.py        # system prompts + packing a snapshot into model-readable text
│   ├── schemas.py        # JSON shapes the model must return (pydantic + JSON schema)
│   ├── llm.py            # local Ollama calls: strict JSON, retry once, timings
│   ├── issues.py         # deterministic ranking of good-first issues
│   ├── honesty.py        # deterministic honesty check (+ evidence rows for the UI)
│   ├── graph.py          # LangGraph: fetch -> explain -> pick_issues -> honesty_check
│   ├── ci.py             # PR CI explainer: fetch, log trimming, prompt, honesty, graph
│   └── api.py            # FastAPI: /api/analyze and /api/ci (SSE), /api/health
├── scripts/
│   ├── check_ollama.py   # Ollama health + speed check
│   ├── fetch_repo.py     # try the GitHub layer on a real repo
│   ├── explain_repo.py   # repo explainer + issue picker from the command line
│   ├── explain_ci.py     # PR CI explainer from the command line
│   └── eval.py           # mini eval over eval/repos.txt -> eval/results.md
├── tests/                # pytest; GitHub and the model are faked, no network
├── web/                  # Next.js (App Router, TypeScript) + Tailwind
│   ├── app/              # pages: / (analyze), /ci, /programs
│   ├── components/       # form, timeline, results, CI results, programs list
│   └── lib/              # SSE client, types, programs data
├── eval/repos.txt        # repos used by scripts/eval.py
├── .env.example
└── requirements.txt
```

