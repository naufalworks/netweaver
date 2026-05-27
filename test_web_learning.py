#!/usr/bin/env python3
"""Quick test of web learning integration."""
from netweaver.web_learner import WebLearner

print("🌐 Testing Web Learner (headless)...\n")

learner = WebLearner(headless=True)
results = learner.learn_cycle()

print(learner.summary(results))

successes = sum(1 for r in results if r.success)
print(f"\n{'✅' if successes > 0 else '❌'} {successes}/{len(results)} sites successful")

learner.close()
