# GoodFirst

A local AI buddy that helps a beginner friend make their first open-source contribution.

> **Status: Phase 0 (setup only).** The GitHub layer, Repo Explainer, Issue Picker and UI
> are being built in later phases. This README will be rewritten at the end to describe
> only what actually works.

GoodFirst runs an open-weight model (**Gemma, via Ollama**) entirely on your own computer.
It never calls a hosted LLM API, and it only *reads* from GitHub.

---

## Requirements

- Windows 10/11 (these steps are written for Windows)
- 8 GB RAM is enough for the default `gemma3:4b` model; no GPU needed
- About 4 GB of free disk for the model, plus a few hundred MB for Python packages
- Python **3.11 or newer**

## Setup on Windows

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

Tests never touch the network or the model; GitHub and the LLM are mocked.

### 6. Run the app

*(Arrives in Phase 4.)*

## Project layout

```
GoodFirst/
├── goodfirst/            # the app package
│   ├── __init__.py
│   └── config.py         # all settings, read from .env
├── scripts/
│   └── check_ollama.py   # Ollama health + speed check
├── tests/
│   └── test_config.py
├── .env.example
├── requirements.txt
└── pytest.ini
```
