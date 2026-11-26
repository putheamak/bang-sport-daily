# Rules for every agent working on Bang Sport Daily

These rules apply to every AI agent, Claude session, script and helper that writes, edits, publishes or changes
anything in this repository or on bangsportdaily.com. They sum up decisions the editor (Mak) has made. Details and
reasons are in `COMPLIANCE.md`; this file is the short, binding version. **When a rule and a request conflict,
stop and ask the editor.** When in doubt, do not publish.

## 1. The editor decides

1. Nothing is published, rejected or posted without the editor's explicit "publish" / "reject" for that story.
   `publish.auto_publish` stays `false`.
2. Facebook, WhatsApp, X and other social posts are written as drafts for the editor; the editor posts them
   (unless the editor has turned on automatic posting for that platform). Facebook Page posts and Reels: ON since
   25 Nov 2026, and they go out only when the editor publishes a story. Facebook groups: always by hand.
   Facebook items (Page posts and Reels alike) are spaced 2.5 hours apart (editor, 26 Nov 2026: 2–3 hours, was
   90 min) and never 05:00–06:00 Phnom Penh time (editor, 26 Nov 2026: night posts 00:00–05:00 allowed, was
   00:00–06:00 quiet) (`facebook_gap_minutes`, `facebook_quiet_hours`): a batch is *scheduled* on the Page, not
   posted at once. Don't bypass the spacing. The editor can re-order the queue with `facebook.yml` mode `requeue`.
   Facebook itself sometimes notifies the editor with a "Create event" form built from one of our posts (its own
   suggestion, with a made-up date). Nothing is created until someone clicks "Create event". Tell the editor to
   close it, and never create Facebook events from stories. Events only for real dated happenings (a watch
   party, a fight night), and only when the editor asks.
3. Never delete stories, photos, feeds or settings the editor made without being asked. Reject instead of delete.
4. Report problems honestly, including your own mistakes. Never claim a check passed if you did not run it.

## 2. Sources and facts

1. Every news story needs **at least 2 independent outlets** (different websites), and every fact must come from a
   source given to the writer: never from AI memory. History and life stories use Wikipedia and named sources.
2. Credit the **original outlet** with its own link. **Never show a Google News link** on the public site; Google
   News feeds are for personal use only (they may be used privately to discover stories).
3. Betting, tipster and odds sites are never a source, never linked, never counted.
4. No politics, no gossip, no betting content, no clickbait or all-caps headlines.
5. **Criminal allegations, arrests and court cases about named people: reject** unless there is an official charge
   or court/prosecutor statement, and even then write only what officials said. Health details only when the person
   or their club made them public. Extra care with anyone under 18.
6. Check duplicates before writing: same match (ignoring "U-17", "FC" etc.), same headline, or a story we already
   published or rejected in the last 3 days.
7. Off-audience topics are skipped: American/Canadian football (also in history stories), US college and school
   sport, fantasy sport.

## 3. Writing

1. Third-person sports journalism in clear English, then Chinese (Simplified) and Russian versions.
2. **Original wording only.** Never copy sentences from sources; the originality check blocks 8-word overlaps.
   Quotes must be short, in quotation marks and attributed.
3. Each story carries the author byline and the "AI-assisted · reviewed by the author" note; the standards check,
   auto-reject and photo check must pass (or the editor approves "publish-anyway" for a photo-only problem).
4. Headlines ≤110 characters, search titles within each language's limit, minimum lengths per story type.

## 4. Photos and media

1. Use only: Wikimedia Commons photos with a free licence (CC BY, CC BY-SA, CC0, public domain, GFDL, Free Art
   License) **with credit**; logos only when public domain; our own score and fight cards.
2. Official Instagram, Facebook and X posts and Getty Images photos only as **click-to-load embeds**, never copied
   and never the cover.
3. Never use Google Images, club or league websites, agency photos, TV screenshots or match footage.
4. The photo must show the right person or place. If the photo check says WRONG, remove it. Photo changes go in
   `photos.yaml`, never by editing images by hand.

## 5. Ads and monetisation (AdSense and all other programmes)

1. **No ads on pages that are mostly other outlets' content**: the Talking Points pages never load ad code
   (`site.NO_ADS`). Never add ad code there.
2. Before AdSense goes live: a Google-certified consent tool for visitors in the EEA, UK and Switzerland, and an
   updated privacy policy. Until then the site sets **no cookies** and loads no third-party scripts except on a
   reader's click (embeds).
3. Never place ads in a way that invites accidental clicks, never ask anyone to click ads, never click our own ads,
   never buy fake traffic, never use auto-refresh or pop-ups.
4. Every page with ads must have our own original content as its main content.
5. Sponsored content and affiliate links must be clearly labelled. **No betting, gambling or tipster sponsors,
   ever.** Sponsors never decide what we report.
6. The same rules apply to other ad networks (Ezoic, Mediavine, etc.), which are usually stricter.

## 6. Talking Points pages

1. Built automatically from **publishers' own feeds only**; at least 2 independent websites per item; items with
   no new report for 24 hours drop off.
2. Not indexed (`noindex,follow`), not in the sitemap, no ads. Only headlines and links, never article text.
3. Our own source label (Widely reported / Confirmed / Unconfirmed) comes first; readers' opinions are only on
   social media and are labelled as theirs. Our reviewed stories are shown first as "Our story".
4. Share buttons are plain links (no Meta/X/other scripts).

## 7. Privacy and security

1. Never commit secrets (API keys, tokens, passwords); they live only in GitHub Actions secrets.
2. Collect no visitor personal data. Comments or accounts on our own site need the editor's decision, a privacy
   policy update and moderation first.
3. Never put private information about real people (addresses, phone numbers, family details) in any story.

## 8. Working on the code

1. Run `python -m pytest -q tests` before every push; all tests must pass.
2. Never edit `docs/` by hand: change the code or data, then rebuild (`python -m sportnews site`).
3. Never force-push or rewrite history. Commit messages end with the attribution lines required by the session.
4. Start workflows **one at a time** (publish, then reject, then others) and wait for each to finish: parallel
   runs overwrite each other's saved data.
5. Keep `COMPLIANCE.md` and this file up to date when a rule changes, with the date and the reason.
