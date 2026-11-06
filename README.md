# Bang Sport Daily · 棒体育日报

A free, automated AI sport newsroom. Every morning it finds the biggest world sport stories, writes them in
**your voice in English**, adapts them into **Chinese and Russian**, and publishes them to a 3-language website
and Telegram channels after you approve.

**Running cost: $0.** GitHub Actions and GitHub Pages are free for public repos, the Gemini API has a free tier,
and Telegram is free. You can switch one line to Claude (paid) later for better writing quality.

```
06:07 Cambodia time, daily (GitHub Actions)
  1. COLLECT   free RSS: BBC, Guardian, ESPN, Sky, Google News EN/中文/RU, Championat
  2. RANK      merge the same story across outlets → more outlets = bigger story; 1 story per sport for variety
  3. WRITE     Gemini (free) + Google Search: English story in YOUR voice (style profile + memos)
  4. ADAPT     native Chinese + Russian versions (same facts, local names: 梅西 / Месси)
  5. REVIEW    full drafts → your private Telegram chat + email
  6. PUBLISH   you approve → website /en /zh /ru  +  Telegram channels EN / 中文 / RU
```

Daily mix (in `config.yaml → daily_plan`): **3 news stories**, **1 "On this day in sport"**, and **1 athlete life story** (rotating through `athletes.yaml`).

---

## Setup (about 30 minutes, once). Everything here is free.

### 1. GitHub repository
Create a **public** repo named `bang-sport-daily` and upload these files.
Then go to **Settings → Pages → Deploy from a branch → `main` / `/docs`**. Your site will be at
`https://<username>.github.io/bang-sport-daily/`. Put that address in `config.yaml → site.url`.

### 2. Free Gemini key
Go to **aistudio.google.com → Get API key**. You don't need a credit card. Then add it in **Settings → Secrets and variables → Actions** as `GEMINI_API_KEY`.

### 3. Telegram (free)
1. In Telegram, message **@BotFather** → `/newbot`, and save the token as the `TELEGRAM_BOT_TOKEN` secret.
2. Create 3 public channels (for example *Bang Sport Daily*, *棒体育日报*, *Bang Sport Daily RU*). Add your bot as an **admin** of each one.
3. Add these secrets: `TELEGRAM_CHANNEL_EN` = `@yourchannel_en`, plus `TELEGRAM_CHANNEL_ZH` and `TELEGRAM_CHANNEL_RU`.
4. For your **private review chat**, send your bot any message. Then open `https://api.telegram.org/bot<TOKEN>/getUpdates`, copy your `chat.id`, and save it as the secret `TELEGRAM_REVIEW_CHAT`.

### 4. Email digest (optional, free with Gmail)
Add secrets: `SMTP_USER` (your Gmail address), `SMTP_PASS` (a Gmail **App password**), and `EMAIL_TO`.

### 5. Your voice
Put 2–5 ebook chapters in `voice/samples/`. The **Learn my writing voice** workflow then rewrites `voice/style_profile.md` automatically. Read it and edit anything that doesn't sound like you. Then write your experiences in `memos/general.md`.

### 6. First run
Go to **Actions → Daily sport news → Run workflow**. Drafts arrive in your Telegram review chat in about 5–10 minutes.

---

## Daily routine (about 10 minutes)
1. *(Optional, before 6am)* Add `memos/YYYY-MM-DD.md` with your angle for the day. You can do this from your phone on GitHub:
   `Focus: the derby last night — I watched it at 2am in Phnom Penh.` · `skip: history`
2. Read the drafts in your Telegram review chat, and check the **⚠️ Check** list against the sources.
3. To publish, go to **GitHub app → Actions → Publish / reject stories → Run workflow**, then paste the full ID (or type `today`).
   The story goes to the website in all 3 languages and to all 3 Telegram channels.

Each month you can compile an ebook: `python -m sportnews book 2026-11 --published-only --lang zh`

## Free tier: what to expect
- `model: auto` picks the newest stable Gemini Flash model your key can use. If you hit the free quota, it switches to Flash-Lite automatically. Model names change often, so the code doesn't hard-code them.
- About 10–12 AI calls a day (one write call plus one translation call per story) is far below the free daily limit. Google changes free limits without notice, so check the quota page in AI Studio.
- **Privacy:** on the free tier, Google may use what you send to improve its models. That's fine for public sport news, but don't put private information in your memos.
- **Quality:** Flash is good but not the best for long, emotional stories. If the site grows, switch `ai.provider: claude` and add `ANTHROPIC_API_KEY`. That costs about $0.50–1 a day.

## Compliance (Google, AdSense, privacy)
See **COMPLIANCE.md** for what the system does and the checklist to finish before monetizing.

## Rules built in
- Feeds are used as **sources of facts**, never copied. Every story lists its sources, and the AI is told never to invent quotes or scores.
- Your memos are used only as **your** first-person view.
- Every page carries a short AI-assistance note. This is honest with readers and protects you with Google.
- No betting content (blocked keywords). Nothing goes public without your approval (`auto_publish: false`).
- Drafts are **not** put on the public website. The optional `drafts_on_site: true` adds a `review.html` page, but anyone who finds it can read it.

## Run on your PC (optional)
```bash
pip install -r requirements.txt
set GEMINI_API_KEY=...            # PowerShell: $env:GEMINI_API_KEY="..."
python -m sportnews collect       # see today's ranked stories (no AI used)
python -m sportnews daily
python -m pytest                  # tests
```
If no key is set, the system writes clearly marked mock drafts, so everything can be tested for free.

## Files
```
config.yaml      sources, sports & weights, languages, AI provider, publishing
athletes.yaml    athlete life-story rotation
voice/           style_profile.md + samples/ (your ebook chapters)
memos/           general.md · YYYY-MM-DD.md · athletes/<slug>.md
sportnews/       code: collect · llm (Gemini/Claude) · writer · publishers · site · exporters
docs/            the public website (generated)
data/ output/    article database, daily .md/.docx, monthly books (generated)
```
