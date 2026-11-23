# On-time scheduler (Cloudflare Worker)

GitHub's free scheduler starts jobs late or skips them. This Worker uses Cloudflare's cron to start the
writer, the trending radar and the headline refresh on time. GitHub's own schedule stays as a backup.

## Set up once (about 10 minutes)

1. **GitHub token.** GitHub › Settings › Developer settings › Personal access tokens › Fine-grained tokens ›
   Generate new token. Name: `bang-sport-scheduler`. Expiration: 1 year. Repository access: *Only select
   repositories* › `bang-sport-daily`. Permissions › Repository › **Actions: Read and write** (nothing else).
   Generate and copy the token.
2. **Create the Worker.** Cloudflare dashboard › Workers & Pages › Create › Create Worker. Name:
   `bang-sport-scheduler` › Deploy. Then *Edit code*, replace everything with `worker.js` from this folder,
   and *Deploy*.
3. **Add the token.** Worker › Settings › Variables and Secrets › Add: type **Secret**, name `GITHUB_TOKEN`,
   value = the token. Add: type **Text**, name `REPO`, value `putheamak/bang-sport-daily`.
4. **Add the timers.** Worker › Settings › Triggers › Cron Triggers › Add, three times:
   - `37 8,11,14 * * *` (writer)
   - `41 1-17/4 * * *` (trending radar)
   - `11 */4 * * *` (headlines)
5. **Test.** Triggers page shows the next run times. After the next one, GitHub › Actions should show a run
   started by `workflow_dispatch` within a minute of the time. Worker › Logs shows `daily.yml: started`.

If the token expires, runs stop starting from Cloudflare (GitHub's backup schedule still runs): make a new
token and replace the secret.
