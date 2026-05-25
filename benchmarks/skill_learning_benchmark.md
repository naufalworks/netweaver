# Skill Learning Benchmark Plan

**Task**: NW-023
**Owner**: QA Benchmark
**Date**: 2026-05-24
**Status**: review

## Purpose

Define repeatable benchmark tasks and success metrics for NetWeaver's skill learning layer — two modules that currently lack dedicated benchmark coverage:

1. **SiteSkill + SkillStore** (`site_skill.py`) — persist successful flows as reusable skills
2. **SkillMatcher** (`skill_matcher.py`) — ranked skill lookup by URL + goal

All benchmarks use **in-memory fixtures and tmpdir persistence** — no browser download, no Playwright, no network access required.

---

## Benchmark Tasks (10)

### SK-001: SiteSkill Data Model

Verify SiteSkill dataclass creation, defaults, and field integrity.

**Pass criteria**:
- Auto-generated skill_id if not provided
- created_at / updated_at default to now
- execution_stats default: {success_count: 0, fail_count: 0}
- All fields accessible and mutable

### SK-002: SiteSkill Serialization Round-Trip

Verify to_dict() / from_dict() produce identical SiteSkill objects.

**Pass criteria**:
- Round-trip preserves all scalar fields
- Round-trip preserves lists, dicts, nested structures
- ISO format datetime strings deserialize correctly
- Empty fields serialize as defaults

### SK-003: SiteSkill Site Matching

Verify regex-based URL matching against site_pattern.

**Pass criteria**:
- Exact domain match works
- Wildcard patterns work (*.example.com)
- Path patterns work (example.com/login)
- Invalid regex returns False (no crash)
- Empty pattern returns False

### SK-004: SiteSkill Execution Stats

Verify record_success() and record_failure() mutation of execution_stats.

**Pass criteria**:
- success_count increments on record_success()
- fail_count increments on record_failure()
- Timestamps updated (last_used_at, last_success_at)
- updated_at changes on each call
- Stats accumulate correctly over multiple calls

### SK-005: SkillStore Persistence

Verify SkillStore CRUD operations against tmpdir.

**Pass criteria**:
- save() writes JSON file to skills_dir
- load() reads back identical SiteSkill
- delete() removes file and cache entry
- find_by_site() returns matching skills
- find_by_goal() returns skills with matching goal regex
- list_all() returns all saved skills
- Empty directory returns empty list

### SK-006: SkillStore Factory Method

Verify SiteSkill.from_orchestration_result() factory creates valid skills.

**Pass criteria**:
- Site pattern auto-extracted from URL
- Preconditions/postconditions extracted from plan steps
- Evidence chain IDs collected from result steps
- Name auto-generated if not provided
- Goal falls back to plan description

### SK-007: SkillMatcher Scoring Accuracy

Verify SkillMatcher composite scoring formula: 0.4×site + 0.3×goal + 0.3×success.

**Pass criteria**:
- Perfect match: site=1.0, goal=1.0, success=1.0 → score=1.0
- No match: site=0.0, goal=0.0, success=0.0 → score=0.0
- Partial match components computed correctly
- Neutral prior: zero-execution skill → success_rate=0.5
- Jaccard similarity matches expected value

### SK-008: SkillMatcher Ranking & Determinism

Verify result ordering, tie-breaking, and top_k truncation.

**Pass criteria**:
- Results sorted descending by score
- Equal scores broken by skill_id (alphabetical)
- top_k limits output count
- top_k larger than store returns all skills
- Ranks assigned 1..N sequentially
- Empty store returns empty list

### SK-009: SkillMatcher Tokenization

Verify _tokenize() produces correct word token sets.

**Pass criteria**:
- Lowercasing applied
- Punctuation stripped from token edges
- Tokens < 2 chars filtered
- Empty string returns empty set
- Numbers preserved as tokens

### SK-010: End-to-End Skill Lifecycle

Verify the full skill lifecycle: learn → store → match → retrieve.

**Pass criteria**:
- Create skill from orchestration result
- Save to store → retrieve by ID
- Match against original URL → skill found
- Match against different URL → appropriate ranking
- Record success/failure stats → re-match with updated score
- Delete skill → no longer in match results

---

## Scoring

Contract benchmark — pass = all tests green.

| Metric | Target |
|--------|--------|
| SiteSkill model integrity | 100% |
| SkillStore CRUD correctness | 100% |
| SkillMatcher scoring accuracy | 100% |
| Ranking determinism | 100% |
| Tokenization correctness | 100% |
| End-to-end lifecycle | 100% |
| No browser/network required | Yes |
| No vendor/CloakBrowser imports | Yes |

---

## Dependencies

- `netweaver/site_skill.py` — SiteSkill data model + SkillStore
- `netweaver/skill_matcher.py` — SkillMatcher engine
- `pytest` — test runner
- No browser, no network, no Playwright

## Risks

- SkillStore.find_by_site() uses regex matching — complex patterns may have edge cases
- from_orchestration_result() depends on dict structure from ActionPlan/OrchestrationResult
- SkillMatcher._tokenize() strips punctuation only from edges, not internal
