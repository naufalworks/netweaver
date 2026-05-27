"""NetWeaver — Browser-native world model and evidence-first automation."""

import os

def get_product_spec():
    """Return the contents of PRODUCT_SPEC.md."""
    path = os.path.join(os.path.dirname(__file__), '..', 'PRODUCT_SPEC.md')
    with open(path) as f:
        return f.read()

product_spec = get_product_spec()
