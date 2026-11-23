// Bang Sport Daily — on-time scheduler.
// GitHub's free scheduler often starts jobs hours late or skips them. This Cloudflare Worker runs on
// Cloudflare's cron (reliable, free) and simply asks GitHub to start the workflow at the right minute.
// GitHub's own schedule stays on as a backup; the writer stops by itself if the day's stories are done.
//
// Secrets/variables (Cloudflare › Workers › bang-sport-scheduler › Settings › Variables):
//   GITHUB_TOKEN  (secret)  fine-grained token: only repo putheamak/bang-sport-daily, permission "Actions: Read and write"
//   REPO          (text)    putheamak/bang-sport-daily

const JOBS = {
  "37 8,11,14 * * *": "daily.yml",      // 3:37 PM, 6:37 PM, 9:37 PM Cambodia time
  "41 1-17/4 * * *": "trending.yml",    // 8:41 AM, 12:41, 4:41 PM, 8:41 PM, 0:41 AM
  "11 */4 * * *": "headlines.yml",      // every 4 hours
};

async function dispatch(env, workflow) {
  const repo = env.REPO || "putheamak/bang-sport-daily";
  const r = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "bang-sport-scheduler",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  const text = r.status === 204 ? "started" : `failed ${r.status}: ${await r.text()}`;
  console.log(`${workflow}: ${text}`);
  return `${workflow}: ${text}`;
}

export default {
  async scheduled(event, env, ctx) {
    const workflow = JOBS[event.cron];
    if (workflow) ctx.waitUntil(dispatch(env, workflow));
    else console.log(`No job for cron ${event.cron}`);
  },
  // Visiting the Worker's address only shows a status line; nothing is started from the web.
  async fetch() {
    return new Response("Bang Sport Daily scheduler is running. Jobs: " + Object.values(JOBS).join(", "));
  },
};
