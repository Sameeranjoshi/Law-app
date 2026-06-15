# Maharashtra Courts

Query Maharashtra district courts via [bharat-courts](https://github.com/iamshouvikmitra/bharat-courts).

## Setup

```bash
pip install -r requirements.txt
python server.py
```

Open http://localhost:5002 in your browser.

## Features

- **Select Court** — Pick your district and court complex (saved for next visit)
- **Cause List** — Daily hearing schedule for any date
- **Search by Party** — Find cases by litigant name
- **Case Lookup** — Look up a specific case by type, number, year
- **Advocate Scan** — Scan cause list for a specific advocate's cases
- **Orders** — Download court orders for a case
- **eCourts API** — National court data via the [eCourtsIndia Partner API](https://ecourtsindia.com/api/docs) (no CAPTCHA, all states). See [`Ecourtindia/`](Ecourtindia/README.md).

## eCourtsIndia API

The **eCourts API** tab is backed by a separate, authenticated REST data source.
Set your key before using it:

```bash
cp .env.example .env   # then fill in ECOURTS_API_KEY=eci_live_...
```

Details and route reference: [`Ecourtindia/README.md`](Ecourtindia/README.md).
