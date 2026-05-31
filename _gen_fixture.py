"""Generate 100+ node scene graph fixture for NW-036 perspective tests."""
import json
import uuid

nodes = []
edges = []

# Build a realistic e-commerce product page with 100+ nodes
# Categories: header, product-gallery, product-info, reviews, sidebar, footer, overlays

categories = {
    "header": {
        "label_prefix": "Header",
        "count": 12,
        "node_type": "dom",
        "labels": ["nav", "logo", "search-input", "search-btn", "cart-icon", "account-menu",
                    "wishlist-btn", "hamburger-menu", "breadcrumbs", "category-dropdown",
                    "promo-banner", "country-selector"]
    },
    "product-gallery": {
        "label_prefix": "Gallery",
        "count": 15,
        "node_type": "dom",
        "labels": ["main-image", "thumb-1", "thumb-2", "thumb-3", "thumb-4", "thumb-5",
                    "zoom-view", "image-carousel", "video-thumb", "360-view-btn",
                    "share-btn", "fullscreen-btn", "pinch-zone", "badge-sale", "badge-new"]
    },
    "product-info": {
        "label_prefix": "Info",
        "count": 20,
        "node_type": "dom",
        "labels": ["product-title", "rating-stars", "review-count", "price-current", "price-original",
                    "discount-badge", "size-selector", "color-swatch-1", "color-swatch-2", "color-swatch-3",
                    "color-swatch-4", "quantity-input", "add-to-cart-btn", "buy-now-btn", "wishlist-btn2",
                    "compare-btn", "stock-status", "delivery-estimate", "trust-badge", "description-toggle"]
    },
    "reviews": {
        "label_prefix": "Review",
        "count": 25,
        "node_type": "dom",
        "labels": ["review-section-header", "sort-dropdown", "filter-rating-5", "filter-rating-4",
                    "filter-rating-3", "write-review-btn", "review-card-1", "review-card-2",
                    "review-card-3", "review-card-4", "review-card-5", "review-card-6",
                    "review-card-7", "review-card-8", "review-card-9", "review-card-10",
                    "review-helpful-btn-1", "review-helpful-btn-2", "review-report-btn",
                    "review-photo-1", "review-photo-2", "pagination-prev", "pagination-next",
                    "page-indicator", "average-rating-chart"]
    },
    "sidebar": {
        "label_prefix": "Sidebar",
        "count": 15,
        "node_type": "dom",
        "labels": ["recommended-section", "rec-product-1", "rec-product-2", "rec-product-3",
                    "rec-product-4", "recently-viewed", "ad-banner-1", "ad-banner-2",
                    "newsletter-signup", "wishlist-summary", "cart-summary", "price-tracker",
                    "size-guide-link", "care-instructions", "return-policy-link"]
    },
    "footer": {
        "label_prefix": "Footer",
        "count": 15,
        "node_type": "dom",
        "labels": ["company-links", "help-center", "shipping-info", "returns-policy", "privacy-policy",
                    "terms-of-service", "social-facebook", "social-twitter", "social-instagram",
                    "social-youtube", "app-store-badge", "play-store-badge", "payment-methods",
                    "ssl-badge", "newsletter-input"]
    },
    "overlays": {
        "label_prefix": "Overlay",
        "count": 8,
        "node_type": "dom",
        "labels": ["cookie-consent", "newsletter-modal", "chat-widget", "chat-minimize-btn",
                    "size-guide-modal", "image-zoom-overlay", "quick-view-modal", "cart-drawer"]
    },
    "accessibility": {
        "label_prefix": "A11y",
        "count": 8,
        "node_type": "accessibility",
        "labels": ["skip-to-content", "aria-live-region", "focus-trap-modal", "keyboard-nav",
                    "screen-reader-only-desc", "aria-label-close", "role-alert-dialog", "tabindex-order"]
    },
    "network": {
        "label_prefix": "Net",
        "count": 10,
        "node_type": "network",
        "labels": ["product-api", "reviews-api", "recommendations-api", "cart-api",
                    "auth-check", "search-suggestions", "analytics-pixel", "ad-server",
                    "cdn-images", "web-socket-chat"]
    },
}

node_id = 0
edge_id = 0
for cat_name, cat in categories.items():
    for i, label in enumerate(cat["labels"]):
        nid = f"n{node_id}"
        nodes.append({
            "node_id": nid,
            "node_type": cat["node_type"],
            "label": label,
            "properties": {
                "tag": "div" if cat["node_type"] != "network" else "xhr",
                "role": "button" if "btn" in label else "text",
                "selector": f"#{label}",
                "visible": "hidden" not in label and "modal" not in label and "overlay" not in label,
                "interactive": "btn" in label or "input" in label or "select" in label,
                "text_content": f"Label for {label}",
            },
            "observation_ids": [f"obs-{nid}"],
            "metadata": {"category": cat_name, "index": i}
        })
        
        # Add containment edges (parent-child hierarchy)
        if i > 0:
            parent_idx = node_id - (i % 3 + 1)  # stagger parents
            if parent_idx < 0:
                parent_idx = 0
            parent_id = f"n{parent_idx}"
            edges.append({
                "edge_id": f"e{edge_id}",
                "source_id": parent_id,
                "target_id": nid,
                "edge_type": "containment",
                "weight": 1.0,
                "properties": {},
                "observation_ids": []
            })
            edge_id += 1
        
        # Add evidence edges
        if node_id % 3 == 0:
            edges.append({
                "edge_id": f"e{edge_id}",
                "source_id": nid,
                "target_id": f"obs-{nid}",
                "edge_type": "evidence",
                "weight": 0.95,
                "properties": {},
                "observation_ids": [f"obs-{nid}"]
            })
            edge_id += 1
            
        node_id += 1

# Add 5 intent nodes for the page
intent_nodes = [
    {"node_id": "n1000", "node_type": "intent", "label": "page-purpose", "properties": {"intent": "product_view", "confidence": 0.95}},
    {"node_id": "n1001", "node_type": "intent", "label": "user-intent-purchase", "properties": {"intent": "purchase", "confidence": 0.7}},
    {"node_id": "n1002", "node_type": "intent", "label": "user-intent-compare", "properties": {"intent": "compare", "confidence": 0.3}},
    {"node_id": "n1003", "node_type": "intent", "label": "user-intent-review", "properties": {"intent": "read_reviews", "confidence": 0.6}},
    {"node_id": "n1004", "node_type": "intent", "label": "page-analytics-cart", "properties": {"intent": "add_to_cart", "confidence": 0.5}},
]
nodes.extend(intent_nodes)

# Add 2 visual nodes
visual_nodes = [
    {"node_id": "n1005", "node_type": "visual", "label": "viewport-main", "properties": {"width": 1440, "height": 900, "scroll_y": 0}},
    {"node_id": "n1006", "node_type": "visual", "label": "viewport-mobile", "properties": {"width": 375, "height": 812, "scroll_y": 120}},
]
nodes.extend(visual_nodes)

fixture = {
    "graph": {
        "nodes": nodes,
        "edges": edges,
    },
    "metadata": {
        "url": "https://example.com/products/smart-watch-pro",
        "title": "Smart Watch Pro - Product Page",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "page_type": "ecommerce_product",
        "description": "Complex e-commerce product page with gallery, reviews, sidebar, and overlays"
    },
    "scenarios": [
        {
            "name": "add-to-cart-safe",
            "description": "User clicks add-to-cart on visible, interactive button",
            "action_type": "click",
            "selector": "#add-to-cart-btn",
            "evidence": {
                "visible": True, "enabled": True, "attached": True,
                "stable": True, "pointer_events": True
            },
            "context": {
                "user_goal": "Purchase Smart Watch Pro",
                "element_role": "button",
                "auth_state": "valid",
                "risk_level": "low",
                "is_payment": False,
                "has_event_handlers": True,
                "is_loading": False,
                "past_failures": 0
            },
            "expected_strategies": ["action"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        },
        {
            "name": "payment-critical-risk",
            "description": "Payment action with critical risk level triggers ABORT",
            "action_type": "click",
            "selector": "#buy-now-btn",
            "evidence": {
                "visible": True, "enabled": True, "attached": True,
                "stable": True, "pointer_events": True
            },
            "context": {
                "user_goal": "Purchase Smart Watch Pro",
                "element_role": "button",
                "auth_state": "valid",
                "risk_level": "critical",
                "action_category": "payment",
                "is_payment": True,
                "payment_amount": "$299.99",
                "has_event_handlers": True,
                "is_loading": False,
                "past_failures": 0
            },
            "expected_strategies": ["abort"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        },
        {
            "name": "hidden-element-click",
            "description": "Trying to click a hidden/collapsed element",
            "action_type": "click",
            "selector": "#hamburger-menu",
            "evidence": {
                "visible": False, "enabled": True, "attached": True,
                "stable": True, "pointer_events": False
            },
            "context": {
                "user_goal": "Open mobile menu",
                "element_role": "button",
                "auth_state": "valid",
                "risk_level": "low",
                "is_hidden": True,
                "has_event_handlers": True,
                "is_loading": False,
                "past_failures": 0
            },
            "expected_strategies": ["abort", "ask"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        },
        {
            "name": "rate-limited-api-call",
            "description": "Action blocked due to API rate limiting",
            "action_type": "click",
            "selector": "#search-btn",
            "evidence": {
                "visible": True, "enabled": True, "attached": True,
                "stable": True, "pointer_events": True
            },
            "context": {
                "user_goal": "Search products",
                "element_role": "button",
                "auth_state": "valid",
                "risk_level": "low",
                "rate_limit_remaining": 0,
                "has_event_handlers": True,
                "is_loading": False,
                "past_failures": 0
            },
            "expected_strategies": ["abort", "recover"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        },
        {
            "name": "expired-auth-form-fill",
            "description": "Filling a form with expired authentication",
            "action_type": "fill",
            "selector": "#newsletter-input",
            "evidence": {
                "visible": True, "enabled": True, "attached": True,
                "stable": True, "editable": True
            },
            "context": {
                "user_goal": "Subscribe to newsletter",
                "element_role": "textbox",
                "auth_state": "expired",
                "risk_level": "low",
                "has_event_handlers": True,
                "is_loading": False,
                "past_failures": 0
            },
            "expected_strategies": ["recover"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        },
        {
            "name": "obscured-element",
            "description": "Clicking an element obscured by another element",
            "action_type": "click",
            "selector": "#quick-view-modal",
            "evidence": {
                "visible": True, "enabled": True, "attached": True,
                "stable": True, "pointer_events": True
            },
            "context": {
                "user_goal": "Quick view product",
                "element_role": "dialog",
                "auth_state": "valid",
                "risk_level": "low",
                "is_obscured": True,
                "has_event_handlers": True,
                "is_loading": False,
                "past_failures": 0
            },
            "expected_strategies": ["recover"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        },
        {
            "name": "cross-perspective-high-risk",
            "description": "Multiple perspectives flag an issue (detached + JS error)",
            "action_type": "click",
            "selector": "#chat-widget",
            "evidence": {
                "visible": False, "enabled": False, "attached": False,
                "stable": False, "pointer_events": False
            },
            "context": {
                "user_goal": "Open chat",
                "element_role": "button",
                "auth_state": "valid",
                "risk_level": "medium",
                "has_event_handlers": False,
                "js_error": "chat-script.js:550 TypeError: t is not a function",
                "is_loading": True,
                "past_failures": 5
            },
            "expected_strategies": ["abort"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        },
        {
            "name": "known-success-pattern",
            "description": "Action matches a known successful pattern from history",
            "action_type": "click",
            "selector": "#login-btn",
            "evidence": {
                "visible": True, "enabled": True, "attached": True,
                "stable": True, "pointer_events": True
            },
            "context": {
                "user_goal": "Log in",
                "element_role": "button",
                "auth_state": "valid",
                "risk_level": "low",
                "has_event_handlers": True,
                "is_loading": False,
                "past_failures": 0,
                "known_pattern": "success"
            },
            "expected_strategies": ["action"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        },
        {
            "name": "mixed-safe-unsafe",
            "description": "Mixed safety results — safe lowest confidence",
            "action_type": "click",
            "selector": "#compare-btn",
            "evidence": {
                "visible": True, "enabled": True, "attached": True,
                "stable": True, "pointer_events": True
            },
            "context": {
                "user_goal": "",
                "element_role": "button",
                "auth_state": "valid",
                "risk_level": "low",
                "has_event_handlers": True,
                "is_loading": False,
                "past_failures": 2
            },
            "expected_strategies": ["action"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        },
        {
            "name": "cross-perspective-safety-veto",
            "description": "Safety critical veto overrides all other perspectives",
            "action_type": "click",
            "selector": "#delete-account-btn",
            "evidence": {
                "visible": True, "enabled": True, "attached": True,
                "stable": True, "pointer_events": True
            },
            "context": {
                "user_goal": "Delete account",
                "element_role": "button",
                "auth_state": "valid",
                "risk_level": "critical",
                "action_category": "account_deletion",
                "is_payment": False,
                "has_event_handlers": True,
                "is_loading": False,
                "past_failures": 0
            },
            "expected_strategies": ["abort"],
            "enabled_perspectives": ["user", "dom", "visual", "network", "js", "safety", "history"]
        }
    ]
}

with open("tests/fixtures/perspectives/complex_graph.json", "w") as f:
    json.dump(fixture, f, indent=2)

print(f"Generated fixture with {len(nodes)} nodes and {len(edges)} edges")
print(f"Scenarios: {len(fixture['scenarios'])}")
print(f"Node count check: {len(nodes) >= 100} ({len(nodes)} nodes)")
