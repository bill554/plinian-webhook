"""
Plinian Enrichment Pipeline - Railway Flask Application
Handles webhooks between Notion, Clay, and Claude for automated firm/contact enrichment.
"""

import os
import hmac
import hashlib
import logging
import json
import requests
from flask import Flask, request, jsonify

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment variables
NOTION_API_KEY = os.environ.get('NOTION_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
CLAY_FIRM_WEBHOOK_URL = os.environ.get('CLAY_FIRM_WEBHOOK_URL')
CLAY_PERSON_WEBHOOK_URL = os.environ.get('CLAY_PERSON_WEBHOOK_URL')
RAILWAY_WEBHOOK_SECRET = os.environ.get('RAILWAY_WEBHOOK_SECRET')
RAILWAY_PUBLIC_URL = os.environ.get('RAILWAY_PUBLIC_URL', '')

# Notion database IDs
PROSPECT_FIRMS_DB = '2aec16a0-949c-802a-851e-de429d9503f4'
PROSPECTS_DB = '2aec16a0-949c-8061-9fdd-daabdc22d5e2'

# Notion API headers
NOTION_HEADERS = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28'
}


def verify_webhook_signature(req):
    """Verify webhook signature if secret is configured."""
    if not RAILWAY_WEBHOOK_SECRET:
        return True
    
    signature = req.headers.get('X-Webhook-Signature', '')
    if not signature:
        return True  # Allow unsigned requests (from Notion automations)
    
    payload = req.get_data()
    expected = hmac.new(
        RAILWAY_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected)


def get_notion_page(page_id):
    """Fetch a Notion page by ID."""
    try:
        url = f'https://api.notion.com/v1/pages/{page_id}'
        response = requests.get(url, headers=NOTION_HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to get Notion page {page_id}: {e}")
        return None


def update_notion_page(page_id, properties):
    """Update a Notion page with given properties."""
    try:
        url = f'https://api.notion.com/v1/pages/{page_id}'
        payload = {'properties': properties}
        response = requests.patch(url, headers=NOTION_HEADERS, json=payload)
        response.raise_for_status()
        logger.info(f"Updated Notion page {page_id}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to update Notion page {page_id}: {e}")
        return None


def create_notion_page(database_id, properties):
    """Create a new page in a Notion database."""
    try:
        url = 'https://api.notion.com/v1/pages'
        payload = {
            'parent': {'database_id': database_id},
            'properties': properties
        }
        response = requests.post(url, headers=NOTION_HEADERS, json=payload)
        response.raise_for_status()
        logger.info(f"Created Notion page in {database_id}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to create Notion page: {e}")
        return None


def query_notion_database(database_id, filter_obj=None):
    """Query a Notion database with optional filter."""
    try:
        url = f'https://api.notion.com/v1/databases/{database_id}/query'
        payload = {}
        if filter_obj:
            payload['filter'] = filter_obj
        response = requests.post(url, headers=NOTION_HEADERS, json=payload)
        response.raise_for_status()
        return response.json().get('results', [])
    except Exception as e:
        logger.error(f"Failed to query Notion database {database_id}: {e}")
        return []


def send_to_clay(webhook_url, data):
    """Send data to a Clay webhook."""
    try:
        response = requests.post(webhook_url, json=data, timeout=30)
        response.raise_for_status()
        logger.info(f"Sent to Clay: {data.get('firm_name', data.get('name', 'unknown'))}")
        return True
    except Exception as e:
        logger.error(f"Failed to send to Clay: {e}")
        return False


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.route('/', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'plinian-enrichment',
        'endpoints': [
            '/webhook/notion/new-firm',
            '/webhook/clay/firm-enriched',
            '/webhook/clay/firm-score',
            '/webhook/clay/person-enriched'
        ]
    })


@app.route('/health', methods=['GET'])
def health():
    """Alternative health check."""
    return jsonify({'status': 'ok'})


# =============================================================================
# NOTION → RAILWAY: New Firm Added
# =============================================================================

@app.route('/webhook/notion/new-firm', methods=['POST'])
def handle_notion_new_firm():
    """
    Triggered when a new firm is added to Prospect Firms in Notion.
    Sends firm to Clay for enrichment.
    """
    if not verify_webhook_signature(request):
        return jsonify({'error': 'Invalid signature'}), 401
    
    data = request.json or {}
    logger.info(f"Received new firm webhook: {json.dumps(data)[:500]}")
    
    # Handle Notion automation payload structure
    if 'data' in data:
        data = data['data']
    
    # Extract page ID and properties
    page_id = data.get('id', '')
    props = data.get('properties', {})
    
    # Detect restart trigger
    is_restart = False
    if props.get('Restart Enrichment', {}).get('checkbox'):
        is_restart = True
        logger.info(f"Restart enrichment triggered for page {page_id}")
    
    # Get firm name - handle both title array and plain text
    firm_name_prop = props.get('Firm Name', {})
    if firm_name_prop.get('title'):
        firm_name = firm_name_prop['title'][0]['plain_text'] if firm_name_prop['title'] else ''
    else:
        firm_name = firm_name_prop.get('plain_text', '')
    
    # Get website
    website = props.get('Website', {}).get('url', '')
    
    # If website empty and this is a restart, fetch full page from Notion
    if not website and is_restart and page_id:
        logger.info(f"Fetching full page for restart: {page_id}")
        page = get_notion_page(page_id)
        if page:
            props = page.get('properties', {})
            website = props.get('Website', {}).get('url', '')
            # Also get firm name if we didn't have it
            if not firm_name:
                firm_name_prop = props.get('Firm Name', {})
                if firm_name_prop.get('title'):
                    firm_name = firm_name_prop['title'][0]['plain_text'] if firm_name_prop['title'] else ''
    
    if not website:
        logger.warning(f"No website provided for firm: {firm_name}")
        return jsonify({'error': 'No website/domain provided'}), 400
    
    if not page_id:
        logger.warning("No page ID in webhook payload")
        return jsonify({'error': 'No page ID provided'}), 400
    
    # Extract domain from URL
    domain = website.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
    
    # Prepare payload for Clay
    clay_payload = {
        'notion_page_id': page_id,
        'firm_name': firm_name,
        'website': website,
        'domain': domain,
        'callback_url': f"{RAILWAY_PUBLIC_URL}/webhook/clay/firm-enriched"
    }
    
    # Send to Clay
    if CLAY_FIRM_WEBHOOK_URL:
        success = send_to_clay(CLAY_FIRM_WEBHOOK_URL, clay_payload)
        if success:
            # Update status in Notion
            updates = {
                'Research Status': {'select': {'name': 'Researching'}}
            }
            # Uncheck restart if this was a restart trigger
            if is_restart:
                updates['Restart Enrichment'] = {'checkbox': False}
            update_notion_page(page_id, updates)
            return jsonify({'status': 'sent_to_clay', 'firm': firm_name})
        else:
            return jsonify({'error': 'Failed to send to Clay'}), 500
    else:
        logger.warning("CLAY_FIRM_WEBHOOK_URL not configured")
        return jsonify({'error': 'Clay webhook not configured'}), 500


# =============================================================================
# CLAY → RAILWAY: Firm Enriched (Basic)
# =============================================================================

@app.route('/webhook/clay/firm-enriched', methods=['POST'])
def handle_firm_enriched():
    """
    Receives enriched firm data from Clay.
    Updates Notion with basic firmographic data.
    """
    data = request.json or {}
    logger.info(f"Received enriched firm: {json.dumps(data)[:500]}")
    
    notion_page_id = data.get('notion_page_id')
    if not notion_page_id:
        return jsonify({'error': 'No notion_page_id provided'}), 400
    
    # Build Notion update payload
    updates = {}
    
    # Map Clay fields to Notion properties
    if data.get('linkedin_url'):
        updates['LinkedIn Company URL'] = {'url': data['linkedin_url']}
    
    if data.get('location'):
        updates['Location / Headquarters Location'] = {
            'rich_text': [{'text': {'content': str(data['location'])[:2000]}}]
        }
    
    if data.get('firm_overview'):
        updates['Firm Overview'] = {
            'rich_text': [{'text': {'content': str(data['firm_overview'])[:2000]}}]
        }
    
    if data.get('employee_count'):
        # Could map to a field if we add one
        pass
    
    # Update Notion if we have updates
    if updates:
        update_notion_page(notion_page_id, updates)
    
    return jsonify({
        'status': 'success',
        'page_id': notion_page_id,
        'updates_applied': list(updates.keys())
    })


# =============================================================================
# CLAY → RAILWAY: Firm Scoring (with Claude Independent Research)
# =============================================================================

@app.route('/webhook/clay/firm-score', methods=['POST'])
def handle_firm_scoring():
    """
    Receives firm data from Clay for scoring.
    Claude does independent research, then combines with Clay data for scoring.
    Updates Notion with fit scores per client.
    """
    data = request.json or {}
    
    notion_page_id = data.get('notion_page_id')
    firm_name = data.get('firm_name')
    website = data.get('website', '')
    
    # Get research from query param OR body
    firm_research = request.args.get('research', '') or data.get('firm_research', '')
    
    # Sanitize research text
    if firm_research:
        firm_research = str(firm_research).replace('\n', ' ').replace('\r', ' ')[:5000]
    
    logger.info(f"Received firm for scoring: {firm_name}, research length: {len(firm_research)}")
    
    if not notion_page_id:
        return jsonify({'error': 'No notion_page_id provided'}), 400
    
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not configured")
        return jsonify({'error': 'Anthropic API key not configured'}), 500
    
    import anthropic
    
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        # =====================================================================
        # STEP 1: Claude Independent Research
        # =====================================================================
        research_prompt = f"""You are an expert on institutional investors and asset allocators. Research this firm from your knowledge:

FIRM: {firm_name}
WEBSITE: {website}

Provide what you know about:
1. What type of organization is this? (pension, endowment, foundation, family office, RIA, OCIO, etc.)
2. Approximate AUM if known
3. Asset allocation approach (what do they invest in?)
4. Do they allocate to: Real Estate? Private Equity? Public Equities? Alternatives?
5. Investment style (core, value-add, opportunistic, growth, etc.)
6. Geographic focus
7. Any notable investment preferences or constraints
8. Key investment staff if known

If you don't have information on this firm, say "Limited information available" and provide any reasonable inferences based on the firm type and website.

Be concise but comprehensive. Focus on investment-relevant details."""

        research_response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": research_prompt}
            ]
        )
        
        claude_research = research_response.content[0].text
        logger.info(f"Claude independent research completed for {firm_name}: {len(claude_research)} chars")
        
        # =====================================================================
        # STEP 2: Combined Scoring with Both Research Sources
        # =====================================================================
        scoring_prompt = f"""You are an expert institutional capital raising advisor. Analyze this allocator firm and score their fit for each of our 6 clients.

FIRM: {firm_name}
WEBSITE: {website}

CLAY ENRICHMENT DATA:
{firm_research if firm_research else "No enrichment data provided"}

CLAUDE INDEPENDENT RESEARCH:
{claude_research}

SCORING PHILOSOPHY:
- Most diversified institutional allocators (pensions, E&Fs, family offices) have broad mandates that include real estate and private equity
- Default to MODERATE fit if they have the relevant asset class allocation, even without specific sub-sector signals
- Upgrade to STRONG if there are explicit positive signals
- Only mark WEAK if there are mismatches or very limited allocations
- Only mark N/A if truly incompatible (e.g., public equity only, no alternatives)

SCORE EACH CLIENT:

1. STONERIVER (Multifamily Real Estate - Southeast US, Value-Add):
   - STRONG if: Value-add or opportunistic appetite, vertically integrated preference, explicit multifamily interest, co-invest opportunities
   - MODERATE if: Has real estate allocation (most diversified allocators do), invests in private RE generally
   - WEAK if: Core-only mandate, gateway cities only, very small RE allocation
   - N/A if: No real estate allocation at all

2. ASHTON GRAY (Healthcare-Anchored Retail Real Estate - Stabilized Income):
   - STRONG if: Retail real estate interest, income/core+ focus, NNN or retail experience
   - MODERATE if: Has real estate allocation, seeks income/yield, diversified RE exposure
   - WEAK if: Explicitly avoids retail, development-only focus
   - N/A if: No real estate allocation at all

3. WILLOW CREST (Inflation-Linked Structural Alpha - Long Duration):
   - STRONG if: Real assets mandate, inflation protection interest, 10-20yr horizon tolerance, $50M+ checks
   - MODERATE if: Has real assets/alternatives allocation, diversified institutional investor
   - WEAK if: Short duration focus, liquidity constraints, small ticket sizes
   - N/A if: No alternatives/real assets allocation

4. ICW HOLDINGS (Global Macro-Driven Public Equities):
   - STRONG if: Global equity mandate, macro-aware investing, risk-managed equity interest
   - MODERATE if: Has public equity allocation, diversified portfolio approach
   - WEAK if: Passive/index only, single region focus
   - N/A if: Private markets only, no public equity

5. HIGHMOUNT (Sports & Entertainment Growth PE):
   - STRONG if: Growth PE mandate, media/entertainment/sports interest, consumer/TMT focus
   - MODERATE if: Has private equity allocation, growth equity experience, diversified PE program
   - WEAK if: Buyout-only, very narrow sector focus excluding consumer/media
   - N/A if: No private equity allocation

6. CO-INVEST PLATFORM (Direct Private Deals - Variable):
   - STRONG if: Direct co-invest capability, flexible mandate, fast decision process, experienced deal team
   - MODERATE if: Has alternatives allocation, some direct investment experience
   - WEAK if: Fund-only investor, slow IC process, needs lead sponsor
   - N/A if: No alternatives capability

IMPORTANT GUIDANCE:
- Pensions, endowments, foundations, and large family offices typically have BOTH real estate AND private equity allocations
- If research shows diversified alternatives program → default to MODERATE for StoneRiver, Ashton Gray, Highmount, and Co-Invest
- Be generous with MODERATE - these are qualified institutional allocators worth a conversation
- Reserve WEAK/N/A for clear mismatches, not absence of specific signals

Return your analysis as JSON:
{{
    "stoneriver_fit": "Strong/Moderate/Weak/N/A",
    "stoneriver_rationale": "brief reason",
    "ashtongray_fit": "Strong/Moderate/Weak/N/A", 
    "ashtongray_rationale": "brief reason",
    "willowcrest_fit": "Strong/Moderate/Weak/N/A",
    "willowcrest_rationale": "brief reason",
    "icw_fit": "Strong/Moderate/Weak/N/A",
    "icw_rationale": "brief reason",
    "highmount_fit": "Strong/Moderate/Weak/N/A",
    "highmount_rationale": "brief reason",
    "coinvest_fit": "Strong/Moderate/Weak/N/A",
    "coinvest_rationale": "brief reason",
    "best_match": "client name with strongest fit",
    "overall_notes": "1-2 sentence summary of allocator profile and recommended approach"
}}

Return ONLY valid JSON, no markdown fences or other text."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": scoring_prompt}
            ]
        )
        
        response_text = message.content[0].text
        logger.info(f"Claude scoring response: {response_text[:500]}")
        
        # Strip markdown code fences if present
        clean_response = response_text.strip()
        if clean_response.startswith('```'):
            clean_response = clean_response.split('\n', 1)[1]
        if clean_response.endswith('```'):
            clean_response = clean_response.rsplit('```', 1)[0]
        clean_response = clean_response.strip()
        
        # Parse JSON response
        scores = json.loads(clean_response)
        
        # Normalize fit values to match Notion select options
        def normalize_fit(value):
            if not value:
                return 'N/A'
            value = str(value).strip()
            if value.lower() in ['strong', 'strong fit']:
                return 'Strong'
            elif value.lower() in ['moderate', 'moderate fit']:
                return 'Moderate'
            elif value.lower() in ['weak', 'weak fit']:
                return 'Weak'
            else:
                return 'N/A'
        
        # Build Notion update payload
        notion_updates = {
            'StoneRiver Fit': {'select': {'name': normalize_fit(scores.get('stoneriver_fit'))}},
            'Ashton Gray Fit': {'select': {'name': normalize_fit(scores.get('ashtongray_fit'))}},
            'Willow Crest Fit': {'select': {'name': normalize_fit(scores.get('willowcrest_fit'))}},
            'ICW Fit': {'select': {'name': normalize_fit(scores.get('icw_fit'))}},
            'Highmount Fit': {'select': {'name': normalize_fit(scores.get('highmount_fit'))}},
            'Co-Invests Fit': {'select': {'name': normalize_fit(scores.get('coinvest_fit'))}},
            'Research Status': {'select': {'name': 'Qualified'}}
        }
        
        # Build Qualification Notes with rationales
        rationale = f"""Best Match: {scores.get('best_match', 'TBD')}

StoneRiver: {scores.get('stoneriver_rationale', '')}
Ashton Gray: {scores.get('ashtongray_rationale', '')}
Willow Crest: {scores.get('willowcrest_rationale', '')}
ICW: {scores.get('icw_rationale', '')}
Highmount: {scores.get('highmount_rationale', '')}
Co-Invest: {scores.get('coinvest_rationale', '')}

{scores.get('overall_notes', '')}"""
        
        notion_updates['Qualification Notes'] = {
            'rich_text': [{'text': {'content': rationale[:2000]}}]
        }
        
        # Update Firm Overview with Claude's independent research
        notion_updates['Firm Overview'] = {
            'rich_text': [{'text': {'content': claude_research[:2000]}}]
        }
        
        # Determine Best Matches multi-select
        best_matches = []
        fit_mapping = {
            'stoneriver_fit': 'StoneRiver',
            'ashtongray_fit': 'Ashton Gray',
            'willowcrest_fit': 'Willow Crest',
            'icw_fit': 'ICW',
            'highmount_fit': 'Highmount',
            'coinvest_fit': 'Co-Invests'
        }
        
        for key, client_name in fit_mapping.items():
            if normalize_fit(scores.get(key)) == 'Strong':
                best_matches.append({'name': client_name})
        
        if best_matches:
            notion_updates['Best Matches'] = {'multi_select': best_matches}
        
        # Update Notion
        update_notion_page(notion_page_id, notion_updates)
        
        return jsonify({
            'status': 'success',
            'firm': firm_name,
            'scores': scores,
            'claude_research_length': len(claude_research)
        })
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        logger.error(f"Raw response: {response_text}")
        return jsonify({'error': 'Failed to parse scoring response', 'raw': response_text[:500]}), 500
    except Exception as e:
        logger.error(f"Claude scoring failed: {str(e)}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# CLAY → RAILWAY: Person Enriched
# =============================================================================

@app.route('/webhook/clay/person-enriched', methods=['POST'])
def handle_person_enriched():
    """
    Receives enriched person/contact data from Clay.
    Creates or updates Prospect record in Notion.
    """
    data = request.json or {}
    logger.info(f"Received enriched person: {json.dumps(data)[:500]}")
    
    # Required fields
    name = data.get('name', '').strip()
    firm_name = data.get('firm_name', '').strip()
    notion_firm_page_id = data.get('notion_page_id', '')
    
    if not name:
        return jsonify({'error': 'No name provided'}), 400
    
    # Check if prospect already exists
    existing = query_notion_database(
        PROSPECTS_DB,
        {
            'and': [
                {'property': 'Name', 'title': {'equals': name}},
                {'property': 'Company', 'rich_text': {'contains': firm_name}}
            ]
        }
    )
    
    # Build properties
    properties = {
        'Name': {'title': [{'text': {'content': name}}]},
        'Company': {'rich_text': [{'text': {'content': firm_name}}]},
        'Status': {'select': {'name': 'New'}}
    }
    
    # Optional fields
    if data.get('email'):
        properties['Email'] = {'email': data['email']}
    
    if data.get('title'):
        properties['Title/Role'] = {
            'rich_text': [{'text': {'content': str(data['title'])[:2000]}}]
        }
    
    if data.get('linkedin_url'):
        properties['LinkedIn URL'] = {'url': data['linkedin_url']}
    
    if data.get('phone'):
        properties['Mobile Phone'] = {'phone_number': data['phone']}
    
    if data.get('location'):
        # Could add to notes or a location field
        pass
    
    # Map organization type if provided
    org_type = data.get('organization_type', '')
    if org_type:
        org_type_mapping = {
            'pension': 'Public Pension',
            'endowment': 'E&F',
            'foundation': 'E&F',
            'family office': 'Family Office',
            'ria': 'RIA',
            'ocio': 'OCIO',
            'hospital': 'Hospital/Healthcare',
            'healthcare': 'Hospital/Healthcare'
        }
        for key, notion_value in org_type_mapping.items():
            if key in org_type.lower():
                properties['Organization Type'] = {'select': {'name': notion_value}}
                break
    
    if existing:
        # Update existing prospect
        page_id = existing[0]['id']
        update_notion_page(page_id, properties)
        return jsonify({
            'status': 'updated',
            'name': name,
            'page_id': page_id
        })
    else:
        # Create new prospect
        result = create_notion_page(PROSPECTS_DB, properties)
        if result:
            return jsonify({
                'status': 'created',
                'name': name,
                'page_id': result.get('id')
            })
        else:
            return jsonify({'error': 'Failed to create prospect'}), 500


# =============================================================================
# MANUAL TRIGGER: Score Existing Firm
# =============================================================================

@app.route('/api/score-firm/<page_id>', methods=['POST'])
def manual_score_firm(page_id):
    """
    Manually trigger scoring for an existing firm in Notion.
    Useful for re-scoring or testing.
    """
    # Fetch the firm from Notion
    page = get_notion_page(page_id)
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    
    props = page.get('properties', {})
    
    # Extract firm name
    firm_name_prop = props.get('Firm Name', {})
    if firm_name_prop.get('title'):
        firm_name = firm_name_prop['title'][0]['plain_text'] if firm_name_prop['title'] else ''
    else:
        firm_name = ''
    
    # Extract website
    website = props.get('Website', {}).get('url', '')
    
    # Extract any existing overview as research
    overview_prop = props.get('Firm Overview', {})
    firm_research = ''
    if overview_prop.get('rich_text'):
        firm_research = overview_prop['rich_text'][0]['plain_text'] if overview_prop['rich_text'] else ''
    
    # Call the scoring endpoint internally
    with app.test_client() as client:
        response = client.post(
            '/webhook/clay/firm-score',
            json={
                'notion_page_id': page_id,
                'firm_name': firm_name,
                'website': website,
                'firm_research': firm_research
            }
        )
        return response.get_json(), response.status_code


# =============================================================================
# UTILITY: List Recent Firms
# =============================================================================

@app.route('/api/firms/recent', methods=['GET'])
def list_recent_firms():
    """List recently added firms from Notion."""
    firms = query_notion_database(PROSPECT_FIRMS_DB)
    
    result = []
    for firm in firms[:20]:  # Limit to 20
        props = firm.get('properties', {})
        
        # Extract firm name
        firm_name_prop = props.get('Firm Name', {})
        if firm_name_prop.get('title'):
            firm_name = firm_name_prop['title'][0]['plain_text'] if firm_name_prop['title'] else ''
        else:
            firm_name = ''
        
        # Extract status
        status_prop = props.get('Research Status', {})
        status = status_prop.get('select', {}).get('name', '') if status_prop.get('select') else ''
        
        result.append({
            'id': firm['id'],
            'name': firm_name,
            'status': status,
            'url': firm.get('url', '')
        })
    
    return jsonify({'firms': result})


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
