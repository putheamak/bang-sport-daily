# Compliance checklist: Google Search, AdSense, privacy and copyright

This file records what Bang Sport Daily does to stay within the rules, and what you still need to do before
running ads. It is a practical guide, not legal advice. Policies change, so re-check them before applying
for monetization.

## 1. Google Search: AI content and spam policies

| Rule | What the system does |
|---|---|
| AI content is allowed if it is helpful and original (Google, Feb 2023) | Stories add context, history and your view, not just a rewording of the news |
| **Scaled content abuse** (2024, updated 2026): no mass-produced or automatically reworded pages | Only 5 stories a day, every one approved by a person. An **originality check** compares each story with its source text, rewrites it once if it repeats too much, and flags it in your review if it still does |
| **Fact-check AI content before publishing** (Google guidance, 1 Oct 2026) | Nothing is published automatically. Every draft comes with a "Check before publishing" list and a fact-check checklist in Telegram and email |
| **No deceptive authorship.** "Made-up names" are called deception (Google, 1 Oct 2026) | Default byline is the real author ("By Mak"), with an author page and bio. Invented columnist names are off (`bylines: author`) |
| Who, how and why: be clear about how content is made | Every story says "AI-assisted · reviewed by the author" and links to the **Editorial policy** page |
| Thin or empty pages | Empty section pages get `noindex` and are left out of the sitemap |
| Structured data must be truthful | NewsArticle data names the real author, the publish date and the modified date |

**Your part:** actually check the facts before you approve a story. If a story is weak, reject it.
Quality matters more than quantity.

## 2. AdSense: before you apply

- [ ] **Own domain.** AdSense effectively needs a domain you own (for example `bangsportdaily.com`, about $10 a year). A `github.io` address is GitHub's domain, not yours.
- [ ] **Move hosting.** GitHub Pages' terms say Pages is *not allowed to be used as a free web-hosting service to run your online business*. Before showing ads, move the `docs/` folder to Cloudflare Pages or Netlify. Both are free and allow commercial sites. Then set `custom_domain` in `config.yaml`.
- [ ] **Enough content.** Have at least 30–50 good, original stories published over several weeks.
- [ ] **Required pages.** About, Editorial policy, Privacy, Terms and Contact already exist. Set `contact_email` in `config.yaml` to a real address you read.
- [ ] **Turn off the "Around the world" box** (`wire_box: false`). Some RSS feeds, such as BBC's, are for non-commercial use only.
- [ ] **Consent.** Visitors from the EEA, the UK and Switzerland must see a **Google-certified consent banner** before ad cookies are set. Use the free "Privacy & messaging" CMP inside AdSense and switch it on before ads go live.
- [ ] **Privacy policy.** Update the Advertising section on the day ads start.
- [ ] **After approval,** set `adsense_client: "ca-pub-…"`. The site then adds the AdSense script and `ads.txt` automatically.
- [ ] **Age.** You must be 18 or older and the account holder.

## 3. Copyright

- **Text.** Stories are original writing. Quotes are short, exact and attributed. Never paste whole articles.
- **Photos.** Only Wikimedia Commons files with free licences (CC, public domain). Logos, flags and "fair use" files are skipped automatically. Each photo shows its author, licence and source link, as the licences require. Never add photos from Getty, Reuters, AP or club websites.
- **No AI images of real people.** They can mislead readers and break platform rules.
- **Fonts.** Self-hosted under the SIL Open Font License (the licences are in `sportnews/fonts/`).
- **Takedown requests.** Answer them quickly through the contact address, and remove the item if the request is valid.

## 4. Privacy

- No accounts, no forms, no analytics and no cookies of your own at the moment.
- Fonts are served from your own site (no Google Fonts), so visitor IP addresses are not sent to Google for fonts. A German court fined a site for embedding Google Fonts in 2022.
- Photos load from Wikimedia, and the privacy policy says so.
- If you add analytics later (for example Google Analytics), that also needs consent in the EU, the UK and Switzerland. Update the privacy policy when you do.

## 5. Social platforms

- **Facebook monetization** excludes "unoriginal content". Post your own stories and summaries, not copies of other outlets' posts.
- **Telegram** channel ads and revenue sharing have their own rules. Keep posts free of gambling promotion and misleading claims.
- **Betting.** Betting content is blocked in `config.yaml`. Gambling ads and content are restricted almost everywhere, including AdSense.

## 6. Ongoing habits

1. Review every draft and use the checklist.
2. Reject gossip, rumours and stories you cannot verify.
3. Correct mistakes quickly and note the correction.
4. Keep the author bio truthful. Don't claim credentials you don't have.
5. Re-read Google's Search Essentials and the AdSense Program policies every few months.
