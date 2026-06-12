# SchoolMeal Connect 🍱

A digital procurement portal for government schools running the Midday Meal Programme.

## What it does

Connects three groups in a shared digital space:
- **School Administration** (Principal/Headmistress/Staff) — browse & order food items
- **Merchants** (Vegetable/grocery suppliers) — list real-time stock and prices
- **Delivery Providers** — accept jobs and confirm delivery

## Features

- Role-based login (Principal, School Staff, Merchant, Delivery)
- Real-time inventory browsing with category filters
- One-click cart ordering with notes
- AI/ML demand prediction based on student attendance + past data
- Principal dashboard with spending charts and supplier rankings
- Delivery job board with status tracking
- Order status progression (Pending → Confirmed → Out for Delivery → Delivered)

## Quick Start

```bash
# 1. Install dependencies
pip install flask

# 2. Run the app
python app.py

# 3. Open in browser
http://localhost:5000
```

## Demo Accounts (password: demo123)

| Username     | Role          | Description                     |
|-------------|---------------|---------------------------------|
| `principal`  | Principal     | Full dashboard + spending view  |
| `staff1`     | School Staff  | Browse inventory + place orders |
| `merchant1`  | Merchant      | Vegetables supplier             |
| `merchant2`  | Merchant      | Grains, spices, oils supplier   |
| `delivery1`  | Delivery      | Accept and complete deliveries  |

## Tech Stack

- **Backend:** Python Flask
- **Database:** SQLite (file: `schoolmeal.db`)
- **Frontend:** Plain HTML/CSS/JS (responsive, no framework dependencies)
- **Charts:** Chart.js (CDN)
- **Fonts:** Google Fonts — Sora + DM Sans

## Project Structure

```
schoolmeal/
├── app.py              # Main Flask application & all routes
├── database.py         # SQLite schema + seed data
├── requirements.txt
├── schoolmeal.db       # Auto-created on first run
└── templates/
    ├── base.html               # Shared layout + design system
    ├── login.html              # Sign-in page
    ├── register.html           # Registration page
    ├── principal_dashboard.html
    ├── staff_dashboard.html    # Cart + AI suggestions
    ├── merchant_dashboard.html # Stock management
    ├── delivery_dashboard.html # Job board
    └── order_detail.html       # Order status tracker
```

## AI Demand Prediction

The `/ai/suggest` endpoint uses a weighted model:
- **Base:** Standard quantity per 100 students for each item category
- **Weighted:** 60% formula + 40% 7-day average actual consumption
- School staff enter today's attendance → system recommends quantities

## Deployment

For production, set the environment variable:
```bash
export SECRET_KEY=your-secure-random-key

```
## REPORT
##
##
