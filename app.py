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


scoring_prompt = f"""You are an expert institutional capital raising advisor. Analyze this allocator firm and score their fit for each of our 6 clients.

FIRM INFORMATION:
- Name: {firm_name}
- Website: {website}
- Research: {firm_research}

SCORING PHILOSOPHY:
- Most diversified institutional allocators (pensions, E&Fs, family offices) have broad mandates that include real estate and private equity
- Default to MODERATE fit if they have the relevant asset class allocation, even without specific sub-sector signals
- Upgrade to STRONG if there are explicit positive signals
- Only mark WEAK if there are mismatches or very limited allocations
- Only mark N/A if truly incompatible (e.g., public equity only, no alternatives)

SCORE EACH CLIENT:

1. STONERIVER (Multifamily Real Estate - Southeast US, Value-Add):
   - STRONG if: Value-add appetite, vertically integrated preference, explicit multifamily interest
   - MODERATE if: Has real estate allocation (most diversified allocators do), invests in private RE generally
   - WEAK if: Core-only mandate, gateway cities only, very small RE allocation
   - N/A if: No real estate allocation at all

2. ASHTON GRAY (Healthcare-Anchored Retail Real Estate - Stabilized Income):
   - STRONG if: Real estate interest, income/core+ focus, NNN or retail experience, appropriate size
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
