"""
Plinian Strategies — Email Response & Outreach Webhook
======================================================
Railway-compatible version with gunicorn support.

Endpoints:
    POST /webhook/outreach     - Trigger LLM-powered outreach for a firm
    POST /webhook/email-reply  - Process email reply
    GET  /health               - Health check

Environment Variables:
    NOTION_API_KEY        - Your Notion integration token
    ANTHROPIC_API_KEY     - Anthropic API key for LLM outreach generation
    OUTREACH_LOG_DB_ID    - Outreach Log database ID (for email replies)
    
    # Gmail OAuth (choose one method):
    # Method 1: File-based (local dev)
    GMAIL_TOKEN_PATH          - Path to token.json (default: token.json)
    GMAIL_CREDENTIALS_PATH    - Path to credentials.json (default: credentials.json)
    
    # Method 2: Environment-based (Railway/production)
    GMAIL_TOKEN_JSON          - Full token.json contents as a string
    GMAIL_CREDENTIALS_JSON    - Full credentials.json contents as a string
"""

import os
import sys
import json
import logging
import base64
from datetime import datetime
from typing import Optional, Dict, Any, List
from email.mime.text import MIMEText

from flask import Flask, request, jsonify
from notion_client import Client
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# LLM Integration
from plinian_outreach_llm import generate_outreach_with_llm

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIG & INITIALIZATION
# =============================================================================

load_dotenv()

NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
OUTREACH_LOG_DB_ID = os.environ.get(
    "OUTREACH_LOG_DB_ID",
    "2b5c16a0-949c-8147-8a7f-ca839e1ae002"
)

# Gmail configuration - supports both file-based and env-based tokens
GMAIL_TOKEN_PATH = os.environ.get("GMAIL_TOKEN_PATH", "token.json")
GMAIL_CREDENTIALS_PATH = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
GMAIL_TOKEN_JSON = os.environ.get("GMAIL_TOKEN_JSON")  # For Railway
GMAIL_CREDENTIALS_JSON = os.environ.get("GMAIL_CREDENTIALS_JSON")  # For Railway
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

# Initialize Notion client
notion = Client(auth=NOTION_API_KEY)

# =============================================================================
# FLASK APP (module-level for gunicorn)
# =============================================================================

app = Flask(__name__)


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
    plinian_fit = get_select_or_multi("Best Matches") or get_select_or_multi("Plinian Fit")
    
    notes_parts = []
    for field in ["Qualification Notes", "Notes", "Key Investment Themes", "Network Angles", "Firm Overview"]:
        text = get_rich_text(field)
        if text:
            notes_parts.append(f"{field}: {text}")
    notes = " | ".join(notes_parts) if notes_parts else get_rich_text("Notes")

    firm_details = {
        "firm_id": firm_id,
        "firm_name": firm_name,
        "website": website,
        "plinian_fit": plinian_fit,
        "notes": notes,
        "raw_page": page,
    }
    logger.info(f"Loaded firm details from Notion for {firm_id}: {firm_name}")
    return firm_details


# =============================================================================
# LLM-POWERED OUTREACH GENERATION
# =============================================================================

def generate_outreach_for_firm(firm_data: dict) -> dict:
    """Generate personalized outreach email using Claude API."""
    firm_name = firm_data.get("firm_name", "Unknown Firm")
    
    logger.info(f"Generating LLM outreach for: {firm_name}")
    
    try:
        result = generate_outreach_with_llm(
            firm_name=firm_name,
            website=firm_data.get("website"),
            plinian_fit=firm_data.get("plinian_fit"),
            notes=firm_data.get("notes"),
            raw_page=firm_data.get("raw_page"),
            contact_name=firm_data.get("contact_name"),
            contact_title=firm_data.get("contact_title")
        )
        
        if result["success"]:
            logger.info(f"✅ LLM outreach generated for {firm_name}")
            logger.info(f"   Primary client: {result['primary_client']}")
            return result
        else:
            logger.error(f"❌ LLM generation failed: {result['error']}")
            return _fallback_outreach(firm_name)
            
    except Exception as e:
        logger.error(f"❌ Exception in LLM generation: {e}")
        return _fallback_outreach(firm_name)


def _fallback_outreach(firm_name: str) -> dict:
    """Fallback template if LLM fails."""
    return {
        "subject": "Plinian Strategies - Introduction",
        "body": f"""Hi,

I hope this message finds you well. I'm Bill Sweeney, founder of Plinian Strategies - a boutique capital raising and strategic advisory firm.

I came across {firm_name} and believe there may be alignment between your investment mandate and several managers we represent across real estate, global equities, and private growth equity.

Would you have 15 minutes for a brief introductory call? I'd be happy to share an overview of our current opportunities and learn more about your priorities.

Best regards,
Bill Sweeney
Plinian Strategies
bill@plinian.co
(908) 347-0156
""",
        "primary_client": "General",
        "secondary_clients": [],
        "reasoning": "Fallback template used due to LLM error",
        "success": True,
        "error": None
    }


# =============================================================================
# GMAIL HELPERS
# =============================================================================

def get_gmail_service():
    """
    Build an authenticated Gmail service.
    Supports both file-based tokens (local) and env-based tokens (Railway).
    """
    try:
        logger.info("⚙️ Building Gmail service...")

        creds = None
        
        # Method 1: Environment variable (Railway/production)
        if GMAIL_TOKEN_JSON:
            logger.info("Using GMAIL_TOKEN_JSON from environment")
            token_data = json.loads(GMAIL_TOKEN_JSON)
            creds = Credentials.from_authorized_user_info(token_data, GMAIL_SCOPES)
        
        # Method 2: File-based (local development)
        elif os.path.exists(GMAIL_TOKEN_PATH):
            logger.info(f"Using token file: {GMAIL_TOKEN_PATH}")
            creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_PATH, GMAIL_SCOPES)
        
        else:
            logger.error("❌ No Gmail credentials found (neither env var nor file)")
            return None

        service = build("gmail", "v1", credentials=creds)
        logger.info("✅ Gmail service built successfully.")
        return service

    except Exception as e:
        logger.error(f"❌ Failed to build Gmail service: {e}")
        return None


def create_gmail_draft(outreach: Dict[str, Any]) -> Dict[str, Any]:
    """Create a real Gmail draft from LLM-generated outreach."""
    subject = outreach.get("subject", "Plinian Strategies - Introduction")
    body = outreach.get("body", "")
    
    service = get_gmail_service()
    if not service:
        logger.warning("Gmail service unavailable — returning stub URL")
        return {
            "gmail_draft_id": None,
            "gmail_draft_url": "https://mail.google.com/mail/u/0/#drafts/GMAIL_NOT_CONFIGURED",
            "success": False,
            "error": "Gmail service not configured"
        }

    message = MIMEText(body)
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        created = (
            service.users()
            .drafts()
            .create(
                userId="me",
                body={"message": {"raw": raw}}
            )
            .execute()
        )

        draft_id = created.get("id")
        gmail_url = f"https://mail.google.com/mail/u/0/#drafts?compose={draft_id}"

        logger.info(f"✅ Gmail draft created: {draft_id}")
        
        return {
            "gmail_draft_id": draft_id,
            "gmail_draft_url": gmail_url,
            "success": True,
            "error": None
        }

    except Exception as e:
        logger.error(f"❌ Gmail draft creation failed: {e}")
        return {
            "gmail_draft_id": None,
            "gmail_draft_url": None,
            "success": False,
            "error": str(e)
        }


def update_firm_page_with_outreach(
    firm: Dict[str, Any],
    outreach: Dict[str, Any],
    gmail_result: Dict[str, Any],
) -> None:
    """Update the Prospect Firm Notion page with outreach info."""
    firm_id = firm.get("firm_id")
    if not firm_id:
        logger.warning("Cannot update firm page: missing firm_id")
        return

    page = notion.pages.retrieve(page_id=firm_id)
    props = page.get("properties", {})

    subject = outreach.get("subject", "")
    primary_client = outreach.get("primary_client", "")
    draft_url = gmail_result.get("gmail_draft_url", "")
    reasoning = outreach.get("reasoning", "")

    now_date = datetime.utcnow().date().isoformat()

    updates: Dict[str, Any] = {}

    if "Relationship Stage" in props:
        updates["Relationship Stage"] = {"select": {"name": "Initial Outreach"}}

    if "Last Contact Date" in props:
        updates["Last Contact Date"] = {"date": {"start": now_date}}

    if "Outreach Draft URL" in props and draft_url:
        updates["Outreach Draft URL"] = {"url": draft_url}

    if "Latest Outreach Subject" in props and subject:
        updates["Latest Outreach Subject"] = {
            "rich_text": [{"text": {"content": subject[:2000]}}]
        }

    if "Latest Outreach Client" in props and primary_client:
        updates["Latest Outreach Client"] = {
            "rich_text": [{"text": {"content": primary_client}}]
        }

    if "Qualification Notes" in props and reasoning:
        current_notes = _get_plain_text_from_rich(
            props.get("Qualification Notes", {}).get("rich_text", [])
        )
        new_notes = f"{current_notes}\n\n[Outreach {now_date}] {reasoning}".strip()
        updates["Qualification Notes"] = {
            "rich_text": [{"text": {"content": new_notes[:2000]}}]
        }

    if "Last Outreach Run" in props:
        updates["Last Outreach Run"] = {"date": {"start": now_date}}

    if not updates:
        logger.info(f"No matching properties to update on firm page {firm_id}")
        return

    notion.pages.update(page_id=firm_id, properties=updates)
    logger.info(f"✅ Updated firm page {firm_id} with outreach info")


# =============================================================================
# ROUTES
# =============================================================================

@app.route("/webhook/outreach", methods=["POST"])
def outreach_webhook():
    """
    Main outreach webhook endpoint.
    Receives a firm_id and executes the full outreach workflow.
    
    Accepts two payload formats:
    1. Simple: {"firm_id": "xxx"}
    2. Notion native: {"data": {"id": "xxx", ...}, "source": {...}}
    """
    logger.info("🚨 /webhook/outreach endpoint was hit")

    data = request.get_json() or {}
    logger.info(f"📬 Payload received: {data}")

    # Handle both simple and Notion native payload formats
    firm_id = data.get("firm_id")
    
    # If no direct firm_id, check for Notion's native webhook format
    if not firm_id and "data" in data:
        firm_id = data.get("data", {}).get("id")
        logger.info(f"📋 Extracted firm_id from Notion payload: {firm_id}")

    if not firm_id:
        logger.error("❌ Missing firm_id in payload")
        return jsonify({
            "status": "error",
            "message": "Missing required field: firm_id (or data.id for Notion webhooks)"
        }), 400
    try:
        # 1. Load firm details from Notion
        logger.info(f"📥 Loading firm details for {firm_id}...")
        firm = get_firm_details_from_notion(firm_id)

        if not firm.get("firm_name"):
            logger.warning(f"⚠️ Firm {firm_id} has no name — proceeding anyway")

        # 2. Generate outreach draft via LLM
        logger.info(f"✍️ Generating LLM outreach for {firm.get('firm_name')}...")
        outreach = generate_outreach_for_firm(firm)

        # 3. Create Gmail draft
        logger.info("📧 Creating Gmail draft...")
        gmail_result = create_gmail_draft(outreach)

        # 4. Update firm page in Notion
        logger.info("📝 Updating firm page with outreach info...")
        update_firm_page_with_outreach(firm, outreach, gmail_result)

        logger.info(f"✅ Outreach workflow completed for {firm.get('firm_name')}")

        return jsonify({
            "status": "ok",
            "message": f"Outreach created for {firm.get('firm_name')}",
            "firm_id": firm_id,
            "firm_name": firm.get("firm_name"),
            "primary_client": outreach.get("primary_client"),
            "reasoning": outreach.get("reasoning"),
            "gmail_draft_url": gmail_result.get("gmail_draft_url"),
            "gmail_success": gmail_result.get("success")
        }), 200

    except Exception as e:
        logger.error(f"❌ Outreach workflow failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "firm_id": firm_id
        }), 500


@app.route("/webhook/email-reply", methods=["POST"])
def email_reply_webhook():
    """Email reply detection webhook."""
    logger.info("🚨 /webhook/email-reply endpoint was hit")

    data = request.get_json() or {}
    thread_id = data.get("thread_id")
    sender_email = data.get("sender_email")
    email_body = data.get("email_body")
    received_date = data.get("received_date")

    logger.info(f"📬 Email reply payload received for thread: {thread_id}")

    if not thread_id:
        return jsonify({
            "status": "error",
            "message": "Missing required field: thread_id"
        }), 400

    if not email_body:
        return jsonify({
            "status": "error",
            "message": "Missing required field: email_body"
        }), 400

    try:
        result = process_email_reply(
            thread_id=thread_id,
            sender_email=sender_email or "unknown@example.com",
            email_body=email_body,
            received_date=received_date,
        )

        status_code = 200 if result.get("status") != "error" else 500
        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"❌ Email reply processing failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring."""
    logger.info("💚 /health route hit")
    return jsonify({
        "status": "healthy",
        "service": "plinian-outreach-webhook",
        "timestamp": datetime.utcnow().isoformat()
    }), 200


@app.route("/", methods=["GET"])
def index():
    """Root endpoint with service info."""
    return jsonify({
        "service": "Plinian Strategies Outreach Webhook",
        "version": "2.0.0",
        "endpoints": {
            "/webhook/outreach": "POST - Trigger LLM-powered outreach for a firm",
            "/webhook/email-reply": "POST - Process email reply",
            "/health": "GET - Health check"
        }
    }), 200


# =============================================================================
# LOCAL DEV ENTRYPOINT
# =============================================================================

if __name__ == "__main__":
    print("🚀 Starting Plinian Outreach Webhook (local dev mode)...")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
