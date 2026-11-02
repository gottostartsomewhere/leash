# Deploying Leash

Two free Render services, defined in [`render.yaml`](render.yaml).

The split is deliberate. A free **web service** sleeps after fifteen idle
minutes and takes about a minute to wake. A free **static site** is served
from a CDN and never sleeps. So the screen is the static site and always
loads instantly, and it knows how to wait for the API rather than showing a
visitor a dead page while the engine boots.

The API has to be a long-lived process rather than a serverless function,
because the whole ledger lives in memory. A cold start wipes it back to the
seeded demo, which for this is fine and arguably a feature.

## 1. Push, then create the blueprint

Render needs read access to the repository. It is private, so connect GitHub
and grant access to `gottostartsomewhere/leash` when asked.

In the Render dashboard: **New → Blueprint**, pick the repo, and it reads
`render.yaml` and offers both services. Nothing in that file is secret.

## 2. Fill in the secrets

Render asks for every `sync: false` variable once, in its own dashboard. They
never exist in this repository.

On **leash-api**:

| Variable | Where it comes from |
| --- | --- |
| `LEASH_PAYPAL_CLIENT_ID` | developer.paypal.com → Apps & Credentials → Sandbox |
| `LEASH_PAYPAL_SECRET` | the same app, behind a Show click |
| `LEASH_DEMO_RECEIVER_EMAIL` | Testing Tools → Sandbox Accounts → the **Personal** one |
| `LEASH_CHANNEL3_API_KEY` | optional; without it the offline catalogue runs |
| `LEASH_GROQ_API_KEY` | optional; only the LLM adversary uses it |

Leave any optional one blank and that part falls back to its offline
substitute. Nothing breaks.

## 3. Point the screen at the API

Chicken and egg: the static site needs the API's URL, which does not exist
until the API has deployed once. So after the first deploy, copy the API's
address (something like `https://leash-api.onrender.com`) and set it on
**leash-web** as:

```
VITE_API_BASE=https://leash-api.onrender.com
```

Then redeploy the static site, because Vite bakes that value in at build
time rather than reading it in the browser.

Check it took: open the site, and the top right should read **PayPal
sandbox** rather than **simulated payouts**. If it says simulated, the API is
up but has no credentials.

## 4. Check it

```bash
curl https://leash-api.onrender.com/health
```

```json
{"status":"ok","gateway":"paypal","catalog":"static",
 "paypal_configured":true,"channel3_configured":false}
```

Then open the static site and press **Run scenario**. Eleven attempts, five
refused, six holds. Approve them and a real sandbox batch goes out.

## The cold start

First visit after an idle spell takes about a minute while the API wakes. The
screen says so plainly instead of reporting an error, because it is not one.

If you want it warm for a judging window, `.github/workflows/keep-awake.yml`
pings `/health` every ten minutes. It is disabled by default and has to be
switched on in the Actions tab, deliberately: Render does not officially
support keeping free services awake, so turning it on is a choice to make
knowingly and for a limited period, not something to leave running forever.

## A note on who can call this

The API is open. There is no sign-in, because a judge has to be able to use
it, and there is nothing behind it worth protecting: the money is PayPal
sandbox money and the ledger resets on every restart. The one real cost is
Channel3 credits, which is why searches are cached.
