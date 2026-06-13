# Bharat-Courts UI Wrapper Design

**Date:** 2026-06-13  
**Goal:** Build a simple, tab-based UI for all major bharat-courts features, backed by a Python service that wraps bharat-courts CLI commands.

---

## Architecture Overview

### Components

**1. Backend (Python Flask)**
- Wraps bharat-courts CLI commands as HTTP REST endpoints
- Each endpoint maps to a bharat-courts command and returns JSON
- Handles CAPTCHA solving (automatic via bharat-courts)
- Runs on a separate port (default: 5000) or same server

**2. Frontend (Single-page app - restructured index.html)**
- Tab-based navigation, one tab per major bharat-courts feature
- Forms to collect parameters (state, district, party name, date, etc.)
- Results displayed as sortable, filterable tables
- "Save to Portfolio" button to add cases to local storage
- Same localStorage-based persistence as original app

**3. Data Flow**
```
User fills form → Frontend POST/GET → Python backend → bharat-courts CLI → returns JSON → Frontend renders table
```

---

## Feature Tabs

### Tab 1: Court Selection
**Purpose:** Navigate the state/district/complex/establishment/court hierarchy to identify and save your default court codes.

**Workflow:**
1. Select State (dropdown, fetched from `/api/courts/states`)
2. Select District (dropdown, filtered by state)
3. Select Court Complex (dropdown, filtered by district)
4. Select Establishment (dropdown, filtered by complex)
5. Select Court (dropdown, filtered by establishment)
6. "Save as Default" button to store selection in localStorage

**Backend Endpoints:**
```
GET /api/courts/states
GET /api/courts/districts?state=27
GET /api/courts/complexes?state=27&dist=DIST_CODE
GET /api/courts/establishments?state=27&dist=DIST_CODE&complex=COMPLEX_CODE
GET /api/courts/courts?state=27&dist=DIST_CODE&complex=COMPLEX_CODE&est=EST_CODE
```

**Output:** Dropdown options with codes and names

---

### Tab 2: Cause List
**Purpose:** Pull the cause list (daily hearing schedule) for a specific court and date.

**Workflow:**
1. (Auto-populate from saved default court, or let user select court)
2. Date picker (default to today)
3. "Fetch Cause List" button
4. Results: table with columns: Item #, Case Number, Parties, Stage, Next Date, Judge, Court No.
5. "Save Cases" button to add all/selected rows to portfolio

**Backend Endpoint:**
```
GET /api/causelist?state=27&dist=DIST&complex=COMPLEX&est=EST&date=DD-MM-YYYY
```

**Output:** Array of cause-list entries (serial_number, case_number, parties, case_type, listing_date, judge, etc.)

---

### Tab 3: Search by Party
**Purpose:** Find all cases involving a specific party (petitioner or respondent).

**Workflow:**
1. Party name input (text field)
2. Year range (default to current year, allow custom)
3. (Optional) State/District filter to narrow scope
4. "Search" button
5. Results: table with columns: CNR, Case Number, Parties, Case Type, Status, Next Hearing, Court

**Backend Endpoint:**
```
GET /api/search-party?state=27&dist=DIST&complex=COMPLEX&est=EST&party=Joshi&year=2025
```

**Output:** Array of cases matching the party name and year

---

### Tab 4: Lookup by CNR
**Purpose:** Get full details of a specific case by its CNR (Case Number Registration).

**Workflow:**
1. CNR input (text field, auto-format)
2. "Lookup" button
3. Results: detailed view showing:
   - CNR, Case Number, Case Type
   - Parties (Petitioner/Respondent)
   - Court, Judge
   - Filing Date, Status, Next Hearing
   - Case History (all previous orders/disposals)
4. "Save Case" button to add to portfolio

**Backend Endpoint:**
```
GET /api/lookup-cnr?cnr=ABC1234567890123456
```

**Output:** Single case object with full metadata

---

### Tab 5: Orders & Documents
**Purpose:** Retrieve and download orders/documents for a specific case.

**Workflow:**
1. CNR input (or case number)
2. "Fetch Orders" button
3. Results: list of orders with:
   - Order Date, Order Type (Judgment/Interim Order/etc.)
   - Judge Name
   - Link to view/download PDF
4. "Download All" button for bulk PDF download

**Backend Endpoint:**
```
GET /api/orders?cnr=ABC1234567890123456
GET /api/order-pdf?cnr=ABC1234567890123456&order_id=ORDER_ID
```

**Output:** Array of orders with PDF URLs; PDF endpoint returns binary file

---

## Future Extension Tabs (Out of scope for Phase 1)

- **High Court Cases** — Same pattern as District Courts but for High Courts
- **Supreme Court** — Recent judgments, search by judge/party/citation
- **Archive Search** — Historical judgment search with DuckDB backend

---

## Data Model

### Local Storage Structure
```javascript
{
  "cases": [
    {
      id: "uuid",
      cnr: "ABC1234567890123456",
      caseNumber: "CS 123/2025",
      parties: { petitioner: "Name", respondent: "Name" },
      court: "District Court, Ahmednagar",
      nextHearing: "2026-07-15",
      status: "active",
      source: "bharatcourt", // or "iecourts"
      importedAt: "2026-06-13T10:00:00Z"
    }
  ],
  "courts": {
    default: {
      state: 27,
      state_name: "Maharashtra",
      district: "DIST_CODE",
      district_name: "Ahmednagar",
      complex: "COMPLEX_CODE",
      complex_name: "Central Complex",
      establishment: "EST_CODE",
      establishment_name: "Principal Seat",
      court: "COURT_CODE",
      court_name: "Court No. 1"
    }
  },
  "settings": {
    lastUpdated: "2026-06-13T10:00:00Z"
  }
}
```

---

## Backend Implementation

### Technology Stack
- **Framework:** Flask (Python 3.9+)
- **Dependency:** bharat-courts library (pip install bharat-courts[all])
- **Port:** 5000 (configurable)
- **.env:** Store any API keys or config (if bharat-courts requires auth in the future)

### Endpoint Pattern
Each endpoint:
1. Validates input parameters
2. Calls bharat-courts CLI or Python API
3. Parses and structures the output
4. Returns JSON with consistent schema: `{ success: bool, data: [...], error: string }`

### Error Handling
- CAPTCHA required → return `{ success: false, error: "CAPTCHA required", captcha_url: "..." }` (or handle automatically)
- Invalid court codes → return validation error
- Network timeout → return with error message
- Malformed input → return 400 Bad Request

---

## Frontend Restructure

### Current State
- index.html: 1122 lines, includes case management dashboard, eCourts live lookup, WhatsApp reminders
- Focus: importing bharat-courts JSON files manually

### New State (Phase 1)
- Simplify to a tab-based interface focused on bharat-courts queries
- Keep the case management features in the background (localStorage persistence)
- Remove the eCourts live lookup (replace with bharat-courts)
- Keep WhatsApp reminder draft functionality for cases added to portfolio

### Tab Navigation
```
Sidebar:
├── Court Selection
├── Cause List
├── Search by Party
├── Lookup by CNR
├── Orders & Documents
├── Portfolio (cases saved so far)
└── Settings
```

---

## Security & Performance

### Security
- Backend runs locally (no external exposure unless deployed)
- bharat-courts handles CAPTCHA solving internally
- No API keys exposed in frontend (all backend calls)
- localStorage for case persistence is browser-local only

### Performance
- Cache court hierarchy in localStorage (state/district/complex/establishment options) to avoid re-fetching on each tab visit
- Debounce search inputs to avoid duplicate requests
- Lazy-load tabs (don't fetch until tab is clicked)
- Pagination for large result sets (cause lists with 100+ entries)

---

## Testing & Validation

### Manual Testing Checklist
1. Court hierarchy loads correctly (all dropdowns populate)
2. Cause list fetches and displays for a valid date and court
3. Party search returns results matching the name
4. CNR lookup returns full case details
5. Orders display with download links
6. Cases can be saved to portfolio and persist on page reload
7. Error messages display when CAPTCHA is required or data is missing
8. Frontend renders table results correctly for different data sizes

### Edge Cases
- Empty result sets (no cases found)
- Very large result sets (100+ entries, test pagination)
- Date formats (ensure consistent DD-MM-YYYY)
- Special characters in party names (quote marks, dashes, etc.)
- Network timeouts and retries

---

## Deliverables

### Phase 1 (This Sprint)
1. `server.py` — Flask backend with 7 core endpoints
2. Restructured `index.html` — Tab-based UI with forms and tables
3. `.env` — Configuration (port, bharat-courts cache settings)
4. `README.md` — Updated with setup and usage instructions
5. Test data/examples in a `tests/` folder

### Phase 2 (Future)
- Integrate High Court and Supreme Court tabs
- Add archive search
- Extend case management dashboard to sync with portfolio
- WhatsApp integration for hearing reminders

---

## Success Criteria

1. ✅ User can navigate court hierarchy and fetch cause list in < 5 clicks
2. ✅ User can search for a case by party name and get results in < 3 seconds
3. ✅ User can look up a case by CNR and see full details
4. ✅ User can save cases to a local portfolio and access them later
5. ✅ All results display in clean, sortable tables
6. ✅ Error messages are clear and helpful
7. ✅ App works offline for saved cases; syncs with bharat-courts when online
