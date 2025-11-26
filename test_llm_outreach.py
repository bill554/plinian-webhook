"""
test_llm_outreach.py
====================
Quick test script to verify the LLM outreach module works
before integrating with the webhook.

Usage:
    python test_llm_outreach.py
    
Expects ANTHROPIC_API_KEY in environment or .env file.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Check for API key first
if not os.getenv("ANTHROPIC_API_KEY"):
    print("❌ ERROR: ANTHROPIC_API_KEY not found in environment")
    print("\nSet it in your .env file:")
    print("  ANTHROPIC_API_KEY=sk-ant-api03-xxxxx")
    sys.exit(1)

# Import the module
try:
    from plinian_outreach_llm import generate_outreach_with_llm, PlinianOutreachGenerator
    print("✅ Module imported successfully")
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("\nMake sure plinian_outreach_llm.py is in the same directory")
    sys.exit(1)

# Test cases representing different firm types
TEST_CASES = [
    {
        "name": "Test 1: Family Office with RE focus",
        "data": {
            "firm_name": "Magnolia Family Office",
            "website": "https://magnoliafamilyoffice.com",
            "plinian_fit": ["StoneRiver", "Ashton Gray"],
            "notes": """
                $650M SFO based in Nashville, TN. 
                CIO previously at CBRE. Strong focus on multifamily and retail.
                Looking for operators with skin in the game.
                Prefers Southeast markets.
            """,
            "contact_name": "Michael Roberts",
            "contact_title": "Chief Investment Officer"
        },
        "expected_primary": ["StoneRiver", "Ashton Gray"]
    },
    {
        "name": "Test 2: Endowment with inflation mandate",
        "data": {
            "firm_name": "Midwest University Endowment",
            "plinian_fit": ["Willow Crest", "ICW"],
            "notes": """
                $2.3B university endowment. 
                Recently expanded inflation-protection allocation.
                Looking for uncorrelated return streams.
                10+ year investment horizon.
                Has signed NDAs with proprietary strategies before.
            """,
            "contact_name": "Jennifer Walsh",
            "contact_title": "Director of Real Assets"
        },
        "expected_primary": ["Willow Crest", "ICW"]
    },
    {
        "name": "Test 3: Pension with PE allocation",
        "data": {
            "firm_name": "State Teachers Retirement System",
            "website": "https://strs.gov",
            "plinian_fit": ["Highmount", "Co-Invest"],
            "notes": """
                $45B public pension. 
                15% alternatives allocation including PE growth.
                Interest in media/entertainment sector diversification.
                Can write $75-150M checks for PE funds.
            """,
        },
        "expected_primary": ["Highmount", "Co-Invest"]
    },
    {
        "name": "Test 4: Healthcare foundation (ideal for AGIF)",
        "data": {
            "firm_name": "Regional Health Foundation",
            "plinian_fit": ["Ashton Gray"],
            "notes": """
                $400M healthcare foundation in Dallas.
                Allocates to stabilized real estate for income.
                Board includes healthcare executives.
                Interested in medical office and healthcare retail.
            """,
            "contact_name": "Dr. Amanda Chen",
            "contact_title": "Investment Committee Chair"
        },
        "expected_primary": ["Ashton Gray"]
    }
]


def run_tests():
    """Run all test cases."""
    print("\n" + "=" * 70)
    print("PLINIAN OUTREACH LLM - INTEGRATION TESTS")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    for test in TEST_CASES:
        print(f"\n{'-' * 60}")
        print(f"🧪 {test['name']}")
        print(f"   Firm: {test['data']['firm_name']}")
        print(f"   Expected Primary: {test['expected_primary']}")
        print(f"{'-' * 60}")
        
        try:
            result = generate_outreach_with_llm(**test["data"])
            
            if result["success"]:
                primary = result["primary_client"]
                is_match = primary in test["expected_primary"]
                
                status = "✅ PASS" if is_match else "⚠️ DIFFERENT (but valid)"
                print(f"\n{status}")
                print(f"   Primary Client: {primary}")
                print(f"   Secondary: {result.get('secondary_clients', [])}")
                print(f"\n   SUBJECT: {result['subject']}")
                print(f"\n   REASONING: {result['reasoning'][:200]}...")
                print(f"\n   BODY PREVIEW:")
                print(f"   {result['body'][:300]}...")
                
                passed += 1
            else:
                print(f"\n❌ FAILED: {result['error']}")
                failed += 1
                
        except Exception as e:
            print(f"\n❌ EXCEPTION: {e}")
            failed += 1
    
    # Summary
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(TEST_CASES)} tests")
    print("=" * 70)
    
    if failed == 0:
        print("\n✅ All tests passed! Ready to integrate with webhook.")
    else:
        print("\n⚠️ Some tests failed. Check errors above.")
    
    return failed == 0


def test_single_firm():
    """Interactive single-firm test."""
    print("\n" + "=" * 70)
    print("INTERACTIVE SINGLE-FIRM TEST")
    print("=" * 70)
    
    firm_name = input("\nEnter firm name (or press Enter for default): ").strip()
    if not firm_name:
        firm_name = "Demo Family Office"
    
    notes = input("Enter any notes about the firm (or press Enter to skip): ").strip()
    
    print(f"\n🔄 Generating outreach for: {firm_name}")
    print("-" * 40)
    
    result = generate_outreach_with_llm(
        firm_name=firm_name,
        notes=notes or "General inquiry. No specific mandate information available."
    )
    
    if result["success"]:
        print(f"\n✅ SUCCESS")
        print(f"\nPrimary Client: {result['primary_client']}")
        print(f"Secondary: {result.get('secondary_clients', [])}")
        print(f"\n{'=' * 40}")
        print(f"SUBJECT: {result['subject']}")
        print(f"{'=' * 40}")
        print(result['body'])
        print(f"{'=' * 40}")
        print(f"\nREASONING: {result['reasoning']}")
    else:
        print(f"\n❌ FAILED: {result['error']}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Plinian LLM Outreach")
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run interactive single-firm test"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true", 
        help="Run all automated test cases"
    )
    
    args = parser.parse_args()
    
    if args.interactive:
        test_single_firm()
    elif args.all:
        run_tests()
    else:
        # Default: run all tests
        run_tests()
