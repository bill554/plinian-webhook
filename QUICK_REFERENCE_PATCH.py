# PLINIAN WEBHOOK - LLM INTEGRATION QUICK REFERENCE
# ==================================================
# Copy this code directly into response_detector.py

# ============================================================================
# 1. ADD THIS IMPORT (near top of file, after existing imports)
# ============================================================================

from plinian_outreach_llm import generate_outreach_with_llm

# ============================================================================
# 2. REPLACE YOUR STUB generate_outreach_for_firm() WITH THIS:
# ============================================================================

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


# ============================================================================
# 3. UPDATE YOUR extract_firm_data() FUNCTION (if needed)
# ============================================================================
# Make sure it returns these keys for the LLM:

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
    for field in ["Qualification Notes", "Notes", "Key Investment Themes", "Network Angles"]:
        if field in props:
            texts = props[field].get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in texts)
            if text:
                notes_parts.append(f"{field}: {text}")
    notes = " | ".join(notes_parts)
    
    return {
        "firm_name": firm_name,
        "website": website,
        "plinian_fit": plinian_fit,
        "notes": notes,
        "raw_page": notion_page  # Pass full page for additional property extraction
    }


# ============================================================================
# 4. SETUP CHECKLIST
# ============================================================================
"""
□ Copy plinian_outreach_llm.py to c:\NantucketHub\plinian-webhook\
□ Run: pip install anthropic python-dotenv
□ Add to .env: ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
□ Add import at top of response_detector.py
□ Replace generate_outreach_for_firm() function
□ Update extract_firm_data() if needed
□ Test: python plinian_outreach_llm.py
□ Test webhook: POST /webhook/outreach with {"firm_id": "..."}
"""

# ============================================================================
# 5. EXPECTED LLM OUTPUT STRUCTURE
# ============================================================================
"""
{
    "subject": "Plinian Strategies - Southeast Real Estate Opportunity",
    "body": "Hi Sarah,\n\nI hope this finds you well...",
    "primary_client": "StoneRiver",
    "secondary_clients": ["Ashton Gray"],
    "reasoning": "Strong fit for StoneRiver because...",
    "success": true,
    "error": null
}
"""
