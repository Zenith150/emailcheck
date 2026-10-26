# EmailCheck — Email Verification & Deliverability Diagnostics (v2.0)

EmailCheck is a full-stack, responsive web application designed for non-invasive email verification and deliverability diagnostics. It resolves cloud hosting restrictions—such as Render's outbound TCP port 25 block—by combining a local 7-stage diagnostic pipeline with reputable email verification APIs operating over secure HTTPS (port 443).

Addresses are classified into four transparent, conservative statuses:
1. **Valid** (Green) — Syntax valid, active mail routing, not disposable, and recipient inbox confirmed deliverable.
2. **Invalid** (Red) — Malformed syntax, nonexistent domain (NXDOMAIN), RFC 7505 Null MX, or confirmed undeliverable inbox.
3. **Risky** (Amber) — Disposable/temporary domain, catch-all mail server, role account, or unverified recipient inbox (when running without a provider API key).
4. **Unknown** (Slate) — DNS query timeout, server error, provider API rate limit (429), or quota exhaustion.

---

## Table of Contents

- [Live Demo & Repository Links](#live-demo--repository-links)
- [Render Outbound SMTP (Port 25) Restriction & Solution](#render-outbound-smtp-port-25-restriction--solution)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [The 7-Stage Verification Pipeline](#the-7-stage-verification-pipeline)
- [Classification Criteria](#classification-criteria)
- [Supported Verification Providers & Setup](#supported-verification-providers--setup)
- [Environment Variables](#environment-variables)
- [Configuring Render Environment Variables](#configuring-render-environment-variables)
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
- **Project Submission Document:** [`submission/EmailCheck_Project_Submission.pdf`](submission/EmailCheck_Project_Submission.pdf)

---

## Render Outbound SMTP (Port 25) Restriction & Solution

### The Problem
Most modern cloud platforms—including **Render**, AWS EC2 (by default), DigitalOcean, and Heroku—strictly block or filter outbound TCP traffic on **port 25** to protect their network reputations and prevent spam abuse. In previous architectures, attempting a raw SMTP handshake (`HELO` $\rightarrow$ `MAIL FROM` $\rightarrow$ `RCPT TO`) from a Render container resulted in immediate socket timeouts, connection drops, or false failure reporting.

### The Production Solution
EmailCheck v2.0 solves this restriction cleanly and robustly without attempting to bypass network controls:

1. **HTTPS Provider-Based Verification (Port 443):**
   Direct SMTP probing is replaced by reputable email verification REST APIs over standard HTTPS (port 443). The backend communicates with provider endpoints using Python standard library `urllib.request` with strict timeouts and resilient error handling.

2. **Modular Provider Architecture (`providers.py`):**
   The verification system defines a unified `BaseVerificationProvider` contract and includes out-of-the-box adapters for:
   - **Abstract API** (Default): Fast, recipient-level verification with deliverability scoring and catch-all detection.
   - **Hunter.io**: Industry-standard email verification with MX and SMTP status checks.
   - **ZeroBounce**: High-precision inbox validation and sub-status tagging.
   - **Local Fallback**: Zero-dependency local verification when no third-party API key is configured.

3. **Transparent Fallback & Honest Reporting:**
   - If no provider API key is configured, EmailCheck executes local syntax validation, domain normalization, disposable domain filtering, and DNS MX checks, while honestly classifying recipient inbox existence as unverified (`Risky`) rather than falsely claiming inbox delivery.
   - If a provider exceeds rate limits or quota (HTTP 429), the system marks the recipient check as `Unknown` rather than crashing or returning false positives.
   - Direct SMTP probing is disabled by default (`ENABLE_DIRECT_SMTP=false`) and automatically bypassed on Render.

---

## Key Features

- **Multi-Stage Verification Pipeline:**
  - RFC 5322 and RFC 5321 syntax validation.
  - Case-preserving email normalization (lowercase domain, preserve local part).
  - Built-in disposable email domain blacklist (200+ domains including Mailinator, GuerrillaMail, TempMail).
  - DNS resolution checking active MX records, NXDOMAIN existence, RFC 7505 Null MX (`0 .`), and RFC 5321 implicit MX fallback (A/AAAA).
  - Provider-based recipient inbox deliverability over HTTPS (port 443).
- **Conservative Classification:** Never assumes mailbox existence when servers refuse disclosure, use catch-all routing, or when recipient verification is unconfigured.
- **Batch Processing with Memoization:** Efficient in-memory caching prevents redundant DNS lookups and HTTP requests for duplicate domains and addresses within the same batch (up to 100 emails).
- **Modern Responsive Dashboard:**
  - Real-time address counter (up to 100 per batch).
  - Five summary metric cards: **Total**, **Valid**, **Invalid**, **Risky**, and **Unknown**.
  - Interactive filter tabs (All, Valid, Invalid, Risky, Unknown) and real-time search box.
  - Informational provider pill in the dashboard showing the active verification engine.
  - One-click RFC 4180 compliant **CSV Export** with all diagnostic columns.
- **Production-Ready Backend:** Flask REST API with sliding-window rate limiting, input sanitization, health monitoring (`/health`), and WSGI production server (`gunicorn`).

---

## Technology Stack

- **Frontend:** HTML5, CSS3 (Custom Design System with responsive grid, accessible contrasts, and dark/light accents), Vanilla JavaScript (ES6+).
- **Backend:** Python 3.11, Flask 3.1.
- **Verification Engine:**
  - Syntax: `email-validator` with RFC 5322 regex fallback.
  - DNS / Routing: `dnspython` with public nameserver fallback (Google `8.8.8.8` / Cloudflare `1.1.1.1`).
  - Recipient Verification: HTTPS REST API (Abstract API / Hunter / ZeroBounce) via Python `urllib.request`.
  - Disposable Detection: Curated dataset of 200+ known disposable and temporary email domains.
- **Production WSGI:** `gunicorn`.
- **Testing:** Python `unittest` suite (37 automated unit, integration, and mocking tests).
- **Documentation & PDF Generation:** ReportLab (`submission/EmailCheck_Project_Submission.pdf`).

---

## The 7-Stage Verification Pipeline

```
[ User Input (up to 100 emails) ]
             │
             ▼
[ Rate Limiter & Sanitizer ]
             │
             ▼
[ 1. Syntax Validation ] ─────────(Malformed)─────────► [ Invalid ]
             │
          (Valid)
             ▼
[ 2. Normalization ] (trim whitespace, lowercase domain, preserve local part)
             │
             ▼
[ 3. Disposable Domain Check ] ───(Disposable Domain)─► [ Risky ]
             │
        (Not Disposable)
             ▼
[ 4. DNS Domain Check ] ──────────(NXDOMAIN)──────────► [ Invalid ]
             │                    (DNS Timeout/Error)─► [ Unknown ]
         (Exists)
             ▼
[ 5. MX Record Validation ]
             ├── RFC 7505 Null MX ("0 .") ────────────► [ Invalid ]
             ├── No MX & No A/AAAA Record ────────────► [ Invalid ]
             └── MX Found (or Implicit MX A/AAAA)
                        │
                        ▼
[ 6. HTTPS Provider Check (Port 443) ]
             ├── Undeliverable Mailbox ───────────────► [ Invalid ]
             ├── Catch-All Server Detected ───────────► [ Risky ]
             ├── Quota Exceeded / Rate Limit (429) ───► [ Unknown ]
             ├── Network / API Timeout ───────────────► [ Unknown ]
             ├── No Provider Key Configured ──────────► [ Risky ] (Domain verified, inbox unverified)
             └── Deliverable Mailbox ─────────────────► [ Valid ]
                        │
                        ▼
[ 7. Result Classification & Transparent Explanation ]
```

---

## Classification Criteria

| Classification | Badge | Meaning | Underlying Conditions |
| :--- | :--- | :--- | :--- |
| **Valid** | <font color="#047857">**Valid**</font> | High confidence deliverability. | • RFC syntax is valid<br>• Domain exists with active MX routing<br>• Domain is not a known disposable provider<br>• Recipient inbox confirmed deliverable via HTTPS provider API |
| **Invalid** | <font color="#b91c1c">**Invalid**</font> | Mail will bounce or be rejected. | • Malformed syntax (missing `@`, consecutive dots, invalid characters)<br>• Nonexistent domain (`NXDOMAIN`)<br>• RFC 7505 Null MX record published (`0 .`)<br>• Domain has no MX and no A/AAAA records<br>• Provider API confirmed recipient inbox does not exist |
| **Risky** | <font color="#b45309">**Risky**</font> | Mail may bounce, be temporary, or cannot be confirmed at the mailbox level. | • Known disposable/temporary email domain (e.g. Mailinator, GuerrillaMail)<br>• Catch-all mail server (accepts all addresses indiscriminately)<br>• Role-based account (`admin@`, `support@`)<br>• Local verification only: Domain MX is active, but recipient inbox is unverified (no API key configured) |
| **Unknown** | <font color="#475569">**Unknown**</font> | Deliverability cannot be reliably determined. | • DNS query timeout or DNS server failure (`SERVFAIL`)<br>• Provider API rate limit (HTTP 429) or monthly quota reached<br>• Provider network timeout or transient connection error |

---

## Supported Verification Providers & Setup

EmailCheck supports multiple providers through standard environment variables:

### 1. Abstract API (Recommended Default)
- **Features:** Real-time deliverability checks, MX checks, SMTP verification, disposable detection, catch-all detection.
- **Free Tier:** 100 free requests per month.
- **Sign-up:** [https://app.abstractapi.com/users/signup](https://app.abstractapi.com/users/signup) $\rightarrow$ Select "Email Verification".
- **Render Configuration:**
  - `EMAIL_VERIFICATION_PROVIDER=abstract`
  - `EMAIL_VERIFICATION_API_KEY=<your_abstract_api_key>`

### 2. Hunter.io
- **Features:** Mailbox verification, SMTP checks, MX status, webmail detection.
- **Free Tier:** 25 free requests per month.
- **Sign-up:** [https://hunter.io/users/sign_up](https://hunter.io/users/sign_up)
- **Render Configuration:**
  - `EMAIL_VERIFICATION_PROVIDER=hunter`
  - `EMAIL_VERIFICATION_API_KEY=<your_hunter_api_key>`

### 3. ZeroBounce
- **Features:** Deep mailbox deliverability, spam trap detection, sub-status codes.
- **Free Tier:** 100 free requests per month.
- **Sign-up:** [https://www.zerobounce.net/members/signup/](https://www.zerobounce.net/members/signup/)
- **Render Configuration:**
  - `EMAIL_VERIFICATION_PROVIDER=zerobounce`
  - `EMAIL_VERIFICATION_API_KEY=<your_zerobounce_api_key>`

### 4. Local Fallback (No Key Required)
- If `EMAIL_VERIFICATION_API_KEY` is omitted or set to `local`, EmailCheck runs the complete local pipeline: syntax validation, normalization, 200+ disposable domain check, and DNS MX / Null MX checks.
- Recipient deliverability is safely classified as `Risky` (unverified inbox), clearly distinguishing domain routing from recipient inbox confirmation.

---

## Environment Variables

All settings are configured using standard environment variables (documented in [`.env.example`](.env.example)):

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `EMAIL_VERIFICATION_PROVIDER` | string | `abstract` | Provider adapter to use: `abstract`, `hunter`, `zerobounce`, or `local`. |
| `EMAIL_VERIFICATION_API_KEY` | string | `""` | API key for the chosen provider. Stored server-side only; never sent to frontend. |
| `EMAIL_VERIFICATION_TIMEOUT` | float | `6.0` | HTTP request timeout in seconds for provider API calls. |
| `ENABLE_DIRECT_SMTP` | boolean | `false` | Set to `true` only on servers with open outbound port 25. Always `false` on Render. |
| `MAX_EMAILS_PER_REQUEST` | integer | `100` | Maximum email addresses allowed per verification batch. |
| `RATE_LIMIT_PER_MINUTE` | integer | `30` | Maximum batch requests per client IP per minute. |
| `PORT` | integer | `5000` | Server listening port (automatically set by Render). |

---

## Configuring Render Environment Variables

To add or update provider credentials on Render:

1. Log in to the [Render Dashboard](https://dashboard.render.com/).
2. Click on the **EmailCheck** web service (`emailcheck-7c9y`).
3. In the left navigation, click **Environment**.
4. Click **Add Environment Variable**:
   - Key: `EMAIL_VERIFICATION_PROVIDER` $\rightarrow$ Value: `abstract`
   - Key: `EMAIL_VERIFICATION_API_KEY` $\rightarrow$ Value: `<your_api_key_here>`
5. Click **Save Changes**. Render will automatically redeploy the service with the new credentials.
6. Verify by loading [https://emailcheck-7c9y.onrender.com/health](https://emailcheck-7c9y.onrender.com/health), which will report `"provider_configured": true`.

---

## Privacy & Anti-Abuse Safeguards

- **Zero Email Transmission:** EmailCheck **never sends emails**. It never issues the SMTP `DATA` command and never transmits any message headers or body content.
- **Server-Side API Key Isolation:** Third-party API keys are strictly kept in backend environment variables and never exposed to the frontend browser or client responses.
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
   git clone https://github.com/Zenith150/emailcheck.git
   cd emailcheck
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

4. **Configure environment variables (optional):**
   ```bash
   # Copy sample environment configuration
   cp .env.example .env
   # Edit .env with your preferred provider and API key
   ```

5. **Run the local development server:**
   ```bash
   python app.py
   ```

6. **Open your browser:**
   Navigate to [http://localhost:5000](http://localhost:5000)

---

## Running Automated Tests

The test suite contains **37 automated tests** covering syntax validation, normalization rules, disposable domain detection, mocked DNS MX resolution, RFC 7505 Null MX records, provider API integration adapters (Abstract, Hunter, ZeroBounce, Local), quota handling, batch deduplication, and REST API endpoints.

To run the automated tests:
```bash
python -m unittest discover tests -v
```

All 37 tests run isolated from external network dependencies via unittest mocks and complete in under 2 seconds:
```
Ran 37 tests in 1.641s: OK
```

---

## API Documentation

### 1. Health Check
- **Endpoint:** `GET /health`
- **Method:** `GET`
- **Response:**
  ```json
  {
    "status": "healthy",
    "service": "EmailCheck",
    "version": "2.0.0",
    "provider": "abstract",
    "provider_configured": false,
    "smtp_outbound_available": false,
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
      "user@example.com",
      "temp@mailinator.com",
      "malformed..syntax@@domain",
      "user@nonexistent-domain-1234.org"
    ]
  }
  ```
- **Response:**
  ```json
  {
    "success": true,
    "total": 4,
    "summary": {
      "total": 4,
      "valid": 1,
      "invalid": 2,
      "risky": 1,
      "unknown": 0
    },
    "results": [
      {
        "email": "user@example.com",
        "normalized_email": "user@example.com",
        "syntax_valid": true,
        "domain": "example.com",
        "domain_status": "exists",
        "mx_status": "mx_found",
        "mx_records": [
          "mail.example.com (priority 10)"
        ],
        "disposable": false,
        "recipient_check": {
          "status": "deliverable",
          "provider": "abstract",
          "details": "Inbox verified deliverable."
        },
        "classification": "Valid",
        "reason": "Valid syntax, active MX routing verified, and recipient inbox confirmed deliverable via HTTPS provider."
      },
      {
        "email": "temp@mailinator.com",
        "normalized_email": "temp@mailinator.com",
        "syntax_valid": true,
        "domain": "mailinator.com",
        "domain_status": "exists",
        "mx_status": "mx_found",
        "mx_records": [
          "mail2.mailinator.com (priority 10)"
        ],
        "disposable": true,
        "recipient_check": {
          "status": "risky",
          "provider": "abstract",
          "details": "Temporary/disposable domain detected."
        },
        "classification": "Risky",
        "reason": "Address belongs to a known temporary or disposable email domain (mailinator.com). Messages may be ephemeral or public."
      },
      {
        "email": "malformed..syntax@@domain",
        "normalized_email": "malformed..syntax@@domain",
        "syntax_valid": false,
        "domain": "",
        "domain_status": "untested",
        "mx_status": "untested",
        "mx_records": [],
        "disposable": false,
        "recipient_check": {
          "status": "skipped",
          "provider": "none",
          "details": "Skipped due to syntax failure"
        },
        "classification": "Invalid",
        "reason": "Invalid email syntax: Email contains multiple '@' symbols.."
      },
      {
        "email": "user@nonexistent-domain-1234.org",
        "normalized_email": "user@nonexistent-domain-1234.org",
        "syntax_valid": true,
        "domain": "nonexistent-domain-1234.org",
        "domain_status": "nonexistent",
        "mx_status": "none",
        "mx_records": [],
        "disposable": false,
        "recipient_check": {
          "status": "skipped",
          "provider": "none",
          "details": "Domain does not exist"
        },
        "classification": "Invalid",
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
   - Render automatically reads [`render.yaml`](render.yaml) and provisions the service.

2. **Option B: Manual Dashboard Setup:**
   - Log in to the [Render Dashboard](https://dashboard.render.com/).
   - Click **New +** $\rightarrow$ **Web Service**.
   - Select repository `Zenith150/emailcheck`.
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Health Check Path:** `/health`
   *(Render will also detect `render.yaml` or `Procfile` automatically)*

3. **Verify Live Deployment:**
   - Open [https://emailcheck-7c9y.onrender.com/](https://emailcheck-7c9y.onrender.com/).
   - Verify that `/health` returns status code `200` ([https://emailcheck-7c9y.onrender.com/health](https://emailcheck-7c9y.onrender.com/health)).
   - Test address verification from the live dashboard.

---

## License

MIT License. Free for educational and commercial use.
