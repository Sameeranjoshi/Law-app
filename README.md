# Joshi & Associates — Office App

Case management, eCourts sync, and WhatsApp client reminders for the office of
Adv. J. A. Joshi (Kopargaon / Ahilyanagar).

The web app (`index.html`) is a single page. A tiny Node backend (`server.js`)
holds the eCourtsIndia API key **server-side** and proxies court-data calls, so
the key is never exposed in the browser.

## Run it

You need Node.js 18 or newer.

```bash
# 1. put your key in place (already done if .env exists)
cp .env.example .env        # then edit .env and paste your eci_live_... key

# 2. start
npm start                   # or: node server.js

# 3. open
#    http://localhost:8787
```

That's it — no `npm install`, no build step.

## What it does

- **Dashboard** — cause list of upcoming dates; missed dates flagged in red.
- **Cases** — CNR, court, stage, FIR/PS, side, client, next date, status.
- **Clients** — directory with Marathi names; one-tap WhatsApp.
- **Notify** — drafts a hearing reminder in English or मराठी and opens WhatsApp
  with it pre-filled (you tap send).
- **eCourts** — live, through the backend:
  - **Find by advocate** — search the national index by name.
  - **Look up by CNR** — pull the latest status, parties, next date, history;
    "Refresh then fetch" asks eCourts to re-scrape first.
  - **Sync all cases** — bulk-refresh every CNR on file and update next dates,
    reporting which dates changed.

## Daily court data (free, self-hosted via bharat-courts)

The app does not scrape the courts. You run [bharat-courts](https://github.com/iamshouvikmitra/bharat-courts)
on your own machine and import its JSON:

```bash
pip install "bharat-courts[all]"

# find your court codes once (Maharashtra = state 27)
bharat-courts districtcourts districts --state 27
bharat-courts districtcourts complexes --state 27 --dist <DIST>
bharat-courts districtcourts establishments --state 27 --dist <DIST> --complex <CPLX>

# fill those into sync.sh, then each morning:
./sync.sh                # today's cause list  → ./exports/causelist-YYYYMMDD.json
./sync.sh "Joshi" 2025   # cause list + rebuild portfolio by party name
```

Then in the app: **eCourts → Import from bharat-courts → Upload .json**. A case search
fills in the portfolio (parties, CNR, court); a cause list stamps the next hearing dates.
The panel shows when you last imported.

## Security

- The API key lives **only** in `.env`, read by `server.js`. It is never sent to
  the browser and `.env` is git-ignored.
- **Rotate the key** in your eCourtsIndia dashboard — the current one was shared
  in a chat, so treat it as exposed and replace it.
- Never commit `.env`. Never paste the key into `index.html` or any client code.

## Hosting note

`index.html` + `server.js` run together as one Node service. To put this online,
deploy the whole folder to any Node host (Render, Railway, a small VPS) and set
`ECI_API_KEY` as an environment variable there instead of using a `.env` file.
Do not host `index.html` as a static-only site that calls eCourtsIndia directly —
that would expose the key.

## eCourtsIndia API

- Base: `https://webapi.ecourtsindia.com`  ·  Auth: `Authorization: Bearer eci_live_...`
- Endpoints used: `GET /api/partner/case/{cnr}`, `GET /api/partner/search`,
  `POST /api/partner/case/{cnr}/refresh`, `POST /api/partner/case/bulk-refresh`.
- Billing is credit-based per request; refresh/sync uses extra credits, so the
  "Sync all" button is meant for once or twice a day, not constant polling.
