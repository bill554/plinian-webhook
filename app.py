from flask import Flask, request, jsonify
import requests
import os
import logging
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
NOTION_API_KEY = os.environ.get('NOTION_API_KEY')
CLAY_FIRM_WEBHOOK_URL = os.environ.get('CLAY_FIRM_WEBHOOK_URL')
CLAY_PERSON_WEBHOOK_URL = os.environ.get('CLAY_PERSON_WEBHOOK_URL')
RAILWAY_WEBHOOK_SECRET = os.environ.get('RAILWAY_WEBHOOK_SECRET')
RAILWAY_PUBLIC_URL = os.environ.get('RAILWAY_PUBLIC_URL', '')

PROSPECT_FIRMS_DB_ID = '2aec16a0-949c-802a-851e-de429d9503f4'
PROSPECTS_DB_ID = '2aec16a0-949c-8061-9fdd-daabdc22d5e2'

NOTION_HEADERS = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28'
}


def verify_webhook_signature(req):
    if not RAILWAY_WEBHOOK_SECRET:
        return True
    signature = req.headers.get('X-Webhook-Signature', '')
    return signature == RAILWAY_WEBHOOK_SECRET


def extract_domain(website_url):
    if not website_url:
        return None
    domain = website_url.lower()
    domain = domain.replace('https://', '').replace('http://', '')
    domain = domain.replace('www.', '')
    domain = domain.split('/')[0]
    return domain


def get_notion_page(page_id):
    url = f'https://api.notion.com/v1/pages/{page_id}'
    response = requests.get(url, headers=NOTION_HEADERS)
    if response.status_code == 200:
        return response.json()
    logger.error(f"Failed to fetch Notion page: {response.status_code}")
    return None


def update_notion_page(page_id, properties):
    url = f'https://api.notion.com/v1/pages/{page_id}'
    payload = {'properties': properties}
    response = requests.patch(url, headers=NOTION_HEADERS, json=payload)
    if response.status_code == 200:
        return response.json()
    logger.error(f"Failed to update Notion page: {response.status_code} - {response.text}")
    return None


def create_notion_page(database_id, properties):
    url = 'https://api.notion.com/v1/pages'
    payload = {
        'parent': {'database_id': database_id},
        'properties': properties
    }
    response = requests.post(url, headers=NOTION_HEADERS, json=payload)
    if response.status_code == 200:
        return response.json()
    logger.error(f"Failed to create Notion page: {response.status_code} - {response.text}")
    return None


def send_to_clay_firm_table(data):
    if not CLAY_FIRM_WEBHOOK_URL:
        logger.error("CLAY_FIRM_WEBHOOK_URL not configured")
        return False
    callback_url = f"{RAILWAY_PUBLIC_URL}/webhook/clay/firm-enriched"
    payload = {
        'notion_page_id': data.get('page_id'),
        'firm_name': data.get('firm_name'),
        'domain': data.get('domain'),
        'website': data.get('website'),
        'callback_url': callback_url
    }
    logger.info(f"Sending to Clay firm table: {payload}")
    response = requests.post(CLAY_FIRM_WEBHOOK_URL, json=payload)
    if response.status_code in [200, 201, 202]:
        logger.info("Successfully sent to Clay")
        return True
    logger.error(f"Failed to send to Clay: {response.status_code}")
    return False


def send_to_clay_person_table(data):
    if not CLAY_PERSON_WEBHOOK_URL:
        logger.error("CLAY_PERSON_WEBHOOK_URL not configured")
        return False
    callback_url = f"{RAILWAY_PUBLIC_URL}/webhook/clay/person-enriched"
    payload = {
        'notion_page_id': data.get('page_id'),
        'full_name': data.get('full_name'),
        'company_domain': data.get('company_domain'),
        'company_name': data.get('company_name'),
        'linkedin_url': data.get('linkedin_url'),
        'callback_url': callback_url
    }
    logger.info(f"Sending to Clay person table: {payload}")
    response = requests.post(CLAY_PERSON_WEBHOOK_URL, json=payload)
    if response.status_code in [200, 201, 202]:
        logger.info("Successfully sent to Clay")
        return True
    logger.error(f"Failed to send to Clay: {response.status_code}")
    return False


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'plinian-enrichment-webhook',
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/routes', methods=['GET'])
def list_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods - {'HEAD', 'OPTIONS'}),
            'path': rule.rule
        })
    return jsonify({'routes': routes})


@app.route('/webhook/notion/new-firm', methods=['POST'])
def handle_notion_new_firm():
    if not verify_webhook_signature(request):
        return jsonify({'error': 'Invalid signature'}), 401
    
    payload = request.json
    logger.info(f"Received new firm webhook: {payload}")
    
    # Handle Notion's nested payload structure
    if 'data' in payload and isinstance(payload['data'], dict):
        # Notion automation format
        page_data = payload['data']
        page_id = page_data.get('id')
        props = page_data.get('properties', {})
        
        # Extract firm name
        firm_name = ''
        if props.get('Firm Name', {}).get('title'):
            title_arr = props['Firm Name']['title']
            if title_arr:
                firm_name = title_arr[0].get('plain_text', '')
        
        # Extract website
        website = props.get('Website', {}).get('url', '')
        
        # Check if this is a restart trigger
        is_restart = False
        if props.get('Restart Enrichment', {}).get('checkbox'):
            is_restart = True
            
    else:
        # Simple flat format (for manual testing)
        page_id = payload.get('page_id')
        firm_name = payload.get('firm_name')
        website = payload.get('website')
        is_restart = False
    
    if not page_id:
        return jsonify({'error': 'Missing page_id'}), 400
    
    # If website empty, try to fetch from Notion page directly
    if not website:
        page = get_notion_page(page_id)
        if page:
            props = page.get('properties', {})
            website = props.get('Website', {}).get('url', '')
            if not firm_name and props.get('Firm Name', {}).get('title'):
                title_arr = props['Firm Name']['title']
                if title_arr:
                    firm_name = title_arr[0].get('plain_text', '')
    
    domain = extract_domain(website)
    
    if not domain:
        logger.warning(f"No domain found for firm {firm_name}")
        return jsonify({'error': 'No website/domain provided', 'firm': firm_name}), 400
    
    clay_data = {
        'page_id': page_id,
        'firm_name': firm_name,
        'domain': domain,
        'website': website
    }
    
    success = send_to_clay_firm_table(clay_data)
    
    if success:
        # Update status and uncheck restart if needed
        updates = {
            'Research Status': {'select': {'name': 'Researching'}}
        }
        if is_restart:
            updates['Restart Enrichment'] = {'checkbox': False}
        
        update_notion_page(page_id, updates)
        return jsonify({'status': 'sent_to_clay', 'firm': firm_name, 'restart': is_restart})
    else:
        return jsonify({'error': 'Failed to send to Clay'}), 500

@app.route('/webhook/enrich-person', methods=['POST'])
def handle_enrich_person():
    data = request.json
    logger.info(f"Received person enrichment request: {data}")
    page_id = data.get('page_id')
    full_name = data.get('full_name')
    company_domain = data.get('company_domain')
    company_name = data.get('company_name')
    linkedin_url = data.get('linkedin_url')
    if not page_id or not full_name:
        return jsonify({'error': 'Missing page_id or full_name'}), 400
    clay_data = {
        'page_id': page_id,
        'full_name': full_name,
        'company_domain': company_domain,
        'company_name': company_name,
        'linkedin_url': linkedin_url
    }
    success = send_to_clay_person_table(clay_data)
    if success:
        update_notion_page(page_id, {
            'Status': {'select': {'name': 'Enriching'}}
        })
        return jsonify({'status': 'sent_to_clay', 'person': full_name})
    else:
        return jsonify({'error': 'Failed to send to Clay'}), 500


@app.route('/webhook/clay/firm-enriched', methods=['POST'])
def handle_clay_firm_enriched():
    data = request.json
    logger.info(f"Received enriched firm data from Clay: {data}")
    notion_page_id = data.get('notion_page_id')
    if not notion_page_id:
        return jsonify({'error': 'Missing notion_page_id'}), 400
    firm_updates = {}
    if data.get('company_linkedin_url'):
        firm_updates['LinkedIn Company URL'] = {'url': data['company_linkedin_url']}
    if data.get('description'):
        description = data['description'][:2000]
        firm_updates['Firm Overview'] = {'rich_text': [{'text': {'content': description}}]}
    if data.get('headquarters'):
        firm_updates['Location / Headquarters Location'] = {
            'rich_text': [{'text': {'content': data['headquarters']}}]
        }
    people = data.get('people', [])
    if people:
        firm_updates['Contacts Identified'] = {'number': len(people)}
    firm_updates['Research Status'] = {'select': {'name': 'Qualified'}}
    if firm_updates:
        update_notion_page(notion_page_id, firm_updates)
    for person in people:
        prospect_properties = {
            'Name': {'title': [{'text': {'content': person.get('name', 'Unknown')}}]},
            'Company': {'rich_text': [{'text': {'content': data.get('firm_name', '')}}]},
            'Title/Role': {'rich_text': [{'text': {'content': person.get('title', '')}}]},
            'Status': {'select': {'name': 'New'}}
        }
        if person.get('linkedin_url'):
            prospect_properties['LinkedIn URL'] = {'url': person['linkedin_url']}
        created = create_notion_page(PROSPECTS_DB_ID, prospect_properties)
        if created:
            logger.info(f"Created prospect: {person.get('name')}")
    return jsonify({
        'status': 'success',
        'firm_updated': notion_page_id,
        'prospects_created': len(people)
    })


@app.route('/webhook/clay/person-enriched', methods=['POST'])
def handle_clay_person_enriched():
    data = request.json
    logger.info(f"Received enriched person data from Clay: {data}")
    
    prospect_properties = {
        'Name': {'title': [{'text': {'content': data.get('full_name', 'Unknown')}}]},
        'Company': {'rich_text': [{'text': {'content': data.get('company_name', '')}}]},
        'Status': {'select': {'name': 'Qualified' if data.get('email') else 'New'}}
    }
    
    if data.get('email'):
        prospect_properties['Email'] = {'email': data['email']}
    
    if data.get('linkedin_url'):
        prospect_properties['LinkedIn URL'] = {'url': data['linkedin_url']}
    
    if data.get('title'):
        prospect_properties['Title/Role'] = {'rich_text': [{'text': {'content': data['title']}}]}
    
    created = create_notion_page(PROSPECTS_DB_ID, prospect_properties)
    
    if created:
        logger.info(f"Created prospect: {data.get('full_name')}")
        return jsonify({
            'status': 'success',
            'prospect_created': data.get('full_name'),
            'email_found': bool(data.get('email'))
        })
    else:
        return jsonify({'error': 'Failed to create prospect'}), 500


@app.route('/test/enrich-firm/<page_id>', methods=['GET'])
def test_enrich_firm(page_id):
    page = get_notion_page(page_id)
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    props = page.get('properties', {})
    firm_name = ''
    if props.get('Firm Name', {}).get('title'):
        firm_name = props['Firm Name']['title'][0]['text']['content']
    website = props.get('Website', {}).get('url', '')
    domain = extract_domain(website)
    clay_data = {
        'page_id': page_id,
        'firm_name': firm_name,
        'domain': domain,
        'website': website
    }
    success = send_to_clay_firm_table(clay_data)
    return jsonify({
        'status': 'sent' if success else 'failed',
        'data': clay_data
    })


@app.route('/test/enrich-person/<page_id>', methods=['GET'])
def test_enrich_person(page_id):
    page = get_notion_page(page_id)
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    props = page.get('properties', {})
    full_name = ''
    if props.get('Name', {}).get('title'):
        full_name = props['Name']['title'][0]['text']['content']
    company_name = ''
    if props.get('Company', {}).get('rich_text'):
        company_name = props['Company']['rich_text'][0]['text']['content']
    linkedin_url = props.get('LinkedIn URL', {}).get('url', '')
    clay_data = {
        'page_id': page_id,
        'full_name': full_name,
        'company_name': company_name,
        'company_domain': '',
        'linkedin_url': linkedin_url
    }
    success = send_to_clay_person_table(clay_data)
    return jsonify({
        'status': 'sent' if success else 'failed',
        'data': clay_data
    })


@app.route('/webhook/clay/firm-score', methods=['POST'])
def handle_firm_scoring():
    """
    Receives firm data from Clay, scores against all 6 Plinian clients using Claude,
    and updates Notion with fit scores and qualification notes.
    """
    data = request.json or {}
    
    notion_page_id = data.get('notion_page_id')
    firm_name = data.get('firm_name')
    website = data.get('website')
    
    # Get research from query param OR body
    firm_research = request.args.get('research', '') or data.get('firm_research', '')
    
    # Sanitize
    if firm_research:
        firm_research = str(firm_research).replace('\n', ' ').replace('\r', ' ')[:5000]
    
    logger.info(f"Received firm for scoring: {firm_name}, research length: {len(firm_research)}")
    
    # =========================================================================
    # COMPREHENSIVE SCORING PROMPT - Based on Plinian Training Frameworks
    # =========================================================================
    scoring_prompt = f"""You are an expert institutional capital raising advisor for Plinian Strategies. 
Analyze this allocator firm and score their fit for each of our 6 clients.

FIRM INFORMATION:
- Name: {firm_name}
- Website: {website}
- Research: {firm_research}

=============================================================================
SCORING INSTRUCTIONS
=============================================================================
For each client, evaluate the firm against the specific criteria below.
- "Strong" = Multiple high-fit signals present, no disqualifying factors, clear alignment
- "Moderate" = Some alignment, no hard disqualifiers, but missing key signals or unconfirmed
- "Weak" = Minimal alignment, potential mismatches, or only tangential fit
- "N/A" = Clear disqualifier present OR completely wrong asset class/mandate

Be rigorous. Most firms should NOT be "Strong" for most clients.
If research is insufficient to evaluate, default to "Weak" or "N/A" with explanation.

=============================================================================
CLIENT 1: STONERIVER - Fund III
=============================================================================
PRODUCT: $200M Multifamily Real Estate Fund, Southeast US, Value-Add + Development (up to 30%)
STRUCTURE: Vertically integrated (in-house construction + property management)
CHECK SIZE: $5M-$25M

TARGET TIERS:
1. "Operator-Focused" Allocators: MFOs, SFOs, specialized RIAs seeking "vertically integrated" or "operator-led" deals, Sunbelt focus, prefer funds <$500M
2. Regional Institutions: Healthcare Foundations, Hospitals, University Endowments, Community Foundations with RE/Alternatives bucket
3. Wealth Aggregators: CIOs of large RIAs/Wealth Platforms buying on behalf of multiple HNW clients
4. OCIO/Consultants: Senior RE leadership with defined manager research teams

HIGH-FIT SIGNALS: "Vertically integrated", "Operator", "Sunbelt", "Southeast", "Migration", "Value-Add", "Opportunistic", "Middle Market", "Real Assets", multifamily/apartment investments

DISQUALIFY IF: Retail without FO structure, Core-only/Stabilized-only mandate (can't tolerate 30% development), Gateway purist (NYC/SF/LA only), Distressed debt/credit hunter (equity strategy), Internal RE org doing direct sourcing, Check size >$50M

=============================================================================
CLIENT 2: ASHTON GRAY - AGIF
=============================================================================
PRODUCT: Evergreen fund of STABILIZED healthcare-anchored retail real estate
STRUCTURE: 31 properties, 100% occupied, ~10yr WALT, 28% GP co-invest, >7% monthly distributions
LIQUIDITY: 2-year lockup, 10% annual NAV redemption, K-1

CRITICAL: AGIF is NOT development. It is stabilized income with healthcare tenancy.

TARGET TIERS:
1. Real Estate Income/Core+ Allocators: Endowments, healthcare foundations, hospitals, insurance, pensions with income mandates
2. Family Offices seeking income, tax efficiency, K-1, healthcare tenancy
3. Wealth Platforms/RIAs offering income alternatives
4. OCIOs advising on income/stable RE

HIGH-FIT SIGNALS: "Core/Core+", "Income-focused", "Yield", "Healthcare real estate", "Medical office", "Long-term leases", "WALT", "NNN", "Sunbelt", "Evergreen", "Durable income", "Defensive tenancy"

DISQUALIFY IF: Gateway-only retail mandates (AGIF is Sunbelt), Development-only, Debt/credit-only, Industrial/multifamily-only, Retail individuals, <2yr liquidity needs, Excludes retail/healthcare retail, Value-add/distressed seekers, Internal RE groups

=============================================================================
CLIENT 3: WILLOW CREST - Inflation Structural Alpha
=============================================================================
PRODUCT: Structural alpha, inflation-linked strategy exploiting long-duration economic dislocations
STRUCTURE: Highly proprietary IP requiring NDA, 10-20+ year horizon, potential multi-X returns
CHECK SIZE: $50M-$200M+

CRITICAL: NOT traditional real assets. Confidential macro-driven structural trade.

TARGET TIERS:
1. Endowments & Foundations: Inflation-protection, real asset, diversifying buckets; long-duration comfort
2. SWFs & Public Pensions: Large pools of long-duration capital, specialist inflation/real asset teams
3. Large FOs/MFOs (Institutional-Grade Only): Inflation resilience, asymmetric opportunities, CIO with macro background

HIGH-FIT SIGNALS: "Inflation-linked", "Inflation protection", "Inflation-sensitive", "Real Return", "Real Assets", "Non-correlated", "Diversifying", "Long-duration capital", "Patient capital", "Opportunistic", "Special Situations", "Structural Themes", prior timber/royalties/insurance-linked allocations

DISQUALIFY IF: Retail individuals, Equity-only/60-40 traditionalists, Crypto-only allocators, Consultants without discretion, Won't sign NDAs early, Short-duration/high-liquidity needs, <$50M check capacity

=============================================================================
CLIENT 4: ICW HOLDINGS - Strategic Equities
=============================================================================
PRODUCT: Global macro-driven, balanced, long-only equity strategy with 4 sub-portfolios
STRUCTURE: ~11.7% returns, ~7.8% vol, monthly liquidity, 1%/10% fees
PEDIGREE: Founded by Mark Dinner, former senior Bridgewater leader (built algorithms for Pure Alpha, All Weather)

CRITICAL: PUBLIC EQUITIES, long-only, no leverage. NOT a hedge fund.

TARGET TIERS:
1. Institutions with Global Equity Mandates: Endowments, foundations, healthcare systems, sovereigns, pensions, OCIOs
2. MFOs/SFOs valuing equity compounding with macro discipline
3. RIAs/Wealth Platforms seeking differentiated long-only exposure
4. OCIOs/Consultants running global equity searches

HIGH-FIT SIGNALS: "Global equity", "ACWI", "Macro-aware", "Regime-aware", "Risk-managed equities", "Downside mitigation", "Inflation resilience" (equity context), "Quality", "Cash flow focus", Bridgewater familiarity/respect

DISQUALIFY IF: Private-only allocators, Hedge fund-only mandates (want leverage/shorting), Single-factor/single-region only, Leverage-seeking, Retail/unstaffed FOs, Explicitly avoid macro frameworks, Index-only buyers, Daily liquidity required

=============================================================================
CLIENT 5: HIGHMOUNT - Sports & Entertainment Growth PE
=============================================================================
PRODUCT: Growth PE fund focused on sports & entertainment, tech-enabled media, creator economy
STRUCTURE: Pre-launch, targeting $1B+ raise
CHECK SIZE: $50M-$250M
PEDIGREE: Nine-figure Dude Perfect investment (April 2024)

CRITICAL: GROWTH PRIVATE EQUITY, pre-launch. NOT real assets, NOT income.

TARGET TIERS:
1. Large Institutions with PE Growth Mandates: SWFs, large pensions, insurance, endowments with PE programs
2. Foundations/Strategic Investors with growth capital or entertainment interest
3. Growth-Focused FOs/MFOs willing to back pre-launch funds
4. OCIOs/Consultants with PE growth mandates

HIGH-FIT SIGNALS: "Private equity growth", "Growth equity", "Sports & entertainment", "Media", "Creator economy", "Live experiences", "Tech-enabled media", "Middle market PE", "Pre-fund commitment", "Anchor investor", prior sports/media investments

DISQUALIFY IF: Retail individuals, Core/income-only mandates (no growth), Traditional buyout only, <5yr horizon, Avoid sports/entertainment/media, Passive/index only, Require full track record (this is pre-launch), Consultants without discretion

=============================================================================
CLIENT 6: CO-INVEST PLATFORM
=============================================================================
PRODUCT: Variable deal flow - direct minority equity, structured equity, JVs, club deals across sectors
STRUCTURE: Deal-by-deal, not a fund
CHECK SIZE: $5M-$200M+ depending on deal

CRITICAL: About CO-INVEST CAPABILITY and MANDATE FLEXIBILITY.

TARGET TIERS:
1. Direct Co-Invest Specialists: SWFs, large pensions, mega-endowments, PE platforms with co-invest teams
2. FOs/MFOs with Direct Investing capability: $1B+ with deal teams, evergreen capital
3. PE FoFs with co-invest arms
4. OCIOs deploying co-invest for E&F clients

HIGH-FIT SIGNALS: "Direct co-investments", "Co-invest program", "Opportunistic private", "Direct deals", "GP-adjacent", "Flexible check sizes", "Fast-track diligence", "JVs", "Structured equity", evidence of prior direct deals outside fund commitments

DISQUALIFY IF: Retail/unstaffed FOs, Fund-only policy (no co-invest capability), Public markets only, Core RE or index only, Rigid IC can't do off-cycle deals, <$5M minimum capacity, Won't do quick NDAs, Require GP sponsor to participate, Daily liquidity required

=============================================================================
OUTPUT FORMAT (Return ONLY valid JSON, no markdown fences)
=============================================================================
{{
    "stoneriver_fit": "Strong/Moderate/Weak/N/A",
    "stoneriver_rationale": "2-3 sentence explanation citing specific evidence from research",
    "ashtongray_fit": "Strong/Moderate/Weak/N/A",
    "ashtongray_rationale": "2-3 sentence explanation citing specific evidence from research",
    "willowcrest_fit": "Strong/Moderate/Weak/N/A",
    "willowcrest_rationale": "2-3 sentence explanation citing specific evidence from research",
    "icw_fit": "Strong/Moderate/Weak/N/A",
    "icw_rationale": "2-3 sentence explanation citing specific evidence from research",
    "highmount_fit": "Strong/Moderate/Weak/N/A",
    "highmount_rationale": "2-3 sentence explanation citing specific evidence from research",
    "coinvest_fit": "Strong/Moderate/Weak/N/A",
    "coinvest_rationale": "2-3 sentence explanation citing specific evidence from research",
    "best_match": "Client name with strongest fit, or 'None' if all N/A",
    "overall_notes": "1-2 sentence summary of allocator profile and where they fit in Plinian's universe"
}}"""

    import anthropic
    
    try:
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
        
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[
                {"role": "user", "content": scoring_prompt}
            ]
        )
        
        response_text = message.content[0].text
        logger.info(f"Claude scoring response: {response_text[:500]}...")
        
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
        
        # Update Notion with scores
        notion_updates = {
            'StoneRiver Fit': {'select': {'name': normalize_fit(scores.get('stoneriver_fit'))}},
            'Ashton Gray Fit': {'select': {'name': normalize_fit(scores.get('ashtongray_fit'))}},
            'Willow Crest Fit': {'select': {'name': normalize_fit(scores.get('willowcrest_fit'))}},
            'ICW Fit': {'select': {'name': normalize_fit(scores.get('icw_fit'))}},
            'Highmount Fit': {'select': {'name': normalize_fit(scores.get('highmount_fit'))}},
            'Co-Invests Fit': {'select': {'name': normalize_fit(scores.get('coinvest_fit'))}},
            'Research Status': {'select': {'name': 'Qualified'}}
        }
        
        # Build qualification notes with rationales
        rationale = f"""Best Match: {scores.get('best_match', 'TBD')}

STONERIVER: {scores.get('stoneriver_rationale', '')}

ASHTON GRAY: {scores.get('ashtongray_rationale', '')}

WILLOW CREST: {scores.get('willowcrest_rationale', '')}

ICW: {scores.get('icw_rationale', '')}

HIGHMOUNT: {scores.get('highmount_rationale', '')}

CO-INVEST: {scores.get('coinvest_rationale', '')}

---
{scores.get('overall_notes', '')}"""
        
        notion_updates['Qualification Notes'] = {
            'rich_text': [{'text': {'content': rationale[:2000]}}]
        }
        
        update_result = update_notion_page(notion_page_id, notion_updates)
        
        if update_result:
            logger.info(f"Successfully updated Notion with scores for {firm_name}")
        else:
            logger.error(f"Failed to update Notion for {firm_name}")
        
        return jsonify({
            'status': 'success',
            'firm': firm_name,
            'scores': scores
        })
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing failed: {str(e)}")
        logger.error(f"Raw response: {response_text}")
        return jsonify({'error': f'JSON parsing failed: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"Claude scoring failed: {str(e)}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
