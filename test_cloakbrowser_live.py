#!/usr/bin/env python3
"""Test CloakBrowser live connection."""
import sys
from pathlib import Path

# Add vendor to path
sys.path.insert(0, str(Path("vendor/CloakBrowser")))

try:
    from cloakbrowser import launch
    
    print("Launching CloakBrowser...")
    browser = launch(headless=False)
    print(f"✓ Browser launched")
    
    page = browser.new_page()
    print("✓ New page created")
    
    page.goto("https://example.com")
    print(f"✓ Navigated to: {page.url}")
    
    title = page.title()
    print(f"✓ Page title: {title}")
    
    # Get some content
    h1 = page.query_selector("h1")
    if h1:
        text = h1.text_content()
        print(f"✓ Found H1: {text}")
    
    browser.close()
    print("✓ Browser closed")
    print("\n✅ CloakBrowser is working!")
    
except ImportError as e:
    print(f"❌ CloakBrowser not installed: {e}")
    print("\nInstall with: pip install cloakbrowser")
    sys.exit(1)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
