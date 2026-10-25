# EmailCheck — Email Verification & Deliverability Diagnostics

EmailCheck is a full-stack, responsive web application designed for non-invasive email verification. It inspects email addresses across multiple diagnostic layers—RFC syntax compliance, DNS domain existence, and Mail Exchanger (MX) routing with RFC 5321 implicit MX fallback, alongside optional safe SMTP recipient handshakes.

The application classifies addresses into three conservative, transparent statuses:
1. **Likely to be Delivered**
2. **Likely to Bounce**
3. **Unknown**

---

## Table of Contents

- [Live Demo & Repository Links](#live-demo--repository-links)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Verification Architecture & Methodology](#verification-architecture--methodology)
- [Classification Criteria](#classification-criteria)
- [Hosting & Outbound SMTP Compatibility](#hosting--outbound-smtp-compatibility)
- [Privacy & Anti-Abuse Safeguards](#privacy--anti-abuse-safeguards)
- [Local Installation & Setup](#local-installation--setup)
- [Running Automated Tests](#running-automated-tests)
- [API Documentation](#api-documentation)
- [Production Deployment Guide](#production-deployment-guide)

---

## Live Demo & Repository Links

- **Live Application URL:** [https://emailcheck-7c9y.onrender.com/](https://emailcheck-7c9y.onrender.com/)
- **GitHub Repository URL:** [https://github.com/Zenith150/emailcheck](https://github.com/Zenith150/emailcheck)
- **Deployment Status:** **Active & Verified on Render** (`GET /health` $\rightarrow$ 200 OK)

> **Deployment Verification:** The application is live and publicly accessible at [https://emailcheck-7c9y.onrender.com/](https://emailcheck-7c9y.onrender.com/). All public endpoints (`/`, `/health`, and `POST /api/verify`) are verified and operational.

---

## Key Features

- **Multi-Layer Non-Invasive Verification:**
  - RFC 5322 & RFC 5321 syntax and format validation.
  - DNS resolution checking active MX records, NXDOMAIN existence, and A/AAAA implicit MX fallback.
  - Optional safe SMTP recipient probing (without ever transmitting message bodies).
- **Conservative Classification:** Never assumes mailbox existence when servers refuse disclosure, use catch-all routing, or block outbound port 25.
- **Batch Processing with Memoization:** Efficient in-memory caching prevents redundant DNS queries and SMTP connections for duplicate domains and addresses within the same request.
- **Modern Responsive Dashboard:**
  - Clean, accessible interface with real-time address counter (up to 100 per batch).
  - Summary metrics cards (Total, Delivered %, Bounce %, Unknown %).
  - Live search and status-based filter tabs (All, Delivered, Bounce, Unknown).
  - One-click RFC 4180 compliant **CSV Export**.
  - Host environment detection banner indicating whether outbound SMTP port 25 is accessible.
- **Production-Ready Backend:** Flask REST API with sliding-window rate limiting, input sanitization, health monitoring (`/health`), and WSGI production server configuration (`gunicorn`).

---

## Technology Stack

- **Frontend:** HTML5, CSS3 (Custom Design System with responsive grid and accessible color contrasts), Vanilla JavaScript (ES6+).
- **Backend:** Python 3.11, Flask 3.1.
- **DNS / Mail Routing:** `dnspython` (configured with public nameserver fallbacks to avoid virtual interface DNS timeouts).
- **Syntax Validation:** `email-validator` library with RFC 5322 regex fallback.
- **Mail Protocol:** Python standard library `smtplib` and `socket` (safe socket timeouts, strict handshake termination without DATA commands).
- **Production WSGI:** `gunicorn`.
- **Testing:** Python `unittest` suite (31 automated unit, integration, and mocking tests).
- **Documentation & Reporting:** ReportLab PDF Generation (`EmailCheck_Project_Submission.pdf`).

---

## Verification Architecture & Methodology

```
[ User Input ] ---> [ Rate Limiter & Sanitizer ]
                            │
                            ▼
              [ 1. Syntax Validation ] ───(Malformed)───► [ Likely to Bounce ]
                            │
                         (Valid)
                            ▼
              [ 2. DNS / Domain Check ]
                 ├── NXDOMAIN ──────────────────────────► [ Likely to Bounce ]
                 ├── DNS Timeout / Error ──────────────► [ Unknown ]
                 ├── No MX & No A/AAAA ────────────────► [ Likely to Bounce ]
                 └── MX Found (or Implicit MX A/AAAA)
                            │
                            ▼
              [ 3. SMTP Check (Optional) ]
                 ├── Disabled / Skipped ───────────────► [ Likely to be Delivered ]*
                 ├── Port 25 Blocked / Timeout ────────► [ Unknown ]
                 ├── Greylisting / 4xx / 252 ──────────► [ Unknown ]
                 ├── Catch-All Server Detected ────────► [ Unknown ]
                 ├── 550 / 55x Mailbox Rejected ───────► [ Likely to Bounce ]
                 └── 250 OK (Specific Mailbox) ────────► [ Likely to be Delivered ]
```

*\*Note: Explains that domain routing is active, but individual mailbox existence is an estimate and not guaranteed.*

---

## Classification Criteria

| Classification | Meaning | Underlying Conditions |
| :--- | :--- | :--- |
| **Likely to be Delivered** | Address syntax is valid and domain is actively configured to receive mail. | • RFC syntax valid<br>• Domain exists with active MX records or valid implicit MX (A/AAAA)<br>• If SMTP attempted: Server returned 250 OK for recipient and is not a catch-all domain.<br>*(Not a guarantee of inbox delivery)* |
| **Likely to Bounce** | Mail sent to this address will almost certainly fail or be rejected. | • Malformed syntax (missing `@`, consecutive dots, invalid characters)<br>• Domain confirmed nonexistent in DNS (`NXDOMAIN`)<br>• Domain has no MX or A records<br>• Mail server explicitly returned permanent failure (SMTP 550–554) |
| **Unknown** | Deliverability cannot be reliably established with non-invasive checks. | • DNS query timed out or server failed<br>• Cloud hosting provider blocked outbound port 25<br>• Mail server configured as catch-all (accepts all addresses indiscriminately)<br>• Greylisting or temporary server error (SMTP 4xx)<br>• Mail server refused to disclose mailbox existence (SMTP 252) |

---

## Hosting & Outbound SMTP Compatibility

### Outbound Port 25 Restrictions
Most modern cloud hosting platforms (such as **Render**, **AWS EC2** by default, **DigitalOcean**, and **Heroku**) restrict or block outbound connections on TCP port 25 to prevent spam and network abuse.

### How EmailCheck Handles This:
1. **No Fake Results:** EmailCheck dynamically checks outbound SMTP connectivity upon boot. If port 25 is blocked, it does **not** pretend the mailbox check succeeded.
2. **Transparent Fallback:** When outbound port 25 is blocked or restricted, the UI displays an informational notice, and deep SMTP checks return `Unknown` (or standard DNS verification is utilized).
3. **Core Functionality Remains 100% Operational:** Syntax validation, domain existence verification, and DNS MX mail exchanger checks function without requiring port 25.

---

## Privacy & Anti-Abuse Safeguards

- **Zero Email Transmission:** EmailCheck **never sends emails**. It never issues the SMTP `DATA` command and never transmits any message headers or body content.
- **Zero Permanent Storage:** Submitted email lists are processed entirely in-memory and are never written to disk, databases, or third-party storage.
- **Privacy-First Logging:** Full email addresses are **never logged**. Server logs record only batch sizes, timestamps, and domain routing statuses.
- **Batch Limits & Throttling:** Requests are limited to a maximum of 100 email addresses per batch, protected by a sliding-window rate limiter (30 requests/minute per IP).
- **XSS Prevention:** All user inputs rendered in the frontend table and CSV exports are strictly sanitized and HTML-escaped.

---

## Local Installation & Setup

### Prerequisites
- Python 3.11+
- Git

### Installation Steps

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd shieldnxt
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # On Windows
   python -m venv venv
   .\venv\Scripts\activate

   # On macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the local development server:**
   ```bash
   python app.py
   ```

5. **Open your browser:**
   Navigate to [http://localhost:5000](http://localhost:5000)

---

## Running Automated Tests

The test suite contains 31 automated tests covering syntax rules, mocked DNS behaviors, mocked SMTP handshake scenarios, deduplication, batch limits, and API endpoints.

To run the automated tests:
```bash
python -m unittest discover tests -v
```

All 31 tests run isolated from the network via mocks and complete in under 1 second.

---

## API Documentation

### 1. Health Check
- **Endpoint:** `GET /health`
- **Response:**
  ```json
  {
    "status": "healthy",
    "service": "EmailCheck",
    "version": "1.0.0",
    "smtp_outbound_available": true,
    "max_emails_per_request": 100
  }
  ```

### 2. Verify Email Batch
- **Endpoint:** `POST /api/verify`
- **Headers:** `Content-Type: application/json`
- **Request Body:**
  ```json
  {
    "emails": [
      "alex@gmail.com",
      "malformed..syntax@@domain",
      "user@nonexistent-domain-1234.org"
    ],
    "smtp_check": false
  }
  ```
- **Response:**
  ```json
  {
    "success": true,
    "total": 3,
    "summary": {
      "total": 3,
      "likely_to_deliver": 1,
      "likely_to_bounce": 2,
      "unknown": 0
    },
    "results": [
      {
        "email": "alex@gmail.com",
        "syntax_valid": true,
        "domain": "gmail.com",
        "domain_status": "exists",
        "mx_status": "mx_found",
        "mx_records": [
          "gmail-smtp-in.l.google.com (priority 5)"
        ],
        "smtp_status": "skipped",
        "smtp_details": null,
        "classification": "Likely to be Delivered",
        "reason": "Valid syntax and active MX mail routing verified. Note: This confirms the domain is prepared to receive mail, but is not an absolute guarantee of inbox delivery."
      },
      {
        "email": "malformed..syntax@@domain",
        "syntax_valid": false,
        "domain": "",
        "domain_status": "untested",
        "mx_status": "untested",
        "mx_records": [],
        "smtp_status": "skipped",
        "smtp_details": null,
        "classification": "Likely to Bounce",
        "reason": "Invalid email syntax: Email contains multiple '@' symbols.."
      },
      {
        "email": "user@nonexistent-domain-1234.org",
        "syntax_valid": true,
        "domain": "nonexistent-domain-1234.org",
        "domain_status": "nonexistent",
        "mx_status": "none",
        "mx_records": [],
        "smtp_status": "skipped",
        "smtp_details": null,
        "classification": "Likely to Bounce",
        "reason": "The domain does not exist in DNS (NXDOMAIN). Mail sent to this address will bounce."
      }
    ]
  }
  ```

---

## Production Deployment Guide

### Deploying to Render

1. **Option A: 1-Click Blueprint Deploy (Fastest):**
   - Click the [Deploy to Render](https://render.com/deploy?repo=https://github.com/Zenith150/emailcheck) button.
   - Render automatically reads [`render.yaml`](render.yaml) and creates the service with all environment variables.

2. **Option B: Manual Dashboard Setup:**
   - Log in to the [Render Dashboard](https://dashboard.render.com/).
   - Click **New +** -> **Web Service**.
   - Connect your GitHub account and select repository `Zenith150/emailcheck`.
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Health Check Path:** `/health`
   *(Render will also detect `render.yaml` or `Procfile` automatically)*

3. **Verify Live Deployment:**
   - Open the live application at [https://emailcheck-7c9y.onrender.com/](https://emailcheck-7c9y.onrender.com/).
   - Verify that `/health` returns status code `200` ([https://emailcheck-7c9y.onrender.com/health](https://emailcheck-7c9y.onrender.com/health)).
   - Test address verification from the live dashboard.

---

## GitHub Repository

The public repository is active at:
- **Repository:** [https://github.com/Zenith150/emailcheck](https://github.com/Zenith150/emailcheck)
- **Clone command:**
  ```bash
  git clone https://github.com/Zenith150/emailcheck.git
  ```

---

## License

MIT License. Free for educational and commercial use.
