"""
Plinian Strategies - LLM-Powered Outreach Generation Module
============================================================
Integrates Claude API with client training frameworks to generate
personalized, institutionally-appropriate outreach emails.

Usage:
    from plinian_outreach_llm import generate_outreach_with_llm
    
    result = generate_outreach_with_llm(
        firm_name="Example Family Office",
        website="https://example.com",
        plinian_fit=["StoneRiver", "Ashton Gray"],
        notes="CIO has real estate background...",
        raw_page=notion_page_object  # Optional: full Notion page
    )
    
    # result = {
    #     "subject": "...",
    #     "body": "...",
    #     "primary_client": "StoneRiver",
    #     "reasoning": "..."
    # }

Requirements:
    pip install anthropic python-dotenv

Environment:
    ANTHROPIC_API_KEY=your_api_key
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

try:
    import anthropic
except ImportError:
    raise ImportError("anthropic package required. Install with: pip install anthropic")

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# CLIENT FRAMEWORK DEFINITIONS
# =============================================================================

class PlinianClient(Enum):
    """Plinian's active client campaigns."""
    STONERIVER = "StoneRiver"
    ASHTON_GRAY = "Ashton Gray"
    WILLOW_CREST = "Willow Crest"
    ICW = "ICW"
    HIGHMOUNT = "Highmount"
    CO_INVEST = "Co-Invest"


# Condensed training frameworks for system prompt
CLIENT_FRAMEWORKS = {
    "StoneRiver": {
        "full_name": "StoneRiver Investment Fund III",
        "asset_class": "Class A Multifamily Real Estate (Apartments)",
        "geography": "Southeast US / Sunbelt (AL, FL, GA, KY, NC, SC, TN, TX, VA)",
        "strategy": "Value-Add, Core-Plus, Ground-Up Development (max 30%)",
        "fund_size": "$200M-$300M target",
        "ticket_size": "$5M-$25M",
        "key_differentiator": "Vertically integrated manager with in-house construction and property management",
        "ideal_allocators": [
            "Multi-Family Offices seeking operator-led deals",
            "Single Family Offices with Sunbelt focus",
            "Healthcare Foundations with real estate mandates",
            "University Endowments with alternatives buckets",
            "RIAs/Wealth Platforms aggregating institutional tickets"
        ],
        "high_fit_signals": [
            "Vertically integrated", "Operator-focused",
            "Sunbelt/Southeast/Migration themes", "Value-Add appetite",
            "Middle Market preference", "Real Assets allocation"
        ],
        "disqualifiers": [
            "Core-only mandates", "Gateway cities only (NYC/SF/LA)",
            "Debt/credit only", "Internal RE acquisition teams"
        ],
        "hook_themes": [
            "Demographic tailwinds in the Sunbelt",
            "Operator alignment and vertical integration",
            "Middle-market fund where LP relationships matter"
        ]
    },
    
    "Ashton Gray": {
        "full_name": "Ashton Gray Investment Fund (AGIF)",
        "asset_class": "Stabilized Healthcare-Anchored Retail Real Estate",
        "geography": "Sunbelt markets (Texas-focused)",
        "strategy": "Evergreen income fund, NOT development",
        "fund_size": "$105M appraised value current portfolio",
        "structure": "Evergreen, 28% GP co-invest, monthly distributions (>7% for 26 months)",
        "key_stats": "31 properties, 72 tenants, 100% occupied, ~10yr WALT, ~$30/SF rent",
        "ticket_size": "Flexible, institutional focus",
        "key_differentiator": "Stabilized, recession-resistant healthcare tenancy (dental, urgent care, PT, vet)",
        "ideal_allocators": [
            "University endowments seeking income",
            "Healthcare foundations (natural alignment)",
            "Hospitals with investment arms",
            "Insurance companies with income mandates",
            "Family Offices seeking tax-efficient K-1 distributions",
            "RIAs building income alternatives sleeves"
        ],
        "high_fit_signals": [
            "Core/Core+ real estate", "Income-focused/Yield",
            "Healthcare real estate/Medical office", "Long-term leases",
            "Sunbelt exposure", "Defensive tenancy"
        ],
        "disqualifiers": [
            "Development-only", "Industrial-only or multifamily-only",
            "Short liquidity needs (<2 years)", "Retail aversion"
        ],
        "hook_themes": [
            "Healthcare retail is sticky and e-commerce-proof",
            "Monthly distributions with strong WALT",
            "Opportunistic returns with core+ risk profile"
        ]
    },
    
    "Willow Crest": {
        "full_name": "Willow Crest Asset Management - Inflation Structured Product",
        "asset_class": "Structural alpha, inflation-linked strategy",
        "strategy": "Long-duration (10-20yr) macro-structural trades exploiting regulatory/demographic bottlenecks",
        "return_profile": "Asymmetric, up to ~18x MOIC historically",
        "ticket_size": "$50M-$200M+",
        "key_differentiator": "Highly proprietary IP requiring NDA; non-cyclical, non-market-correlated outcomes",
        "ideal_allocators": [
            "Endowments & Foundations with inflation/real asset buckets",
            "Sovereign Wealth Funds with long-duration capital",
            "Large Public Pensions with specialist teams",
            "Institutional Family Offices comfortable with non-traditional exposures"
        ],
        "high_fit_signals": [
            "Inflation-linked/protection mandates", "Real Assets adjacent",
            "Non-correlated/diversifying streams", "Long-duration/patient capital",
            "Opportunistic/special situations", "Regulatory/structural themes"
        ],
        "disqualifiers": [
            "Equity-only/60-40 traditionalists", "Unwilling to sign NDAs early",
            "Require full transparency pre-NDA", "Retail individuals"
        ],
        "hook_themes": [
            "Inflation protection with asymmetric upside",
            "Diversifying return stream uncorrelated to markets",
            "Structural alpha from regulatory/demographic dislocations"
        ]
    },
    
    "ICW": {
        "full_name": "ICW Holdings - Strategic Equities Strategy",
        "asset_class": "Global, macro-informed, long-only equities",
        "strategy": "4 sub-portfolio balanced approach across regimes",
        "sub_portfolios": [
            "High Cash Flow Companies (20-40%)",
            "Current Winners (20-40%)",
            "Rising Rate Beneficiaries (15-30%)",
            "Rising Inflation Beneficiaries (15-30%)"
        ],
        "pedigree": "Founded by Mark Dinner, former Bridgewater senior leader (2008-2020)",
        "performance": "~11.7% annualized, ~7.8% vol since inception",
        "structure": "LP master/feeder, monthly liquidity, 1% mgmt + 10% perf",
        "key_differentiator": "Bridgewater DNA + macro regime framework for equities",
        "ideal_allocators": [
            "Endowments & Foundations with global equity mandates",
            "Corporate/public pensions seeking risk-managed equities",
            "Family Offices valuing macro discipline",
            "OCIOs seeking differentiated equity exposure"
        ],
        "high_fit_signals": [
            "Global equity mandate", "Macro-aware/regime-aware",
            "Risk-managed equities", "Inflation resilience",
            "Downside mitigation focus", "Quality/cash flow orientation"
        ],
        "disqualifiers": [
            "Private markets only", "Hedge fund (short/leverage) only",
            "Index-only/fee-minimizing", "Daily liquidity required"
        ],
        "hook_themes": [
            "Bridgewater pedigree applied to long-only equities",
            "Regime-balanced approach for all economic environments",
            "Demonstrated downside protection (2022, 2025 stress)"
        ]
    },
    
    "Highmount": {
        "full_name": "Highmount Capital - Sports & Entertainment Growth Fund",
        "asset_class": "Growth-oriented private equity",
        "focus": "Sports & entertainment, creator economy, media, live experiences",
        "status": "Pre-launch fund",
        "ticket_size": "$50M-$250M",
        "target_fund": "$1B+",
        "notable_deal": "Nine-figure investment in Dude Perfect (April 2024)",
        "key_differentiator": "Sector-specialist PE in sports/entertainment with operational value-add",
        "ideal_allocators": [
            "Sovereign Wealth Funds with PE growth mandates",
            "Large public pensions with alternatives allocation",
            "University endowments with large PE programs",
            "Growth-focused Family Offices with sports/media interest",
            "Strategic investors (media conglomerates)"
        ],
        "high_fit_signals": [
            "Private equity growth", "Sports & entertainment interest",
            "Media/creator economy", "Middle market PE",
            "Pre-fund/anchor investor appetite"
        ],
        "disqualifiers": [
            "Core real estate income only", "Short-term liquidity (<3 years)",
            "Passive/index only", "No interest in thematic verticals"
        ],
        "hook_themes": [
            "Sports & entertainment as an institutional asset class",
            "Creator economy and live experiences growth",
            "Demonstrated execution with Dude Perfect investment"
        ]
    },
    
    "Co-Invest": {
        "full_name": "Plinian Private Co-Invest Platform",
        "asset_class": "Variable - PE, growth, credit, real assets, infrastructure",
        "strategy": "Off-market, direct co-investments across sectors",
        "ticket_size": "$5M-$200M+ (deal dependent)",
        "key_differentiator": "Curated, non-intermediated deal flow with fast execution",
        "deal_types": [
            "Direct minority equity", "Structured/preferred equity",
            "Club deals", "Follow-on rounds", "Secondary blocks"
        ],
        "ideal_allocators": [
            "Sovereign Wealth Funds with co-invest teams",
            "Large pensions with direct investing capability",
            "$1B+ Family Offices with deal teams",
            "PE Funds-of-Funds with co-invest arms"
        ],
        "high_fit_signals": [
            "Direct co-investments", "Opportunistic private investing",
            "Flexible check sizes", "Fast-track diligence",
            "Cross-sector mandate"
        ],
        "disqualifiers": [
            "Only invest via funds", "Needs lead sponsor always",
            "Long approval cycles", "Geo-restricted mandates"
        ],
        "hook_themes": [
            "Proprietary deal flow outside traditional channels",
            "Flexibility to participate in unique situations",
            "Direct access without fund overhead"
        ]
    }
}


# =============================================================================
# SYSTEM PROMPT BUILDER
# =============================================================================

def build_system_prompt() -> str:
    """Construct the system prompt with all client frameworks."""
    
    frameworks_text = ""
    for client_key, framework in CLIENT_FRAMEWORKS.items():
        frameworks_text += f"""
### {framework['full_name']} ({client_key})
- **Asset Class:** {framework['asset_class']}
- **Strategy:** {framework.get('strategy', 'N/A')}
- **Geography:** {framework.get('geography', 'Global')}
- **Ticket Size:** {framework.get('ticket_size', 'Variable')}
- **Key Differentiator:** {framework['key_differentiator']}
- **Ideal Allocators:** {', '.join(framework['ideal_allocators'][:3])}...
- **High-Fit Signals:** {', '.join(framework['high_fit_signals'][:4])}
- **Disqualifiers:** {', '.join(framework['disqualifiers'][:3])}
- **Hook Themes:** {'; '.join(framework['hook_themes'])}

"""

    return f"""You are ghostwriting emails AS Bill Sweeney, founder of Plinian Strategies. Write in FIRST PERSON as Bill himself — not as an assistant, not on his behalf, but AS him directly.

## About Bill & Plinian Strategies
Bill Sweeney is the founder of Plinian Strategies, a boutique capital-raising and strategic advisory firm. The most compelling part of Bill's background was his experience at Bridgewater. Plinian bridges emerging asset managers with institutional allocators, providing fractional representation and global investor access for GPs, while offering curated opportunity sourcing for LPs.

## Bill's Voice & Style (Write AS Bill)
- First person: "I'm reaching out..." / "I came across..." / "I'd love to..."
- Warm but professional — never salesy or pushy
- Concise and respectful of the reader's time
- Shows genuine interest in the allocator's mandate
- References specific details that demonstrate research
- Positions opportunities as potentially relevant, not as pitches
- Always offers an easy path to learn more (brief call, materials)
- Signs off as Bill personally

## CRITICAL: Email Voice
- CORRECT: "I'm Bill Sweeney, founder of Plinian Strategies..."
- CORRECT: "I've made it my goal to match up differentiated GPs that are a genuinely strong fit for firms like yours..."
- CORRECT: "I'd welcome the chance to connect..."
- WRONG: "I'm reaching out on behalf of Bill..."
- WRONG: "Bill Sweeney asked me to contact you..."
- WRONG: "As Bill's assistant..."

## Active Client Campaigns & Frameworks
{frameworks_text}

## Your Task
Given information about a prospect firm, you will:
1. Analyze their profile to determine which Plinian client(s) are the best fit
2. Select the PRIMARY client to lead with (most relevant to their mandate)
3. Draft a personalized email AS BILL (first person) that:
   - Opens with something specific to their firm/mandate
   - Introduces Bill and Plinian naturally ("By way of introduction, I spent the last 15 years at Bridgewater Associates, managing global institutional relationships. Now I look to...")
   - Positions the primary client opportunity naturally
   - Offers a low-friction next step
   - Keeps total length under 200 words
   - Signs off with Bill's contact info:
     
     Best regards,
     Bill Sweeney
     Plinian Strategies
     bill@plinian.co
     (908) 347-0156

## Output Format
Return a JSON object with:
- "primary_client": The main client to pitch (from: StoneRiver, Ashton Gray, Willow Crest, ICW, Highmount, Co-Invest)
- "secondary_clients": List of other potentially relevant clients (may be empty)
- "subject": Email subject line (brief, professional, not clickbait)
- "body": Full email body (salutation through signature)
- "reasoning": Brief explanation of why this client/approach was chosen

## Important Guidelines
- If the firm is clearly a poor fit for ALL clients, indicate this in reasoning and draft a relationship-building email instead
- Never fabricate details about the prospect — only use what's provided
- Reference their specific characteristics when possible
- For Family Offices, emphasize alignment and access
- For Endowments/Foundations, emphasize mandate fit and institutional quality
- For Pensions, emphasize scale and governance alignment
- For RIAs/OCIOs, emphasize differentiated access for their clients"""


# =============================================================================
# OUTREACH GENERATOR CLASS
# =============================================================================

@dataclass
class OutreachResult:
    """Result from outreach generation."""
    subject: str
    body: str
    primary_client: str
    secondary_clients: List[str]
    reasoning: str
    success: bool
    error: Optional[str] = None


class PlinianOutreachGenerator:
    """Generate personalized outreach using Claude API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the generator.
        
        Args:
            api_key: Anthropic API key. If not provided, reads from ANTHROPIC_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter."
            )
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = "claude-sonnet-4-20250514"  # Using Sonnet for cost efficiency
        self.system_prompt = build_system_prompt()
    
    def _extract_firm_context(
        self,
        firm_name: str,
        website: Optional[str],
        plinian_fit: Optional[List[str]],
        notes: Optional[str],
        raw_page: Optional[Dict[str, Any]]
    ) -> str:
        """Extract relevant context from firm data for the prompt."""
        
        context_parts = [f"**Firm Name:** {firm_name}"]
        
        if website:
            context_parts.append(f"**Website:** {website}")
        
        if plinian_fit:
            context_parts.append(f"**Pre-tagged Best Matches:** {', '.join(plinian_fit)}")
        
        if notes:
            context_parts.append(f"**Research Notes:** {notes}")
        
        # Extract additional context from raw Notion page if available
        if raw_page and "properties" in raw_page:
            props = raw_page["properties"]
            
            # Extract key properties
            property_mappings = {
                "Firm Type": "firm_type",
                "Type": "type",
                "AUM Range": "aum_range",
                "Geographic Focus": "geographic_focus",
                "Primary Office City": "city",
                "Private Markets Experience": "private_markets",
                "Real Estate Allocation": "re_allocation",
                "Alternatives Platform": "alts_platform",
                "Investment Decision Timeline": "timeline",
                "Value-Add Tolerance": "value_add",
                "Qualification Notes": "qual_notes",
                "Key Investment Themes": "themes",
                "Network Angles": "network",
                "Warm Intro Potential": "warm_intro"
            }
            
            extracted = {}
            for prop_name, key in property_mappings.items():
                if prop_name in props:
                    prop = props[prop_name]
                    value = self._extract_property_value(prop)
                    if value:
                        extracted[key] = value
            
            # Add extracted properties to context
            if extracted.get("firm_type") or extracted.get("type"):
                context_parts.append(f"**Firm Type:** {extracted.get('firm_type') or extracted.get('type')}")
            
            if extracted.get("aum_range"):
                context_parts.append(f"**AUM Range:** {extracted['aum_range']}")
            
            if extracted.get("geographic_focus"):
                context_parts.append(f"**Geographic Focus:** {extracted['geographic_focus']}")
            
            if extracted.get("city"):
                context_parts.append(f"**Location:** {extracted['city']}")
            
            if extracted.get("private_markets"):
                context_parts.append(f"**Private Markets Experience:** {extracted['private_markets']}")
            
            if extracted.get("re_allocation"):
                context_parts.append(f"**Real Estate Allocation:** {extracted['re_allocation']}")
            
            if extracted.get("alts_platform"):
                context_parts.append(f"**Alternatives Platform:** {extracted['alts_platform']}")
            
            if extracted.get("value_add"):
                context_parts.append(f"**Value-Add Tolerance:** {extracted['value_add']}")
            
            if extracted.get("themes"):
                context_parts.append(f"**Key Investment Themes:** {extracted['themes']}")
            
            if extracted.get("qual_notes"):
                context_parts.append(f"**Qualification Notes:** {extracted['qual_notes']}")
            
            if extracted.get("network"):
                context_parts.append(f"**Network Angles:** {extracted['network']}")
            
            # Extract fit scores
            fit_scores = []
            for client in ["StoneRiver", "Ashton Gray", "Willow Crest", "ICW", "Highmount", "Co-Invests"]:
                fit_prop = f"{client} Fit"
                if fit_prop in props:
                    fit_value = self._extract_property_value(props[fit_prop])
                    if fit_value and fit_value != "N/A":
                        fit_scores.append(f"{client}: {fit_value}")
            
            if fit_scores:
                context_parts.append(f"**Fit Scores:** {', '.join(fit_scores)}")
        
        return "\n".join(context_parts)
    
    def _extract_property_value(self, prop: Dict[str, Any]) -> Optional[str]:
        """Extract value from a Notion property object."""
        prop_type = prop.get("type")
        
        if prop_type == "title":
            titles = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in titles) if titles else None
        
        elif prop_type == "rich_text":
            texts = prop.get("rich_text", [])
            return "".join(t.get("plain_text", "") for t in texts) if texts else None
        
        elif prop_type == "select":
            select = prop.get("select")
            return select.get("name") if select else None
        
        elif prop_type == "multi_select":
            options = prop.get("multi_select", [])
            return ", ".join(o.get("name", "") for o in options) if options else None
        
        elif prop_type == "url":
            return prop.get("url")
        
        elif prop_type == "email":
            return prop.get("email")
        
        elif prop_type == "number":
            return str(prop.get("number")) if prop.get("number") is not None else None
        
        elif prop_type == "date":
            date = prop.get("date")
            return date.get("start") if date else None
        
        return None
    
    def generate(
        self,
        firm_name: str,
        website: Optional[str] = None,
        plinian_fit: Optional[List[str]] = None,
        notes: Optional[str] = None,
        raw_page: Optional[Dict[str, Any]] = None,
        contact_name: Optional[str] = None,
        contact_title: Optional[str] = None
    ) -> OutreachResult:
        """
        Generate personalized outreach for a firm.
        
        Args:
            firm_name: Name of the prospect firm
            website: Firm website URL
            plinian_fit: List of pre-tagged best match clients
            notes: Research notes about the firm
            raw_page: Full Notion page object with all properties
            contact_name: Optional - specific contact to address
            contact_title: Optional - contact's title
            
        Returns:
            OutreachResult with subject, body, and metadata
        """
        try:
            # Build context from firm data
            firm_context = self._extract_firm_context(
                firm_name=firm_name,
                website=website,
                plinian_fit=plinian_fit,
                notes=notes,
                raw_page=raw_page
            )
            
            # Add contact info if available
            if contact_name:
                firm_context += f"\n**Contact Name:** {contact_name}"
            if contact_title:
                firm_context += f"\n**Contact Title:** {contact_title}"
            
            # Build the user message
            user_message = f"""Please generate a personalized outreach email for the following prospect firm:

{firm_context}

Generate the email following Bill's communication style and the guidelines in your instructions. Return your response as a valid JSON object."""

            # Call Claude API
            logger.info(f"Generating outreach for: {firm_name}")
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=self.system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )
            
            # Extract response text
            response_text = response.content[0].text
            
            # Parse JSON from response
            # Handle potential markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]
            
            result_data = json.loads(response_text.strip())
            
            return OutreachResult(
                subject=result_data.get("subject", f"Plinian Strategies - Introduction"),
                body=result_data.get("body", ""),
                primary_client=result_data.get("primary_client", ""),
                secondary_clients=result_data.get("secondary_clients", []),
                reasoning=result_data.get("reasoning", ""),
                success=True
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response was: {response_text[:500]}...")
            return OutreachResult(
                subject="",
                body="",
                primary_client="",
                secondary_clients=[],
                reasoning="",
                success=False,
                error=f"JSON parsing error: {str(e)}"
            )
        
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            return OutreachResult(
                subject="",
                body="",
                primary_client="",
                secondary_clients=[],
                reasoning="",
                success=False,
                error=f"API error: {str(e)}"
            )
        
        except Exception as e:
            logger.error(f"Unexpected error generating outreach: {e}")
            return OutreachResult(
                subject="",
                body="",
                primary_client="",
                secondary_clients=[],
                reasoning="",
                success=False,
                error=str(e)
            )


# =============================================================================
# CONVENIENCE FUNCTION (Drop-in replacement for webhook)
# =============================================================================

# Module-level generator instance (lazy initialization)
_generator: Optional[PlinianOutreachGenerator] = None

def get_generator() -> PlinianOutreachGenerator:
    """Get or create the generator instance."""
    global _generator
    if _generator is None:
        _generator = PlinianOutreachGenerator()
    return _generator


def generate_outreach_with_llm(
    firm_name: str,
    website: Optional[str] = None,
    plinian_fit: Optional[List[str]] = None,
    notes: Optional[str] = None,
    raw_page: Optional[Dict[str, Any]] = None,
    contact_name: Optional[str] = None,
    contact_title: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate personalized outreach using Claude API.
    
    This is the drop-in replacement for the stub function in response_detector.py.
    
    Args:
        firm_name: Name of the prospect firm
        website: Firm website URL  
        plinian_fit: List of pre-tagged best match clients (from Notion multi-select)
        notes: Research notes about the firm
        raw_page: Full Notion page object with all properties
        contact_name: Optional specific contact to address
        contact_title: Optional contact's title
        
    Returns:
        Dict with keys: subject, body, primary_client, reasoning, success, error
    """
    generator = get_generator()
    result = generator.generate(
        firm_name=firm_name,
        website=website,
        plinian_fit=plinian_fit,
        notes=notes,
        raw_page=raw_page,
        contact_name=contact_name,
        contact_title=contact_title
    )
    
    return {
        "subject": result.subject,
        "body": result.body,
        "primary_client": result.primary_client,
        "secondary_clients": result.secondary_clients,
        "reasoning": result.reasoning,
        "success": result.success,
        "error": result.error
    }


# =============================================================================
# CLI TEST HARNESS
# =============================================================================

if __name__ == "__main__":
    """Test the outreach generator with a sample firm."""
    
    # Sample test data
    test_firm = {
        "firm_name": "Coastal Family Office",
        "website": "https://coastalfo.com",
        "plinian_fit": ["StoneRiver", "Ashton Gray"],
        "notes": """
            $800M single family office based in Atlanta. 
            CIO background in commercial real estate. 
            Currently allocating to multifamily and healthcare properties.
            Interested in Southeast managers.
            Met at TEXPERS conference last year.
        """,
        "contact_name": "Sarah Chen",
        "contact_title": "Chief Investment Officer"
    }
    
    print("=" * 60)
    print("PLINIAN OUTREACH LLM - TEST RUN")
    print("=" * 60)
    print(f"\nTest Firm: {test_firm['firm_name']}")
    print(f"Contact: {test_firm.get('contact_name', 'N/A')}")
    print(f"Pre-tagged Fit: {test_firm.get('plinian_fit', [])}")
    print("\n" + "-" * 60)
    
    result = generate_outreach_with_llm(**test_firm)
    
    if result["success"]:
        print(f"\n✅ SUCCESS")
        print(f"\nPrimary Client: {result['primary_client']}")
        print(f"Secondary Clients: {result['secondary_clients']}")
        print(f"\n--- REASONING ---")
        print(result['reasoning'])
        print(f"\n--- SUBJECT ---")
        print(result['subject'])
        print(f"\n--- BODY ---")
        print(result['body'])
    else:
        print(f"\n❌ FAILED: {result['error']}")