"""
PLINIAN WEBHOOK INTEGRATION GUIDE
=================================

This document shows exactly how to integrate the LLM-powered outreach
generation into your existing response_detector.py webhook.

Files to update:
1. response_detector.py (your existing webhook)
2. .env (add ANTHROPIC_API_KEY)
3. requirements.txt (add anthropic package)

"""

# =============================================================================
# STEP 1: UPDATE requirements.txt
# =============================================================================
"""
Add these lines to your requirements.txt:

anthropic>=0.39.0
python-dotenv>=1.0.0

Then run:
pip install -r requirements.txt
"""

# =============================================================================
# STEP 2: UPDATE .env FILE
# =============================================================================
"""
Add your Anthropic API key to .env:

ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx

Get your API key from: https://console.anthropic.com/
"""

# =============================================================================
# STEP 3: MODIFY response_detector.py
# =============================================================================

# --- IMPORT SECTION (add near top of file) ---
IMPORT_PATCH = '''
# Add these imports near the top of response_detector.py
# (after your existing imports)

from plinian_outreach_llm import generate_outreach_with_llm
'''

# --- REPLACE THE STUB FUNCTION ---
# Find this function (around line 230) and replace it entirely:

OLD_STUB_FUNCTION = '''
def generate_outreach_for_firm(firm_data: dict) -> dict:
    """
    STUB: Generate outreach email for a firm.
    TODO: Replace with LLM-powered generation.
    """
    firm_name = firm_data.get("firm_name", "Unknown Firm")
    
    return {
        "subject": f"Plinian Strategies - Introduction ({firm_name})",
        "body": f"""Hi,

I'm reaching out from Plinian Strategies regarding {firm_name}.

[This is a placeholder email - LLM integration pending]

Best regards,
Bill Sweeney
Plinian Strategies
""",
        "primary_client": "TBD"
    }
'''

NEW_LLM_FUNCTION = '''
def generate_outreach_for_firm(firm_data: dict) -> dict:
    """
    Generate personalized outreach email using Claude API.
    
    Args:
        firm_data: Dict containing firm details from Notion
            - firm_name: str
            - website: str (optional)
            - plinian_fit: list[str] (optional) 
            - notes: str (optional)
            - raw_page: dict (optional, full Notion page)
            - contact_name: str (optional)
            - contact_title: str (optional)
    
    Returns:
        Dict with: subject, body, primary_client, reasoning, success, error
    """
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
            # Fall back to basic template
            return _fallback_outreach(firm_name)
            
    except Exception as e:
        logger.error(f"❌ Exception in LLM generation: {e}")
        return _fallback_outreach(firm_name)


def _fallback_outreach(firm_name: str) -> dict:
    """Fallback template if LLM fails."""
    return {
        "subject": f"Plinian Strategies - Introduction",
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
        "success": True,
        "error": None
    }
'''

# =============================================================================
# STEP 4: UPDATE THE WEBHOOK HANDLER (if needed)
# =============================================================================

WEBHOOK_HANDLER_EXAMPLE = '''
@app.post("/webhook/outreach")
async def handle_outreach_webhook(request: Request):
    """
    Webhook endpoint for generating outreach.
    Receives firm_id, loads from Notion, generates email, creates Gmail draft.
    """
    try:
        data = await request.json()
        firm_id = data.get("firm_id")
        
        if not firm_id:
            return JSONResponse(
                status_code=400,
                content={"error": "firm_id required"}
            )
        
        # Load firm from Notion
        logger.info(f"Loading firm {firm_id} from Notion")
        firm_page = notion_client.pages.retrieve(page_id=firm_id)
        
        # Extract firm data
        firm_data = extract_firm_data(firm_page)
        
        # Generate outreach with LLM
        outreach = generate_outreach_for_firm(firm_data)
        
        if not outreach.get("success", True):
            logger.warning(f"Using fallback outreach: {outreach.get('error')}")
        
        # Create Gmail draft
        draft_result = create_gmail_draft(
            to=firm_data.get("contact_email", ""),
            subject=outreach["subject"],
            body=outreach["body"]
        )
        
        # Update Notion with outreach metadata
        update_notion_outreach_status(
            firm_id=firm_id,
            subject=outreach["subject"],
            primary_client=outreach.get("primary_client", ""),
            draft_id=draft_result.get("draft_id")
        )
        
        return JSONResponse(content={
            "success": True,
            "firm_name": firm_data.get("firm_name"),
            "primary_client": outreach.get("primary_client"),
            "draft_created": bool(draft_result.get("draft_id")),
            "reasoning": outreach.get("reasoning", "")
        })
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


def extract_firm_data(notion_page: dict) -> dict:
    """Extract firm data from Notion page for LLM generation."""
    props = notion_page.get("properties", {})
    
    # Extract firm name
    firm_name = ""
    if "Firm Name" in props:
        titles = props["Firm Name"].get("title", [])
        firm_name = "".join(t.get("plain_text", "") for t in titles)
    
    # Extract website
    website = props.get("Website", {}).get("url", "")
    
    # Extract Best Matches (multi-select)
    plinian_fit = []
    if "Best Matches" in props:
        options = props["Best Matches"].get("multi_select", [])
        plinian_fit = [o.get("name", "") for o in options]
    
    # Extract notes (combine several fields)
    notes_parts = []
    for field in ["Qualification Notes", "Research Notes", "Notes", "Key Investment Themes"]:
        if field in props:
            texts = props[field].get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in texts)
            if text:
                notes_parts.append(text)
    notes = " | ".join(notes_parts)
    
    return {
        "firm_name": firm_name,
        "website": website,
        "plinian_fit": plinian_fit,
        "notes": notes,
        "raw_page": notion_page
    }
'''

# =============================================================================
# COMPLETE MODIFIED response_detector.py STRUCTURE
# =============================================================================

FULL_STRUCTURE_EXAMPLE = '''
"""
response_detector.py - Plinian Outreach Webhook
Modified to use LLM-powered email generation
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from notion_client import Client as NotionClient

# LLM Integration
from plinian_outreach_llm import generate_outreach_with_llm

# Gmail integration (your existing code)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients
app = FastAPI()
notion_client = NotionClient(auth=os.getenv("NOTION_API_KEY"))

# ... (your existing Gmail setup code) ...


# =============================================================================
# OUTREACH GENERATION (LLM-POWERED)
# =============================================================================

def generate_outreach_for_firm(firm_data: dict) -> dict:
    """Generate personalized outreach using Claude API."""
    # ... (use the NEW_LLM_FUNCTION code above) ...


def _fallback_outreach(firm_name: str) -> dict:
    """Fallback template if LLM fails."""
    # ... (use the fallback code above) ...


# =============================================================================
# NOTION HELPERS
# =============================================================================

def extract_firm_data(notion_page: dict) -> dict:
    """Extract firm data from Notion page."""
    # ... (use the extract_firm_data code above) ...


def update_notion_outreach_status(
    firm_id: str,
    subject: str,
    primary_client: str,
    draft_id: Optional[str]
) -> None:
    """Update Notion firm page with outreach metadata."""
    # Your existing Notion update code
    pass


# =============================================================================
# GMAIL HELPERS
# =============================================================================

def create_gmail_draft(to: str, subject: str, body: str) -> dict:
    """Create Gmail draft."""
    # Your existing Gmail draft creation code
    pass


# =============================================================================
# WEBHOOK ENDPOINT
# =============================================================================

@app.post("/webhook/outreach")
async def handle_outreach_webhook(request: Request):
    """Main webhook handler."""
    # ... (use the webhook handler code above) ...


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''

# =============================================================================
# PRINT INSTRUCTIONS
# =============================================================================

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════╗
║         PLINIAN WEBHOOK - LLM INTEGRATION INSTRUCTIONS           ║
╚══════════════════════════════════════════════════════════════════╝

STEP 1: COPY THE MODULE
-----------------------
Copy plinian_outreach_llm.py to your webhook directory:
  c:\\NantucketHub\\plinian-webhook\\plinian_outreach_llm.py

STEP 2: INSTALL DEPENDENCIES
----------------------------
pip install anthropic python-dotenv

STEP 3: ADD API KEY
-------------------
Add to your .env file:
  ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx

STEP 4: MODIFY response_detector.py
------------------------------------
a) Add import at top:
   from plinian_outreach_llm import generate_outreach_with_llm

b) Replace the stub generate_outreach_for_firm() function
   with the LLM-powered version (see code above)

STEP 5: TEST
------------
Run the test harness:
  python plinian_outreach_llm.py

Then test the webhook:
  curl -X POST http://localhost:8000/webhook/outreach \\
       -H "Content-Type: application/json" \\
       -d '{"firm_id": "your-notion-firm-page-id"}'

EXPECTED OUTPUT
---------------
{
  "success": true,
  "firm_name": "Example Family Office",
  "primary_client": "StoneRiver",
  "draft_created": true,
  "reasoning": "Strong fit for StoneRiver because..."
}
""")
