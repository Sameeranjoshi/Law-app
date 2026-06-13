# Joshi & Associates — Bharat-Courts Query Tool

A simple, tab-based web interface for querying Indian court data via bharat-courts.

## Quick Start

### Prerequisites

- Python 3.9 or newer
- pip (comes with Python)

### Install & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure your API key (optional, if using eCourtsIndia features)
cp .env.example .env
# Edit .env and add your ECI_API_KEY if needed

# 3. Start the backend
python server.py

# 4. Open the app
# Open this file in your browser:
# file:///path/to/app_bharatcourt/index.html
```

The backend runs on `http://localhost:5001` (or 5000 if available) and the frontend is a static HTML file.

## Features

### Court Selection
Navigate the state → district → complex → establishment → court hierarchy. Save your default court to avoid re-selecting each time.

### Cause List
Fetch the daily hearing schedule for a specific court and date. See case numbers, parties, judges, and hearing times.

### Search by Party
Find all cases involving a specific party (petitioner or respondent) for a given year.

### Lookup by CNR
Get full details of a case by its Case Number Registration (CNR).

### Orders & Documents
Retrieve orders and documents for a specific case (feature available with eCourtsIndia API).

## Troubleshooting

### "Can't reach backend" error
- Make sure `python server.py` is running in another terminal
- Check that it says `▲ Bharat-Courts Backend running → http://localhost:5001`

### bharat-courts CAPTCHA required
- The tool automatically solves CAPTCHAs using OCR. If it fails, you may need to retry or check your internet connection.

### Missing results
- Different courts have different levels of data availability in bharat-courts
- Try with a different state/district or date range

## Architecture

- **Backend:** Python Flask service wrapping bharat-courts CLI
- **Frontend:** Static HTML/JavaScript single-page app
- **Data Storage:** Browser localStorage (cases, default court, settings)

## Next Steps

- High Court queries (same pattern as District Courts)
- Supreme Court judgment search
- Historical judgment archive search
- Integration with WhatsApp reminders (from original app)

## Original App

The original case-management dashboard is archived in `index-original.html` if you want to restore it.
