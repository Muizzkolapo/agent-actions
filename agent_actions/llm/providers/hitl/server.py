"""Flask-based approval UI server."""

import hashlib
import json
import logging
import os
import re
import secrets
import socket
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from flask import Flask, jsonify, render_template, request
from werkzeug.serving import make_server

from agent_actions.errors import NetworkError

# Keys whose values should be redacted from /api/context responses
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|credential|api_key|auth_token|auth_secret|_secret|_token)$", re.IGNORECASE
)
_REDACTED = "***"

logger = logging.getLogger(__name__)


class HitlServer:
    """Single-use approval server."""

    def __init__(
        self,
        port: int,
        instructions: str,
        context_data: Any,
        timeout: int = 300,
        require_comment_on_reject: bool = True,
        field_order: list[str] | None = None,
        state_file: Path | None = None,
    ):
        self.port = port
        self.instructions = instructions
        self.context_data = context_data
        self.timeout = timeout
        self.require_comment_on_reject = require_comment_on_reject
        self.field_order = field_order or []
        self.record_count = self._determine_record_count(context_data)
        self.record_reviews: list[dict[str, Any] | None] = [None] * self.record_count
        self._data_fingerprint = self._compute_data_fingerprint(context_data)
        self.state_file = state_file
        self.response: dict[str, Any] | None = None
        self.response_event = threading.Event()
        self.shutdown_requested = False
        self._server: Any = None
        self._lock = threading.Lock()
        self._active_port = port  # Updated when an available port is found
        self._session_token = secrets.token_urlsafe(32)
        if self.state_file:
            self._load_state_from_disk()
        self.app = self._create_app()

    def _load_state_from_disk(self) -> None:
        """Load persisted review state from disk if available."""
        if not self.state_file or not self.state_file.exists():
            return
        try:
            raw = self.state_file.read_text(encoding="utf-8")
            state = json.loads(raw)
            if not isinstance(state, dict):
                logger.warning(
                    "HITL state file %s is not a JSON object — starting fresh", self.state_file
                )
                return
            if state.get("total_records") != self.record_count:
                logger.warning(
                    "HITL state file record count mismatch (file=%d, current=%d) — starting fresh",
                    state.get("total_records", -1),
                    self.record_count,
                )
                return
            saved_fingerprint = state.get("data_fingerprint")
            if saved_fingerprint and saved_fingerprint != self._data_fingerprint:
                logger.warning(
                    "HITL state file data fingerprint mismatch — input content changed, starting fresh"
                )
                return
            saved_reviews = state.get("record_reviews", [])
            for idx, review in enumerate(saved_reviews):
                if idx < self.record_count and isinstance(review, dict):
                    self.record_reviews[idx] = review
            restored = sum(1 for r in self.record_reviews if r is not None)
            logger.info(
                "Restored %d/%d HITL reviews from %s", restored, self.record_count, self.state_file
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "Could not load HITL state file %s: %s — starting fresh", self.state_file, exc
            )
        except OSError as exc:
            logger.warning("Could not read HITL state file %s: %s", self.state_file, exc)

    def _persist_state(self) -> None:
        """Atomically persist current review state to disk (best-effort)."""
        if not self.state_file:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                # Skip if a terminal response was already set (submit/approve/
                # reject deleted the state file; don't recreate it).
                if self.response_event.is_set():
                    return
                snapshot = list(self.record_reviews)
            state = {
                "record_reviews": snapshot,
                "total_records": self.record_count,
                "data_fingerprint": self._data_fingerprint,
                "last_updated": _utc_timestamp(),
            }
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.state_file.parent),
                prefix=".hitl_tmp_",
                suffix=".json",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                # Re-check terminal state right before the atomic replace.
                # A concurrent submit/approve/reject may have set the
                # response and deleted the state file while we were writing
                # the temp file; replacing now would resurrect stale state.
                if self.response_event.is_set():
                    Path(tmp_path).unlink(missing_ok=True)
                    return
                Path(tmp_path).replace(self.state_file)
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except OSError as exc:
            logger.warning("Failed to persist HITL state to %s: %s", self.state_file, exc)

    def _delete_state_file(self) -> None:
        """Remove persisted state file after successful completion."""
        if not self.state_file:
            return
        try:
            self.state_file.unlink(missing_ok=True)
            logger.debug("Deleted HITL state file %s", self.state_file)
        except OSError as exc:
            logger.warning("Could not delete HITL state file %s: %s", self.state_file, exc)

    def _create_app(self) -> Flask:
        """Create Flask app with routes."""
        template_folder = Path(__file__).parent / "templates"
        app = Flask(__name__, template_folder=str(template_folder))

        @app.before_request
        def _enforce_post_security():
            """Enforce CSRF token, JSON content-type, and origin on POST requests."""
            if request.method != "POST":
                return None

            # Require JSON content type (blocks form-encoded CSRF)
            content_type = request.content_type or ""
            if "application/json" not in content_type:
                return jsonify(
                    {"success": False, "error": "Content-Type must be application/json"}
                ), 400

            # Validate session token
            token = request.headers.get("X-HITL-Token", "")
            if not secrets.compare_digest(token, self._session_token):
                return jsonify({"success": False, "error": "Invalid or missing session token"}), 403

            # Validate Origin/Referer when present.  Missing headers are allowed
            # because same-origin requests from CLI tools and some browsers omit
            # both; the custom X-HITL-Token header + JSON content-type already
            # provide sufficient CSRF protection on their own.
            origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
            if origin:
                from urllib.parse import urlparse as _urlparse

                parsed_origin = _urlparse(origin)
                origin_key = (parsed_origin.scheme, parsed_origin.hostname, parsed_origin.port)
                allowed_keys = {
                    ("http", "127.0.0.1", self._active_port),
                    ("http", "localhost", self._active_port),
                }
                if origin_key not in allowed_keys:
                    return jsonify({"success": False, "error": "Invalid origin"}), 403

            return None

        @app.after_request
        def _set_security_headers(response):
            nonce = getattr(request, "csp_nonce", "")
            script_src = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                f"script-src {script_src}; "
                "img-src 'self' data:; "
                "connect-src 'self'"
            )
            return response

        app.add_url_rule("/", "index", self._handle_index)
        app.add_url_rule("/api/context", "get_context", self._handle_get_context)
        app.add_url_rule("/api/review-state", "review_state", self._handle_review_state)
        app.add_url_rule(
            "/api/review-record", "review_record", self._handle_review_record, methods=["POST"]
        )
        app.add_url_rule("/api/approve", "approve", self._handle_approve, methods=["POST"])
        app.add_url_rule("/api/reject", "reject", self._handle_reject, methods=["POST"])
        app.add_url_rule("/api/submit", "submit", self._handle_submit, methods=["POST"])
        app.add_url_rule("/api/shutdown", "shutdown", self._handle_shutdown, methods=["POST"])
        return app

    def _handle_index(self):
        nonce = secrets.token_urlsafe(16)
        request.csp_nonce = nonce  # type: ignore[attr-defined]
        return render_template(
            "approval.html",
            instructions=self.instructions,
            require_comment_on_reject=self.require_comment_on_reject,
            hitl_token=self._session_token,
            csp_nonce=nonce,
        )

    def _handle_get_context(self):
        response = {"_envelope": True, "data": _sanitize_context(self.context_data)}
        if self.field_order:
            response["field_order"] = self.field_order
        return jsonify(response)

    def _handle_review_state(self):
        with self._lock:
            reviewed_count = sum(1 for r in self.record_reviews if r is not None)
            snapshot = list(self.record_reviews)
        logger.debug(
            "Serving review state: %d/%d records reviewed", reviewed_count, self.record_count
        )
        return jsonify(
            {
                "record_count": self.record_count,
                "record_reviews": snapshot,
            }
        )

    def _handle_review_record(self):
        if self.response_event.is_set():
            return jsonify({"success": False, "error": "Review already submitted."}), 409
        if self.record_count == 0:
            return (
                jsonify({"success": False, "error": "No records available for review."}),
                400,
            )

        payload = self._get_request_payload()
        raw_index = payload.get("index")
        if not isinstance(raw_index, int):
            return (
                jsonify({"success": False, "error": "Record index must be an integer."}),
                400,
            )

        if raw_index < 0 or raw_index >= self.record_count:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Record index {raw_index} is out of range.",
                    }
                ),
                400,
            )

        normalized_review = self._normalize_single_review(payload)
        if not normalized_review:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Record decision must include hitl_status as approved or rejected.",
                    }
                ),
                400,
            )

        reject_error = self._validate_reject_comment(normalized_review)
        if reject_error:
            return jsonify({"success": False, "error": reject_error}), 400

        with self._lock:
            self.record_reviews[raw_index] = normalized_review
        logger.debug("Saved review for record %d: %s", raw_index, normalized_review["hitl_status"])
        self._persist_state()
        return jsonify({"success": True})

    def _handle_approve(self):
        if self.response_event.is_set():
            return jsonify({"success": False, "error": "Review already submitted."}), 409
        if self.record_count > 1:
            return jsonify(
                {
                    "success": False,
                    "error": "Use /api/submit with per-record reviews for multi-record sets.",
                }
            ), 400
        payload = self._get_request_payload()
        if self.record_count == 1:
            review = self._normalize_single_review(
                {"hitl_status": "approved", "user_comment": payload.get("comment", "")}
            )
            with self._lock:
                self.record_reviews[0] = review
        self._set_response(payload=payload, default_status="approved")
        self._delete_state_file()
        return jsonify({"success": True})

    def _handle_reject(self):
        if self.response_event.is_set():
            return jsonify({"success": False, "error": "Review already submitted."}), 409
        if self.record_count > 1:
            return jsonify(
                {
                    "success": False,
                    "error": "Use /api/submit with per-record reviews for multi-record sets.",
                }
            ), 400
        payload = self._get_request_payload()
        comment = payload.get("comment", "")
        reject_error = self._validate_reject_comment(
            {"hitl_status": "rejected", "user_comment": str(comment)}
        )
        if reject_error:
            return jsonify({"success": False, "error": reject_error}), 400
        if self.record_count == 1:
            review = self._normalize_single_review(
                {"hitl_status": "rejected", "user_comment": comment}
            )
            with self._lock:
                self.record_reviews[0] = review
        self._set_response(payload=payload, default_status="rejected")
        self._delete_state_file()
        return jsonify({"success": True})

    def _handle_submit(self):
        if self.response_event.is_set():
            return jsonify({"success": False, "error": "Review already submitted."}), 409
        payload = self._get_request_payload()
        payload_reviews = payload.get("record_reviews")
        if isinstance(payload_reviews, list):
            record_reviews = self._normalize_record_reviews(payload_reviews)
        else:
            with self._lock:
                record_reviews = list(self.record_reviews)

        completeness_error = self._validate_submit_completeness(record_reviews)
        if completeness_error:
            return jsonify({"success": False, "error": completeness_error}), 400

        for index, review in enumerate(record_reviews):
            if not isinstance(review, dict):
                continue
            reject_error = self._validate_reject_comment(review, record_label=str(index + 1))
            if reject_error:
                return jsonify({"success": False, "error": reject_error}), 400

        with self._lock:
            self.record_reviews = list(record_reviews)
        self._set_response(
            payload=payload,
            default_status="approved",
            record_reviews=record_reviews,
        )
        self._delete_state_file()
        return jsonify({"success": True})

    def _handle_shutdown(self):
        self.shutdown_requested = True
        logger.info("Shutdown requested - server will stop")
        if not self.response_event.is_set():
            self._make_terminal_response("timeout")
        self._shutdown_server()
        return jsonify({"success": True, "message": "Server shutting down"})

    @staticmethod
    def _get_request_payload() -> dict:
        """Extract JSON payload from the current Flask request."""
        return request.get_json(silent=True) or {}

    def _make_terminal_response(
        self,
        status: str,
        comment: str | None = None,
        record_reviews: list[dict[str, Any] | None] | None = None,
    ) -> None:
        """Build response, store it, and unblock the waiting thread.

        This is the single place where self.response is assigned and
        self.response_event is fired, ensuring thread-safe signaling.
        """
        with self._lock:
            if self.response_event.is_set():
                return  # Another thread already set the response
            self.response = {
                "hitl_status": status,
                "user_comment": comment,
                "timestamp": _utc_timestamp(),
            }
            if record_reviews:
                self.response["record_reviews"] = record_reviews
            self.response_event.set()

    def _validate_reject_comment(self, review: dict, record_label: str | None = None) -> str | None:
        """Return an error message if a rejected review is missing a required comment."""
        if not self.require_comment_on_reject:
            return None
        if review.get("hitl_status") != "rejected":
            return None
        if review.get("user_comment", "").strip():
            return None
        if record_label:
            return f"Comment is required when rejecting record {record_label}."
        return "Comment is required when rejecting."

    def _validate_submit_completeness(
        self, record_reviews: list[dict[str, Any] | None]
    ) -> str | None:
        """Return an error message if the review set is incomplete, None if valid."""
        if self.record_count == 0:
            return None
        if len(record_reviews) != self.record_count:
            return (
                f"Review state is incomplete. Expected "
                f"{self.record_count} records but got {len(record_reviews)}."
            )
        missing_index = next(
            (idx for idx, review in enumerate(record_reviews) if not isinstance(review, dict)),
            None,
        )
        if missing_index is not None:
            return (
                f"Please review all records before submitting. Missing record {missing_index + 1}."
            )
        return None

    @staticmethod
    def _determine_record_count(context_data: Any) -> int:
        """Determine how many records are in the review payload."""
        if isinstance(context_data, list):
            return len(context_data)
        if context_data is None:
            return 0
        return 1

    @staticmethod
    def _compute_data_fingerprint(context_data: Any) -> str:
        """Return a short hash of the review dataset for stale-state detection."""
        serialized = json.dumps(context_data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    @staticmethod
    def _normalize_single_review(item: Any) -> dict[str, Any] | None:
        """Normalize one review object into canonical HITL fields."""
        if not isinstance(item, dict):
            return None

        status = str(item.get("hitl_status", "")).strip().lower()
        if status not in {"approved", "rejected"}:
            return None

        user_comment = item.get("user_comment", item.get("comment", ""))
        return {"hitl_status": status, "user_comment": str(user_comment or "")}

    def _normalize_record_reviews(self, value: Any) -> list[dict[str, Any] | None]:
        """Normalize optional record-level review payload from request body.

        Invalid items are preserved as None to maintain list length alignment.
        """
        if not isinstance(value, list):
            return []
        return [self._normalize_single_review(item) for item in value]

    def _resolve_status(
        self,
        payload: dict[str, Any],
        default_status: str,
        record_reviews: list[dict[str, Any] | None],
    ) -> str:
        """Resolve response status from explicit payload status or record reviews."""
        explicit_status = str(payload.get("hitl_status", "")).strip().lower()
        if explicit_status:
            return explicit_status

        if record_reviews:
            all_approved = all(
                isinstance(review, dict) and review.get("hitl_status") == "approved"
                for review in record_reviews
            )
            return "approved" if all_approved else "rejected"

        return default_status

    def _set_response(
        self,
        payload: dict[str, Any],
        default_status: str,
        record_reviews: list[dict[str, Any] | None] | None = None,
    ) -> None:
        """Store server response and release waiting workflow thread."""
        normalized_reviews = (
            record_reviews
            if record_reviews is not None
            else self._normalize_record_reviews(payload.get("record_reviews"))
        )
        comment = str(payload.get("comment", ""))
        status = self._resolve_status(payload, default_status, normalized_reviews)
        self._make_terminal_response(status, comment, normalized_reviews or None)

    def start_and_wait(self) -> dict[str, Any]:
        """
        Start server, block until response or timeout.

        Returns:
            Response dict with status/comment/timestamp
        """
        # Try to find available port
        actual_port = self._find_available_port()
        self._active_port = actual_port

        # Display URL for user
        url = f"http://localhost:{actual_port}"
        click.echo(f"\n  HITL approval UI ready at: {url}\n")
        logger.info("HITL approval UI ready at: %s", url)

        # Start Flask in background thread
        server_thread = threading.Thread(
            target=self._run_server,
            args=(actual_port,),
            daemon=True,
        )
        server_thread.start()

        # Wait for response or timeout
        received = self.response_event.wait(timeout=self.timeout)

        if not received:
            logger.warning("HITL approval timeout after %ds", self.timeout)
            self._make_terminal_response("timeout")

        self._shutdown_server()
        assert self.response is not None
        return self.response

    def _run_server(self, port: int):
        """Run Flask server (called in thread)."""
        try:
            self._server = make_server("127.0.0.1", port, self.app)
            self._server.serve_forever()
        except (Exception, SystemExit) as e:
            # Werkzeug calls sys.exit(1) on bind failures, so catch SystemExit too
            logger.error("Flask server error: %s", e)
            # Signal failure to main thread immediately to avoid timeout wait
            if not self.response_event.is_set():
                self._make_terminal_response("error", f"Server failed to start: {e}")

    def _shutdown_server(self):
        """Stop the werkzeug server from a separate thread to avoid deadlock."""
        server = self._server
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True).start()

    def _find_available_port(self) -> int:
        """Find available port, trying sequential ports on failure.

        Uses SO_REUSEADDR to handle TIME_WAIT sockets and probes by
        actually binding the port.  The socket is closed immediately
        before ``make_server`` re-binds, but SO_REUSEADDR on the
        server socket (werkzeug default) prevents the narrow TOCTOU
        window from causing a failure.
        """
        max_attempts = 5
        last_error = None

        for attempt in range(max_attempts):
            try_port = self.port + attempt
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", try_port))
                if attempt > 0:
                    logger.warning("Port %d in use, using %d instead", self.port, try_port)
                return try_port
            except OSError as e:
                last_error = e
                logger.debug("Port %d unavailable: %s", try_port, e)
                continue
            finally:
                sock.close()

        raise NetworkError(
            f"Could not find available port near {self.port}",
            context={
                "attempted_ports": list(range(self.port, self.port + max_attempts)),
                "last_error": str(last_error),
            },
        )


def _sanitize_context(data: Any) -> Any:
    """Recursively redact values for keys matching sensitive patterns.

    Prevents accidental leakage of credentials or secrets through the
    ``/api/context`` endpoint.
    """
    if isinstance(data, dict):
        return {
            k: (_REDACTED if _SENSITIVE_KEY_PATTERN.search(k) else _sanitize_context(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_sanitize_context(item) for item in data]
    return data


def _utc_timestamp() -> str:
    """Return ISO-8601 UTC timestamp with Z suffix."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
