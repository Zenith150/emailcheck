"""
EmailCheck - Flask Web Application
Provides responsive UI, REST API (/api/verify), and health monitoring (/health).
"""

import os
import time
import logging
from collections import defaultdict
from flask import Flask, render_template, request, jsonify

from verifier import verify_email_list, test_smtp_outbound_capability

# Configure logging (Privacy-first: do NOT log full email addresses)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("EmailCheck")

app = Flask(__name__)

# Configuration
MAX_EMAILS_PER_REQUEST = int(os.environ.get("MAX_EMAILS_PER_REQUEST", 100))
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", 30))  # Max requests per window
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW", 60))

# Simple in-memory rate limiter per IP address
rate_limit_tracker = defaultdict(list)

# Check outbound SMTP capability at startup (cached)
_smtp_capability_cache = None


def check_cached_smtp_capability() -> bool:
    global _smtp_capability_cache
    if _smtp_capability_cache is None:
        try:
            _smtp_capability_cache = test_smtp_outbound_capability(timeout=2.0)
            logger.info("Outbound SMTP capability detected: %s", _smtp_capability_cache)
        except Exception:
            _smtp_capability_cache = False
    return _smtp_capability_cache


def is_rate_limited(client_ip: str) -> bool:
    """Basic sliding-window rate limiter per client IP."""
    now = time.time()
    history = rate_limit_tracker[client_ip]
    # Filter out timestamps older than the window
    valid_history = [t for t in history if now - t < RATE_LIMIT_WINDOW_SECONDS]
    rate_limit_tracker[client_ip] = valid_history

    if len(valid_history) >= RATE_LIMIT_REQUESTS:
        return True

    rate_limit_tracker[client_ip].append(now)
    return False


@app.route("/")
def index():
    """Serves the main application single-page dashboard."""
    smtp_available = check_cached_smtp_capability()
    return render_template(
        "index.html",
        smtp_available=smtp_available,
        max_emails=MAX_EMAILS_PER_REQUEST
    )


@app.route("/health", methods=["GET"])
def health():
    """Deployment health check endpoint."""
    smtp_available = check_cached_smtp_capability()
    return jsonify({
        "status": "healthy",
        "service": "EmailCheck",
        "version": "1.0.0",
        "smtp_outbound_available": smtp_available,
        "max_emails_per_request": MAX_EMAILS_PER_REQUEST
    }), 200


@app.route("/api/verify", methods=["POST"])
def api_verify():
    """
    Main verification API endpoint.
    Accepts:
    {
        "emails": ["user1@example.com", "user2@domain.com"],
        "smtp_check": false
    }
    Returns:
    {
        "success": true,
        "total": 2,
        "summary": {...},
        "results": [...]
    }
    """
    # Rate limiting check
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if is_rate_limited(client_ip):
        logger.warning("Rate limit exceeded for client %s", client_ip)
        return jsonify({
            "success": False,
            "error": "Rate limit exceeded. Please wait a minute before submitting again."
        }), 429

    # Content-Type and payload validation
    if not request.is_json:
        return jsonify({
            "success": False,
            "error": "Request Content-Type must be application/json."
        }), 400

    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "Invalid JSON body provided."
        }), 400

    raw_emails = data.get("emails")
    if raw_emails is None:
        return jsonify({
            "success": False,
            "error": "Missing required 'emails' field in request body."
        }), 400

    if not isinstance(raw_emails, list):
        return jsonify({
            "success": False,
            "error": "'emails' must be a list of email address strings."
        }), 400

    if len(raw_emails) == 0:
        return jsonify({
            "success": False,
            "error": "Email list cannot be empty. Please provide at least one email address."
        }), 400

    if len(raw_emails) > MAX_EMAILS_PER_REQUEST:
        return jsonify({
            "success": False,
            "error": f"Request exceeds maximum limit of {MAX_EMAILS_PER_REQUEST} addresses per batch."
        }), 400

    perform_smtp = bool(data.get("smtp_check", False))

    # Anonymized logging (Log count only; avoid logging actual emails for privacy)
    logger.info("Processing verification batch: count=%d, smtp_requested=%s", len(raw_emails), perform_smtp)

    try:
        verification_result = verify_email_list(
            emails=raw_emails,
            perform_smtp=perform_smtp,
            max_emails=MAX_EMAILS_PER_REQUEST
        )
        return jsonify(verification_result), 200

    except ValueError as val_err:
        return jsonify({
            "success": False,
            "error": str(val_err)
        }), 400
    except Exception as exc:
        logger.error("Unhandled verification exception: %s", str(exc), exc_info=True)
        return jsonify({
            "success": False,
            "error": "An internal error occurred during verification. Please try again."
        }), 500


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Endpoint not found."}), 404
    return render_template("index.html", smtp_available=check_cached_smtp_capability(), max_emails=MAX_EMAILS_PER_REQUEST), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"success": False, "error": "Method not allowed for this route."}), 405


@app.errorhandler(500)
def server_error(e):
    return jsonify({"success": False, "error": "Internal server error."}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info("Starting EmailCheck server on %s:%d (debug=%s)", host, port, debug)
    app.run(host=host, port=port, debug=debug)
