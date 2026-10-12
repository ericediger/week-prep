# Week Prep — a weekly rollover to-do list

A single-file, local-first weekly to-do app. Drop your week's raw material — meeting notes, emails, screenshots, PDFs — into a folder, and the app uses Claude to turn it into a prioritized action list. Unfinished items roll over to the next week automatically.

No server, no build step, no account. One HTML file, your files stay in your folder, and the only network call is to the Anthropic API when you ask it to read a week.

**[▶ Try the live demo](https://ericediger.github.io/week-prep/demo.html)** — the full app pre-loaded with a fictional week of sample data. No setup, no API key, nothing saved; click into the week, expand items, poke around.

## How it works

```
your week-prep folder/
├── Home.html            ← the app (open in Chrome or Edge)
├── projects.json        ← created for you: themes & projects for tagging
├── WO-260803/           ← one folder per week, named WO-YYMMDD (that week's Monday)
│   ├── meeting-notes.txt
│   ├── some-email.eml
│   ├── screenshot.png
│   └── todo-state.json  ← created by the app: the week's to-do list
└── WO-260810/
    └── …
```

1. **Connect** — open `Home.html` in Chrome or Edge and connect it to your folder (it uses the File System Access API to read and write directly; nothing is uploaded anywhere by connecting).
2. **Ingest** — when a `WO-YYMMDD` folder has source files but no to-do list yet, an *Ingest* banner appears. One click sends that folder's contents to Claude, which extracts the action items that are yours to act on, tags them with your themes/projects, and writes `todo-state.json`. Open items from the previous week are carried over automatically (with a ↩ badge and age counter).
3. **Work the week** — check things off, set a plan day (Mon–Fri), add subtasks, notes, and manual items. Everything saves back to `todo-state.json` as you type, so it syncs wherever your folder syncs (OneDrive, Dropbox, iCloud…).
4. **Weeks without emails** — click **+ New week** (creates the correctly-named Monday folder) or **Start … empty** on a folder you made yourself: the week opens with last week's open items carried over and nothing else, ready for manual entry or the Assistant. Drop files in later and Re-scan picks them up. The app also warns when a folder's date isn't a Monday or is far from today — a typo'd date silently files the week in the wrong place.
5. **Re-scan** — dropped in more emails on Wednesday? Hit **⟳ Re-scan week**: it reads only the files added since the last scan and asks Claude for genuinely new items — it won't duplicate what's on the list or resurrect items you removed.

## Features

- **AI ingest & re-scan** — reads `.txt`, `.eml`, `.pdf`, and images (screenshots work); merges duplicates; skips FYI-only noise.
- **Weekly rollover** — open items carry forward automatically with their subtasks and history.
- **Themes & projects** — two independent tagging axes (e.g. theme `LEGAL`, project `ACME-ROLLOUT`), with keywords for auto-tagging, per-project views, and a "Copy brief for LLM" button that packages a project's open items for pasting into a chat.
- **Feedback loop** — removing an item asks why ("not relevant", "already handled"…), and those reasons are fed back to the model so it stops surfacing that kind of item.
- **Dark mode** — ☾ toggle in the top bar; remembers your choice (defaults to your OS setting).
- **Plan, prioritize, search** — priority pills, plan-day column, due-date highlighting, full-text search, done-hiding, sortable columns.
- **✦ Assistant** — a chat drawer that sees the whole week and acts as an executive-assistant / productivity coach (default prompt included, editable in ⚙ AI). It can propose any change — plan days, priorities, done, new items, subtasks, removals, and creating / editing / retiring themes and projects — but **every change appears as a card you must explicitly Apply or Skip**; nothing touches your list without a click. Conversations persist per week in `todo-assistant.json`.

## Setup

1. Put `Home.html` in (or point it at) a folder where you'll keep week folders.
2. Open it in **Chrome or Edge** (the File System Access API isn't available in Safari/Firefox).
3. Click **⚙ AI** and add your [Anthropic API key](https://console.anthropic.com/). Optionally describe yourself ("Jane, a product director at Acme Corp") — this helps the model figure out which action items are *yours*. The key is stored only in your browser's localStorage, never written into the folder.
4. Create a `WO-YYMMDD` folder for the coming Monday, drop files in, and click **Ingest**.

A tiny sample week is included in `sample-week/` — copy `WO-260803` into your folder to try the flow.

## Use it from other devices — or let an AI agent read it

`Home.html` alone needs the folder picker, which only works on the machine that has the folder. `serve.py` (Python 3, no dependencies) lifts that limit: run it from your week-prep folder and the app is reachable from any phone, tablet, or laptop on your network — and readable by browser-based AI agents.

```bash
python3 serve.py          # or double-click "Start Server.command" on macOS
```

It prints URLs like these (the key is generated on first run and stored in `.serve-key`; delete that file to rotate it, or pass `--no-key` to disable it):

| URL | What it is |
|---|---|
| `http://<your-ip>:8877/?key=…` | The app — full read/write, no folder picker. Open once with the key; a cookie remembers it. |
| `http://<your-ip>:8877/brief?key=…` | **The current week as a clean, agent-friendly page**: open items sorted by priority and due date with plan day, project, carry-over age, subtasks, notes and context; plus done / not-doing / removed lists and project descriptions. Add `?week=WO-YYMMDD` for another week, or use `/brief.txt` for markdown. |
| `http://<your-ip>:8877/api/file/WO-260803/todo-state.json` | Raw JSON for a week (`PUT` to save). `/api/ls/` lists the folder. |

Point a personal-assistant agent at the `/brief` URL to have it review and prioritize your week; give it the app URL if you want it to set plan days or reorder priorities itself. The server only writes `todo-state.json` and `projects.json` (atomically, after validating the JSON), refuses paths outside the folder, and never serves dotfiles. It binds to all interfaces by default — use `--bind 127.0.0.1` for this machine only, or `--port` to change the port.

## Privacy notes

- Your files are read locally. Their contents are sent to the Anthropic API **only** when you click Ingest or Re-scan.
- The API key and your "about you" line live in browser localStorage — they are never written to the synced folder.
- Everything else (`todo-state.json`, `projects.json`) is plain JSON in your folder; there's no other storage.

## Extras

`extras/Review Week.command` is an optional macOS script for a manual, no-API-key workflow: it bundles a week folder's text into one file and prints a prompt you can paste into an AI chat app (e.g. Claude) to generate `todo-state.json` by hand.

## License

MIT
