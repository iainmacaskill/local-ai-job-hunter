# Getting started

A complete, beginner-friendly walkthrough: install the local AI, pick a model, set
up the tool, and use it day to day. No prior experience with AI models or the
command line is assumed. Every step is a one-time setup unless it says otherwise.

Total time: about 30 minutes, most of which is the model downloading in the
background while you do the rest.

**Contents**

1. [Before you start](#1-before-you-start)
2. [Install LM Studio (the local AI)](#2-install-lm-studio-the-local-ai)
3. [Download and select the model](#3-download-and-select-the-model)
4. [Start the local server](#4-start-the-local-server)
5. [Install the tool](#5-install-the-tool)
6. [Add your career facts](#6-add-your-career-facts)
7. [Turn on the job search (optional)](#7-turn-on-the-job-search-optional)
8. [How to use it](#8-how-to-use-it)
9. [Command-line use (optional)](#9-command-line-use-optional)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Before you start

You need two things.

- **A reasonably powerful computer.** The AI runs on your own machine, so the
  machine does the work a cloud server would normally do. It was built and tested
  on an Apple silicon MacBook. As a rough guide:
  - **32 GB of RAM or more** (or unified memory on Apple silicon): run the default
    27-billion-parameter model, `qwen/qwen3.6-27b`. Best quality.
  - **16 GB of RAM:** run the smaller `qwen3.5-9b` instead. It is lighter and
    faster, with a modest drop in quality. The tool supports it out of the box.
  - **Less than 16 GB:** you can still try the 9B model, but expect it to be slow.
- **Google Chrome or Chromium installed.** The designed interview PDF is rendered
  through headless Chrome. The plain screening CV (`.docx`) and everything else
  work without it; only the PDF needs it.

You do **not** need a ChatGPT subscription, an API bill, or any account for the AI
part. It is all free and local.

---

## 2. Install LM Studio (the local AI)

[LM Studio](https://lmstudio.ai/) is a free desktop app that runs AI models on your
own computer and exposes them to other tools (like this one) through a small local
server. Think of it as the engine; this tool is the steering wheel.

1. Go to **[lmstudio.ai](https://lmstudio.ai/)** and download the version for your
   operating system (macOS, Windows, or Linux).
2. Open the downloaded file and install it the same way you would any other app.
3. Launch LM Studio. On first run it shows a welcome screen; you can skip any
   onboarding prompts, you will do the important steps below by hand so you
   understand them.

---

## 3. Download and select the model

A "model" is the AI itself: a large file the app loads into memory. You download it
once.

1. In LM Studio, click the **search / discover** icon (a magnifying glass) in the
   left sidebar.
2. In the search box, type the model name for your machine:
   - 32 GB+ RAM: **`qwen/qwen3.6-27b`**  (the default this tool is tuned for, about
     16 GB to download)
   - 16 GB RAM: **`qwen3.5-9b`**  (smaller and faster)
3. Pick the matching result. LM Studio may offer several **quantisations** (compressed
   versions, labelled things like `Q4_K_M`). If you are unsure, accept LM Studio's
   recommended / default download: it chooses one that fits your machine.
4. Click **Download** and let it finish. This is the big, one-time download; it runs
   in the background, so carry on with the steps below while it completes.

> **Why this model?** `qwen3.6-27b` is a strong local reasoning model that this tool
> has a specific trick for (see the README's "For developers" note). Any qwen-family
> model works, because they share the same prompt template. You are not locked in.

**You do not have to memorise the exact model name.** The tool auto-detects whatever
model LM Studio has loaded: if you have exactly one (non-embedding) model loaded, it
just uses that one, whatever it is called. Loading a different qwen model is enough
to switch.

---

## 4. Start the local server

This is the step that makes the model reachable by the tool. You will do this each
time you want to draft (it takes two clicks).

1. In LM Studio, open the **Developer** tab (left sidebar; on some versions it is a
   "Local Server" or `>_` icon).
2. At the top, **select / load the model** you downloaded so it is resident in
   memory.
3. Make sure the server **port is `1234`** (the default). This tool expects
   `http://localhost:1234`.
4. Click **Start Server** (or toggle the server **On**).

That is it. LM Studio is now listening locally, and nothing about your data leaves
your machine. Leave LM Studio running while you use the tool. When you are done for
the day you can stop the server; start it again next time.

> Want to check it is working? The tracker shows a small model badge once it can see
> the loaded model. If it cannot, see [Troubleshooting](#10-troubleshooting).

---

## 5. Install the tool

Now install the job hunter itself. These commands go in a **terminal** (on macOS:
open the **Terminal** app; on Windows use **PowerShell** or WSL). Copy and paste one
block at a time.

```bash
git clone https://github.com/iainmacaskill/local-ai-job-hunter
cd local-ai-job-hunter
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

What those lines do, in order: download the tool, move into its folder, create an
isolated Python environment (`.venv`) so nothing touches your system Python, and
install the tool's dependencies into it.

> **Windows note:** the virtual-environment path uses a backslash. Use
> `.\.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt`, and
> `.\.venv\Scripts\streamlit` / `.\.venv\Scripts\python` in the later commands.

---

## 6. Add your career facts

The tool never invents experience. Everything it writes is grounded in one file you
control: `profile.json`. Create yours from the example:

```bash
cp profile.example.json profile.json
```

Open `profile.json` in any text editor and fill in **your** real details: your name,
your competencies, and each job with its title, company, dates, and bullet points.
This file is the single source of truth. The AI is only allowed to rephrase what is
here; it cannot add an employer, change a job title, stretch a date, or invent a
metric. Anything it tries is blocked or flagged before a document is saved.

`profile.json` is **gitignored**: it stays on your machine and is never committed or
uploaded.

---

## 7. Turn on the job search (optional)

You can draft CVs for any advert you paste in without this step. But to have the tool
**find** roles for you, add a free Adzuna key.

1. Go to **[developer.adzuna.com](https://developer.adzuna.com)** and register.
   An app id and key are issued instantly and are free.
2. In the tool's folder, create a file called **`.env`** and put your keys in it:

   ```
   ADZUNA_APP_ID=your-id
   ADZUNA_APP_KEY=your-key
   REED_API_KEY=your-key
   ```

3. Reed is an optional extra. A [Reed](https://www.reed.co.uk/developers) key can
   take a while to be issued, but it is worth having because Reed returns the full
   job description rather than a short snippet. The tool works fine with Adzuna
   alone; leave the Reed line out if you do not have a key yet.

`.env` is **gitignored**, so your keys stay local. For safety, tighten its
permissions so only you can read it:

```bash
chmod 600 .env
```

---

## 8. How to use it

Start the tracker (LM Studio's server should be running, from step 4):

```bash
./.venv/bin/streamlit run app.py
```

Your browser opens the board. Here is the everyday loop.

1. **Find roles.** Use the search panel at the top to run a sweep (for example,
   keywords "ai delivery manager", a location, a distance). New, relevant roles land
   on the board as **Found**. Roles you have already seen, duplicate re-posts of the
   same vacancy, and roles needing security clearance are skipped automatically. You
   can also skip this and just paste an advert into a role you add by hand.
2. **Triage.** Read each **Found** role's advert and decide: **Pass** (not for you),
   or set it to **Draft CV** (or **Draft CV & Cover Letter**). Tidying is
   bulk-friendly: tick rows and delete to archive them. Archiving is reversible, and
   a future search will not re-add an archived role.
3. **Draft.** On a role set to draft, press the draft button. The AI on your laptop
   rewrites your real experience to mirror the advert and produces:
   - a plain **screening `.docx`** (single column, no tables, so automated screening
     systems parse it cleanly),
   - a designed **interview `.pdf`** for human readers (needs Chrome), and
   - a **cover letter** if you chose that option.
   This takes roughly 50 seconds and costs about £0.
4. **Read the honesty report.** Every draft is checked against your `profile.json`
   before it is saved. You will see a coverage score (how many of the advert's
   keywords you genuinely match), any gaps it is honest about, and any **review**
   warnings (for example an unverified figure). Read the review lines before you
   send anything. If the AI ever alters an employer, title, or date, the draft is
   **blocked**, not saved.
5. **Download and apply.** Download the documents, do your own final polish, and
   apply. Then mark the role **Applied**. From here the conversation with the
   recruiter is yours; the tool tracks the search, not the relationship.
6. **Follow up.** Two working days after you apply, the role resurfaces with a short
   drafted follow-up note and a button that opens it in your own email app. The
   recruiter's address is only ever taken from the advert or typed in by you, never
   guessed, and the tool never sends anything for you.

Drafted documents land in the `outputs/` folder, which is gitignored.

> **Treat every draft as a first draft.** A laptop-sized model is fast, free, and
> honest, but it is not as strong as a frontier cloud model. Review and polish
> before you send, especially for a role that really matters.

---

## 9. Command-line use (optional)

If you prefer the terminal, you can draft one-off documents without the board. Save
an advert into a text file (`jd.txt`) first.

```bash
# a screening CV and interview PDF for one advert
./.venv/bin/python draft_cv.py --jd-file jd.txt --title "The Role Title"

# a cover letter
./.venv/bin/python draft_cover.py --jd-file jd.txt --title "The Role Title" --company "The Company"

# find roles from the free job-board APIs
./.venv/bin/python hunt.py --source adzuna --location London --keywords "ai delivery manager"
```

Each draft prints its coverage, keyword gaps, and honesty report. If a draft fails
the honesty guard (an altered employer, title, or date), it exits without writing a
document and tells you why.

---

## 10. Troubleshooting

**"local endpoint unreachable" / the tool cannot see the model.**
LM Studio's server is not running or is on the wrong port. Open LM Studio, go to the
Developer tab, load a model, confirm the port is `1234`, and press Start Server
(step 4).

**"insufficient system resources" when drafting.**
The model is too large for the free memory on your machine. Close other heavy apps,
or switch to the smaller `qwen3.5-9b` model (download it in step 3, load it in
step 4). The tool auto-detects the newly loaded model.

**Drafting is very slow.**
A smaller model (`qwen3.5-9b`) drafts faster. Speed also depends on how much else is
running; closing memory-hungry apps helps.

**The interview PDF does not appear, but the `.docx` does.**
The PDF needs Google Chrome or Chromium installed. Install it and redraft. The rest
of the tool works without it.

**I want to use a different endpoint or model (for example Ollama).**
Override the defaults with environment variables (or lines in `.env`):

```
CVDRAFTER_LLM_URL=http://localhost:11434/v1
CVDRAFTER_LLM_MODEL=qwen3.5-9b
```

Ollama listens on port `11434`; qwen models there work because they share the same
prompt template.

**Where is my data?**
On your machine, nowhere else. `profile.json`, the `outputs/` folder, the tracker
database, and your `.env` keys are all local and gitignored. The only thing that
ever leaves your computer is the job-board search request itself.
```