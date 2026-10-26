"""
EmailCheck - Flask Web Application (v2.2)
Provides responsive dashboard UI, REST API (/api/verify, /api/domain), and health monitoring (/health)
with HTTPS verification provider support, disposable email detection, RFC 7505 Null MX handling,
and modular genuine SMTP probing with Render port 25 fallback.
"""

import os
import time
import logging
from collections import defaultdict
from flask import Flask, render_template, request, jsonify

from verifier import (
    verify_email_list,
    test_smtp_outbound_capability,
    check_domain_diagnostics,
    PIPELINE_STAGES
)
from providers import get_verification_provider
from smtp_probe import get_smtp_probe_config, is_smtp_probe_enabled

# Configure logging (Privacy-first: do NOT log full email addresses or API keys)
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

# Simple in-memory sliding window rate limiter per IP address
rate_limit_tracker = defaultdict(list)

# Check outbound SMTP capability at startup (cached, for informational purposes only)
_smtp_capability_cache = None


def check_cached_smtp_capability() -> bool:
    global _smtp_capability_cache
    if _smtp_capability_cache is None:
        try:
            # Short non-blocking socket test
            _smtp_capability_cache = test_smtp_outbound_capability(timeout=1.5)
        except Exception:
            _smtp_capability_cache = False
    return _smtp_capability_cache


def is_rate_limited(client_ip: str) -> bool:
    """Basic sliding-window rate limiter per client IP."""
    now = time.time()
    history = rate_limit_tracker[client_ip]
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
    provider = get_verification_provider()
    has_api_key = bool(os.environ.get("EMAIL_VERIFICATION_API_KEY", "").strip())
    smtp_probe_cfg = get_smtp_probe_config()
    
    return render_template(
        "index.html",
        smtp_available=smtp_available,
        smtp_probe_enabled=smtp_probe_cfg["enabled"],
        smtp_probe_config=smtp_probe_cfg,
        provider_name=provider.name,
        provider_configured=has_api_key,
        max_emails=MAX_EMAILS_PER_REQUEST,
        pipeline_stages=PIPELINE_STAGES,
        pipeline_stage_count=len(PIPELINE_STAGES)
    )


@app.route("/health", methods=["GET"])
def health():
    """Deployment health check endpoint reporting system status and verification pipeline."""
    smtp_available = check_cached_smtp_capability()
    provider = get_verification_provider()
    has_api_key = bool(os.environ.get("EMAIL_VERIFICATION_API_KEY", "").strip())
    smtp_probe_cfg = get_smtp_probe_config()
    
    return jsonify({
        "status": "healthy",
        "service": "EmailCheck",
        "version": "2.2.0",
        "provider": provider.name,
        "provider_configured": has_api_key,
        "smtp_outbound_available": smtp_available,
        "smtp_probe_config": smtp_probe_cfg,
        "max_emails_per_request": MAX_EMAILS_PER_REQUEST,
        "pipeline_stages": PIPELINE_STAGES,
        "pipeline_stage_count": len(PIPELINE_STAGES)
    }), 200


@app.route("/api/pipeline", methods=["GET"])
def api_pipeline():
    """Returns the authoritative 7-stage verification pipeline definition."""
    return jsonify({
        "success": True,
        "stages": PIPELINE_STAGES,
        "count": len(PIPELINE_STAGES)
    }), 200


@app.route("/api/domain", methods=["GET", "POST"])
def api_domain():
    """
    Dedicated Domain Diagnostics API endpoint.
    Accepts GET /api/domain?domain=example.com or POST {"domain": "example.com"}
    """
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if is_rate_limited(client_ip):
        logger.warning("Rate limit exceeded for client %s on /api/domain", client_ip)
        return jsonify({
            "success": False,
            "error": "Rate limit exceeded. Please wait a minute before submitting again."
        }), 429

    domain = None
    if request.method == "POST":
        if request.is_json:
            body = request.get_json(silent=True) or {}
            domain = body.get("domain")
        else:
            domain = request.form.get("domain")
    else:
        domain = request.args.get("domain")

    if not domain or not isinstance(domain, str) or not domain.strip():
        return jsonify({
            "success": False,
            "error": "Domain parameter is required."
        }), 400

    domain_str = domain.strip()
    if len(domain_str) > 253:
        return jsonify({
            "success": False,
            "error": "Domain name exceeds maximum length of 253 characters."
        }), 400

    try:
        diagnostics = check_domain_diagnostics(domain_str)
        status_code = 200 if diagnostics.get("success") else 400
        return jsonify(diagnostics), status_code
    except Exception as exc:
        logger.error("Domain diagnostics error for domain %s: %s", domain_str, str(exc), exc_info=True)
        return jsonify({
            "success": False,
            "error": "An internal error occurred during domain diagnostics. Please try again."
        }), 500


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
        "provider": "abstract",
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

    perform_smtp = bool(data.get("check_smtp", data.get("smtp_check", False)))

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
    provider = get_verification_provider()
    has_api_key = bool(os.environ.get("EMAIL_VERIFICATION_API_KEY", "").strip())
    smtp_probe_cfg = get_smtp_probe_config()
    return render_template(
        "index.html",
        smtp_available=check_cached_smtp_capability(),
        smtp_probe_enabled=smtp_probe_cfg["enabled"],
        smtp_probe_config=smtp_probe_cfg,
        provider_name=provider.name,
        provider_configured=has_api_key,
        max_emails=MAX_EMAILS_PER_REQUEST,
        pipeline_stages=PIPELINE_STAGES,
        pipeline_stage_count=len(PIPELINE_STAGES)
    ), 404


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
