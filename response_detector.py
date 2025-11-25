"""
Plinian Strategies — Email Response & Outreach Webhook
======================================================

Part 1: Email Response Detector
-------------------------------
Detects email replies and updates Outreach Log entries in Notion.

Part 2: Outreach Trigger (Prospect Firms → Outreach Draft)
----------------------------------------------------------
Accepts webhook calls from Notion (e.g., button in Prospect Firms database)
to kick off an outreach workflow:

    Notion Button → /webhook/outreach → Notion Read
        → Outreach Draft (stub / LLM)
        → Gmail Draft (stub)
        → Notion Update

Setup:
    pip install notion-client python-dotenv flask

Environment Variables:
    NOTION_API_KEY      - Your Notion integration token
    OUTREACH_LOG_DB_ID  - Outreach Log database ID (for email replies)
"""

import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from notion_client import Client
from dotenv import load_dotenv


# =============================================================================
# CONFIG & INITIALIZATION
# =============================================================================

# Load environment variables from .env (if present)
load_dotenv()

NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
OUTREACH_LOG_DB_ID = os.environ.get(
    "OUTREACH_LOG_DB_ID",
    "2b5c16a0-949c-8147-8a7f-ca839e1ae002"
)

notion = Client(auth=NOTION_API_KEY)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# OUTREACH LOG HELPERS (EMAIL REPLY FLOW)
# =============================================================================

def search_outreach_by_thread_id(thread_id: str) -> Optional[Dict[str, Any]]:
    """Search Outreach Log for an entry matching the Gmail Thread ID."""
    try:
        logger.info(f"Searching Outreach Log for thread ID: {thread_id}")
        response = notion.databases.query(
            database_id=OUTREACH_LOG_DB_ID,
            filter={
                "property": "Gmail Thread ID",
                "rich_text": {"equals": thread_id},
            },
        )
        results = response.get("results", [])
        if results:
            logger.info(f"Found {len(results)} matching Outreach Log entries")
            return results[0]
        else:
            logger.warning(f"No outreach entry found for thread ID: {thread_id}")
            return None
    except Exception as e:
        logger.error(f"Error searching Outreach Log: {e}")
        return None


def classify_response_tone(email_body: str) -> str:
    """
    Simple keyword-based classification of response tone.
    Returns: "Responded — Positive" / "Neutral" / "Negative"
    """
    body_lower = email_body.lower()

    positive_keywords = [
        "interested", "yes", "sounds good", "let's discuss", "happy to",
        "would love to", "absolutely", "definitely", "great", "perfect",
        "schedule", "meeting", "call", "connect",
    ]
    negative_keywords = [
        "not interested", "no thank you", "pass", "not a fit", "decline",
        "unsubscribe", "remove", "stop", "not at this time",
    ]

    positive_count = sum(1 for k in positive_keywords if k in body_lower)
    negative_count = sum(1 for k in negative_keywords if k in body_lower)

    if negative_count > 0:
        return "Responded — Negative"
    elif positive_count > 0:
        return "Responded — Positive"
    else:
        return "Responded — Neutral"


def update_outreach_entry(
    page_id: str,
    response_status: str,
    response_date: str,
    email_body: Optional[str] = None,
) -> bool:
    """Update an Outreach Log entry with response details."""
    try:
        logger.info(f"Updating Outreach Log page {page_id} with status: {response_status}")

        properties: Dict[str, Any] = {
            "Response Status": {"select": {"name": response_status}},
            "Response Date": {"date": {"start": response_date}},
            "Outcome": {
                "select": {
                    "name": "In Discussion"
                    if response_status != "Responded — Negative"
                    else "Declined"
                }
            },
            "Follow-up Required": {"checkbox": False},
        }

        if email_body:
            page = notion.pages.retrieve(page_id=page_id)
            current_notes = (
                page.get("properties", {})
                .get("Notes", {})
                .get("rich_text", [])
            )
            current_text = "".join(
                block.get("plain_text", "") for block in current_notes
            )
            response_snippet = (
                f"\n\n[Response received {response_date}]\n{email_body[:200]}..."
            )
            properties["Notes"] = {
                "rich_text": [
                    {"text": {"content": current_text + response_snippet}}
                ]
            }

        notion.pages.update(page_id=page_id, properties=properties)
        logger.info(f"Successfully updated Outreach Log page {page_id}")
        return True
    except Exception as e:
        logger.error(f"Error updating Outreach Log entry: {e}")
        return False


def process_email_reply(
    thread_id: str,
    sender_email: str,
    email_body: str,
    received_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Main processing function for email replies."""
    if not received_date:
        received_date = datetime.utcnow().isoformat()

    outreach_entry = search_outreach_by_thread_id(thread_id)
    if not outreach_entry:
        return {
            "status": "not_found",
            "message": f"No outreach entry found for thread ID: {thread_id}",
        }

    page_id = outreach_entry["id"]
    response_status = classify_response_tone(email_body)

    success = update_outreach_entry(
        page_id=page_id,
        response_status=response_status,
        response_date=received_date[:10],
        email_body=email_body,
    )

    if success:
        return {
            "status": "updated",
            "message": f"Updated outreach entry for {sender_email}",
            "page_id": page_id,
            "response_status": response_status,
        }
    else:
        return {"status": "error", "message": "Failed to update Notion"}


# =============================================================================
# PROSPECT FIRM OUTREACH HELPERS
# =============================================================================

def _get_plain_text_from_rich(items: List[Dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in (items or []))


def get_firm_details_from_notion(firm_id: str) -> Dict[str, Any]:
    """Retrieve and normalize a Prospect Firm page from Notion."""
    page = notion.pages.retrieve(page_id=firm_id)
    props: Dict[str, Any] = page.get("properties", {})

    def get_title(name: str) -> Optional[str]:
        prop = props.get(name)
        if not prop:
            return None
        return _get_plain_text_from_rich(prop.get("title") or [])

    def get_url(name: str) -> Optional[str]:
        prop = props.get(name)
        return prop.get("url") if prop else None

    def get_rich_text(name: str) -> Optional[str]:
        prop = props.get(name)
        if not prop:
            return None
        return _get_plain_text_from_rich(prop.get("rich_text") or [])

    def get_select_or_multi(name: str) -> List[str]:
        prop = props.get(name)
        if not prop:
            return []
        if "select" in prop and prop["select"]:
            return [prop["select"]["name"]]
        if "multi_select" in prop and prop["multi_select"]:
            return [opt["name"] for opt in prop["multi_select"]]
        return []

    firm_name = get_title("Firm Name") or get_title("Name")
    website = get_url("Website")
    plinian_fit = get_select_or_multi("Plinian Fit")
    notes = get_rich_text("Notes")

    firm_details = {
        "firm_id": firm_id,
        "firm_name": firm_name,
        "website": website,
        "plinian_fit": plinian_fit,
        "notes": notes,
        "raw_page": page,
    }
    logger.info(f"Loaded firm details from Notion for {firm_id}: {firm_details}")
    return firm_details


def generate_outreach_for_firm(firm: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a contact + outreach draft for a firm.
    Currently a stub: easy to replace with a Claude/GPT call later.
    """
    firm_name = firm.get("firm_name") or "your organization"
    website = firm.get("website")
    fit_tags = firm.get("plinian_fit") or []
    fit_str = ", ".join(fit_tags) if fit_tags else "long-term partnership capital"

    contact = {
        "full_name": "Investment Team",
        "title": "Investment Office",
        "email": None,
        "seniority": "Unknown",
        "fit_reason": f"Prospect firm identified as a strong fit for {fit_str}.",
        "client_match": None,
    }

    subject = f"Intro: Plinian Strategies and potential fit for {firm_name}"

    intro_line = (
        "I hope this note finds you well. I lead Plinian Strategies, "
        "a boutique advisory and capital-sourcing platform."
    )
    body_lines = [
        "Hi there,",
        "",
        intro_line,
        "",
        f"We've spent time understanding organizations like {firm_name} "
        f"and how you think about {fit_str.lower()}. "
        "Given that context, I think there could be a very natural fit with "
        "one or more of the managers I work with.",
    ]
    if website:
        body_lines.append(
            f"\nI’ve also reviewed your public materials ({website}) "
            "which reinforced that impression."
        )

    body_lines.extend(
        [
            "",
            "Rather than send you a deck blindly, I’d be grateful for 15 minutes "
            "to share a brief overview of how we’re helping a small number of LPs "
            "solve for specific objectives across their portfolios, and to see if "
            "any of it resonates with your current priorities.",
            "",
            "If it makes sense after that, I’m happy to follow up with more detailed "
            "materials or set up time with one of the underlying managers.",
            "",
            "Best regards,",
            "Bill Sweeney",
            "Founder, Plinian Strategies",
        ]
    )

    body = "\n".join(body_lines)

    return {
        "contacts": [contact],
        "outreach_drafts": [
            {
                "contact_name": contact["full_name"],
                "email": contact["email"],
                "subject": subject,
                "body": body,
            }
        ],
    }


def create_gmail_drafts_stub(outreach: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Stub for Gmail draft creation.
    Currently just returns fake draft URLs; easy to swap to real Gmail API.
    """
    results: List[Dict[str, Any]] = []
    for idx, draft in enumerate(outreach.get("outreach_drafts", []), start=1):
        email = draft.get("email")
        subject = draft.get("subject")
        fake_url = f"https://mail.google.com/mail/u/0/#drafts/PLINIAN_STUB_{idx}"
        results.append(
            {
                "email": email,
                "subject": subject,
                "gmail_draft_url": fake_url,
            }
        )
    logger.info(f"Generated Gmail draft stubs: {results}")
    return results


def update_firm_page_with_outreach(
    firm: Dict[str, Any],
    outreach: Dict[str, Any],
    gmail_results: List[Dict[str, Any]],
) -> None:
    """Update the Prospect Firm Notion page with outreach info."""
    firm_id = firm.get("firm_id")
    if not firm_id:
        logger.warning("Cannot update firm page: missing firm_id in firm dict")
        return

    page = notion.pages.retrieve(page_id=firm_id)
    props = page.get("properties", {})

    first_contact = (outreach.get("contacts") or [{}])[0]
    first_draft = (outreach.get("outreach_drafts") or [{}])[0]
    first_gmail = (gmail_results or [{}])[0]

    contact_label = first_contact.get("full_name") or "Investment Team"
    contact_email = first_contact.get("email")
    subject = first_draft.get("subject")
    draft_url = first_gmail.get("gmail_draft_url")

    now_date = datetime.utcnow().date().isoformat()

    updates: Dict[str, Any] = {}

    if "Latest Outreach Contact" in props:
        updates["Latest Outreach Contact"] = {
            "rich_text": [{"text": {"content": contact_label}}]
        }

    if "Latest Outreach Email" in props and contact_email:
        updates["Latest Outreach Email"] = {"email": contact_email}

    if "Outreach Draft URL" in props and draft_url:
        updates["Outreach Draft URL"] = {"url": draft_url}

    if "Latest Outreach Subject" in props and subject:
        updates["Latest Outreach Subject"] = {
            "rich_text": [{"text": {"content": subject}}]
        }

    if "Last Outreach Run" in props:
        updates["Last Outreach Run"] = {"date": {"start": now_date}}

    if not updates:
        logger.info(
            f"No matching properties to update on firm page {firm_id} "
            "(ensure schema includes Latest Outreach Contact / Email / "
            "Draft URL / Last Outreach Run)."
        )
        return

    notion.pages.update(page_id=firm_id, properties=updates)
    logger.info(f"Updated firm page {firm_id} with outreach info: {updates}")


# =============================================================================
# WEBHOOK SERVER (Flask)
# =============================================================================

def start_webhook_server(port: int = 5000) -> None:
    """
    Start a Flask webhook server.

    Locally: binds to port 5000.
    On Railway: binds to PORT from environment (e.g. 8080).
    """
    from flask import Flask, request, jsonify

    # Use Railway's PORT if present
    port = int(os.environ.get("PORT", port))

    app = Flask(__name__)

    # /webhook/email-reply -----------------------------------------------------
    @app.route("/webhook/email-reply", methods=["POST"])
    def email_reply_webhook():
        try:
            data = request.get_json() or {}
            thread_id = data.get("thread_id")
            sender_email = data.get("sender_email")
            email_body = data.get("email_body", "")
            received_date = data.get("received_date")

            if not thread_id or not sender_email:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Missing required fields: thread_id, sender_email",
                    }
                ), 400

            result = process_email_reply(
                thread_id=thread_id,
                sender_email=sender_email,
                email_body=email_body,
                received_date=received_date,
            )
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Webhook error (/webhook/email-reply): {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    # /webhook/outreach --------------------------------------------------------
    @app.route("/webhook/outreach", methods=["POST"])
    def outreach_webhook():
        try:
        raw_body = request.get_data(as_text=True)
        logger.info(f"[NOTION RAW PAYLOAD] {raw_body}")

        data = request.get_json(silent=True) or {}
        """
        Triggered by a Notion Button ("Send Webhook") from the Prospect Firms database.
        """
        try:
            raw_body = request.get_data(as_text=True)
            logger.info(f"Raw outreach request body: {raw_body}")

            data = request.get_json(silent=True) or {}

            firm_id = data.get("firm_id")
            firm_name_from_payload = data.get("firm_name")
            fit = data.get("fit")
            website_from_payload = data.get("website")

            if not firm_id:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Missing required field: firm_id",
                        "raw_body": raw_body,
                        "parsed_data": data,
                    }
                ), 400

            logger.info(
                f"[Outreach Trigger] firm_id={firm_id}, "
                f"firm_name={firm_name_from_payload}, fit={fit}, "
                f"website={website_from_payload}"
            )

            firm = get_firm_details_from_notion(firm_id)
            outreach = generate_outreach_for_firm(firm)
            gmail_results = create_gmail_drafts_stub(outreach)
            update_firm_page_with_outreach(firm, outreach, gmail_results)

            return jsonify(
                {
                    "status": "ok",
                    "message": "Outreach workflow completed (stub drafts)",
                    "firm": {
                        "firm_id": firm.get("firm_id"),
                        "firm_name": firm.get("firm_name"),
                        "website": firm.get("website"),
                        "plinian_fit": firm.get("plinian_fit"),
                    },
                    "outreach": outreach,
                    "gmail_results": gmail_results,
                }
            ), 200

        except Exception as e:
            logger.error(f"Outreach webhook error (/webhook/outreach): {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    # /health ------------------------------------------------------------------
    @app.route("/health", methods=["GET"])
    def health_check():
        logger.info("🚑 /health endpoint hit")
        return jsonify({"status": "healthy"}), 200

    # Start server -------------------------------------------------------------
    logger.info(f"Starting webhook server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "server":
        start_webhook_server()
    else:
        print("Response Detector - Test Mode")
        print("=" * 50)
        print()
        print("To run as webhook server:")
        print("  python response_detector.py server")
        print()
        print("Example direct call:")
        result = process_email_reply(
            thread_id="example-thread-id",
            sender_email="test@example.com",
            email_body=(
                "Thanks for reaching out! I'd love to discuss this further. "
                "Let's schedule a meeting."
            ),
            received_date="2025-11-24",
        )
        print(f"Result: {result}")
