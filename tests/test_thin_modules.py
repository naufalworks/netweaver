"""Comprehensive tests for thin module expansion (NW-037).

Covers all 5 modules: tracker, skill_view, product_spec, roadmap,
skill_doc_extractor — with emphasis on new multi-format extraction.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

import pytest

# ── tracker ───────────────────────────────────────────────────────────


class TestTrackerModule:
    """Tests for netweaver.tracker — items, events, persistence, query."""

    def test_query_filter_state(self):
        from netweaver.tracker import Item, ItemState, QueryFilter, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "a", state=ItemState.BACKLOG))
        tracker.add_item(Item("2", "b", state=ItemState.IN_PROGRESS))
        tracker.add_item(Item("3", "c", state=ItemState.DONE))

        assert len(tracker.query(QueryFilter(state=ItemState.BACKLOG))) == 1
        assert len(tracker.query(QueryFilter(state=ItemState.IN_PROGRESS))) == 1
        assert len(tracker.query(QueryFilter(state=ItemState.DONE))) == 1

    def test_query_filter_tags(self):
        from netweaver.tracker import Item, QueryFilter, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "a", tags=["bug", "urgent"]))
        tracker.add_item(Item("2", "b", tags=["feature"]))
        tracker.add_item(Item("3", "c", tags=["bug"]))

        assert len(tracker.query(QueryFilter(tags=["bug"]))) == 2
        assert len(tracker.query(QueryFilter(tags=["urgent"]))) == 1

    def test_query_filter_priority(self):
        from netweaver.tracker import Item, QueryFilter, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "a", priority=1))
        tracker.add_item(Item("2", "b", priority=5))
        tracker.add_item(Item("3", "c", priority=10))

        assert len(tracker.query(QueryFilter(min_priority=5))) == 2
        assert len(tracker.query(QueryFilter(max_priority=5))) == 2
        assert len(tracker.query(QueryFilter(min_priority=3, max_priority=7))) == 1

    def test_query_filter_assignee(self):
        from netweaver.tracker import Item, QueryFilter, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "a", assignee="alice"))
        tracker.add_item(Item("2", "b", assignee="bob"))
        assert len(tracker.query(QueryFilter(assignee="alice"))) == 1

    def test_query_filter_date(self):
        from netweaver.tracker import Item, QueryFilter, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "old"))
        tracker.add_item(Item("2", "new"))
        cutoff = datetime.now(timezone.utc).isoformat(timespec="seconds")
        assert len(tracker.query(QueryFilter(created_before=cutoff))) == 2

    def test_event_tracking(self):
        from netweaver.tracker import Item, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "test"))
        tracker.move_item("1", "in_progress")
        tracker.update_item("1", description="updated")
        events = tracker.get_events()
        assert len(events) == 3
        assert events[0].event_type == "item_added"
        assert events[1].event_type == "item_transitioned"
        assert events[2].event_type == "item_updated"

    def test_event_filtering(self):
        from netweaver.tracker import Item, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "a"))
        tracker.move_item("1", "in_progress")
        tracker.add_item(Item("2", "b"))
        assert len(tracker.get_events(event_type="item_added")) == 2
        assert len(tracker.get_events(item_id="1")) == 2

    def test_event_clear(self):
        from netweaver.tracker import Item, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "a"))
        tracker.clear_events()
        assert len(tracker.get_events()) == 0

    def test_remove_item(self):
        from netweaver.tracker import Item, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "a"))
        tracker.remove_item("1")
        assert tracker.get_item("1") is None

    def test_remove_nonexistent_raises(self):
        from netweaver.tracker import Tracker

        tracker = Tracker()
        with pytest.raises(KeyError):
            tracker.remove_item("nonexistent")

    def test_save_and_load(self):
        from netweaver.tracker import Item, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "title", "desc", tags=["bug"]))
        tracker.move_item("1", "in_progress")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker.save(path)
            loaded = Tracker.load(path)
            item = loaded.get_item("1")
            assert item is not None
            assert item.title == "title"
            assert item.state == "in_progress"
            assert item.description == "desc"
            assert len(loaded.get_events()) == 2
        finally:
            os.unlink(path)

    def test_tracker_search(self):
        from netweaver.tracker import Item, Tracker

        tracker = Tracker()
        tracker.add_item(Item("1", "Fix login bug", tags=["bug"]))
        tracker.add_item(Item("2", "Add feature", tags=["feature"]))
        results = tracker.search("bug")
        assert len(results) == 1
        assert results[0].id == "1"

    def test_item_count(self):
        from netweaver.tracker import Item, Tracker

        tracker = Tracker()
        assert tracker.item_count() == 0
        tracker.add_item(Item("1", "a"))
        assert tracker.item_count() == 1

    def test_state_validity(self):
        from netweaver.tracker import ItemState

        assert ItemState.is_valid("backlog")
        assert ItemState.is_valid("done")
        assert not ItemState.is_valid("invalid_state")

    def test_item_empty_id_raises(self):
        from netweaver.tracker import Item

        with pytest.raises(ValueError, match="item_id"):
            Item("", "title")


# ── skill_view ────────────────────────────────────────────────────────


class TestSkillViewModule:
    """Tests for netweaver.skill_view — SkillDoc, rendering, filtering, export."""

    def test_skill_doc_creation(self):
        from netweaver.skill_view import SkillDoc

        doc = SkillDoc(name="test", description="A test skill")
        assert doc.name == "test"
        assert doc.description == "A test skill"
        assert doc.category == ""
        assert doc.tags == []

    def test_skill_doc_with_all_fields(self):
        from netweaver.skill_view import SkillDoc

        doc = SkillDoc(
            name="full",
            description="desc",
            category="dev",
            tags=["python", "test"],
            author="me",
            version="2.0.0",
            content="full content",
        )
        assert doc.author == "me"
        assert doc.version == "2.0.0"
        assert doc.content == "full content"
        assert doc.category == "dev"

    def test_skill_doc_defaults(self):
        from netweaver.skill_view import SkillDoc

        doc = SkillDoc(name="defaults")
        assert doc.author == "system"
        assert doc.version == "1.0.0"
        assert doc.content == doc.description

    def test_skill_doc_matches_filter(self):
        from netweaver.skill_view import SkillDoc

        doc = SkillDoc(name="MySkill", description="does python stuff", tags=["python"])
        assert doc.matches_filter("python")
        assert doc.matches_filter("MySkill")
        assert not doc.matches_filter("javascript")

    def test_skill_doc_to_dict_roundtrip(self):
        from netweaver.skill_view import SkillDoc

        doc = SkillDoc(name="rt", description="round trip", tags=["test"])
        d = doc.to_dict()
        restored = SkillDoc.from_dict(d)
        assert restored.name == "rt"
        assert restored.description == "round trip"
        assert restored.tags == ["test"]

    def test_render_markdown(self):
        from netweaver.skill_view import SkillDoc, render_skills_markdown

        docs = [SkillDoc(name="A", description="desc A")]
        output = render_skills_markdown(docs)
        assert "**A**" in output
        assert "desc A" in output
        assert "## Available Skills" in output

    def test_render_markdown_empty(self):
        from netweaver.skill_view import render_skills_markdown

        output = render_skills_markdown([])
        assert "No skills available" in output

    def test_render_json(self):
        from netweaver.skill_view import SkillDoc, render_skills_json

        docs = [SkillDoc(name="J", description="json test")]
        output = render_skills_json(docs)
        parsed = json.loads(output)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "J"

    def test_render_html(self):
        from netweaver.skill_view import SkillDoc, render_skills_html

        docs = [SkillDoc(name="H", description="html test", tags=["web"])]
        output = render_skills_html(docs)
        assert "<h2>" in output
        assert "<strong>H</strong>" in output
        assert 'class="tag"' in output

    def test_render_rst(self):
        from netweaver.skill_view import SkillDoc, render_skills_rst

        docs = [SkillDoc(name="R", description="rst test")]
        output = render_skills_rst(docs)
        assert "Available Skills" in output
        assert "=====" in output

    def test_filter_skills_by_query(self):
        from netweaver.skill_view import SkillDoc, filter_skills

        docs = [
            SkillDoc(name="Parsing", description="parse HTML"),
            SkillDoc(name="Render", description="render markdown"),
        ]
        result = filter_skills(docs, query="parse")
        assert len(result) == 1
        assert result[0].name == "Parsing"

    def test_filter_skills_by_category(self):
        from netweaver.skill_view import SkillDoc, filter_skills

        docs = [
            SkillDoc(name="A", category="dev"),
            SkillDoc(name="B", category="ops"),
        ]
        assert len(filter_skills(docs, category="dev")) == 1
        assert len(filter_skills(docs, category="none")) == 0

    def test_filter_skills_by_tags(self):
        from netweaver.skill_view import SkillDoc, filter_skills

        docs = [
            SkillDoc(name="A", tags=["python", "test"]),
            SkillDoc(name="B", tags=["js"]),
        ]
        result = filter_skills(docs, tags=["python"])
        assert len(result) == 1

    def test_export_unsupported_format(self):
        from netweaver.skill_view import export_skills

        with pytest.raises(ValueError, match="format"):
            export_skills([], fmt="unknown")

    def test_skill_view_prompt_function(self):
        from netweaver.skill_view import skill_view

        result = skill_view()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_skill_view_with_agent(self):
        from netweaver.skill_view import skill_view

        result = skill_view(agent="cron")
        assert "cron" in result


# ── product_spec ──────────────────────────────────────────────────────


class TestProductSpecModule:
    """Tests for netweaver.product_spec — SpecComponent, SpecPhase, ProductSpec."""

    def test_spec_component_creation(self):
        from netweaver.product_spec import SpecComponent

        c = SpecComponent(name="auth", status="implemented", description="Login flow")
        assert c.name == "auth"
        assert c.status == "implemented"
        assert c.is_implemented()

    def test_component_not_implemented(self):
        from netweaver.product_spec import SpecComponent

        c = SpecComponent(name="planned_feature")
        assert not c.is_implemented()

    def test_component_to_dict_roundtrip(self):
        from netweaver.product_spec import SpecComponent

        c = SpecComponent("comp", "tested", owner="alice", dependencies=["dep1"])
        d = c.to_dict()
        restored = SpecComponent.from_dict(d)
        assert restored.name == "comp"
        assert restored.owner == "alice"
        assert restored.dependencies == ["dep1"]

    def test_spec_phase_creation(self):
        from netweaver.product_spec import SpecPhase

        p = SpecPhase("Phase 1", "NW-001", "in_progress", "First phase")
        assert p.title == "Phase 1"
        assert p.completion_percentage() == 0.0

    def test_phase_completion_percentage(self):
        from netweaver.product_spec import SpecComponent, SpecPhase

        p = SpecPhase("P1")
        p.add_component(SpecComponent("a", "implemented"))
        p.add_component(SpecComponent("b", "planned"))
        p.add_component(SpecComponent("c", "deployed"))
        assert p.completion_percentage() == 2 / 3

    def test_phase_add_component(self):
        from netweaver.product_spec import SpecComponent, SpecPhase

        p = SpecPhase("P1")
        p.add_component(SpecComponent("a"))
        p.add_component(SpecComponent("b"))
        assert len(p.components) == 2

    def test_phase_to_dict_roundtrip(self):
        from netweaver.product_spec import SpecComponent, SpecPhase

        p = SpecPhase("P1", status="completed")
        p.add_component(SpecComponent("a", "implemented"))
        d = p.to_dict()
        restored = SpecPhase.from_dict(d)
        assert restored.title == "P1"
        assert len(restored.components) == 1

    def test_product_spec_validation_passes(self):
        from netweaver.product_spec import ProductSpec, SpecComponent, SpecPhase

        spec = ProductSpec("My Spec", "1.0.0")
        phase = SpecPhase("Phase 1", status="in_progress")
        phase.add_component(SpecComponent("comp1", "implemented"))
        spec.add_phase(phase)
        errors = spec.validate()
        assert errors == []

    def test_product_spec_validation_fails_empty_title(self):
        from netweaver.product_spec import ProductSpec

        spec = ProductSpec("")
        errors = spec.validate()
        assert len(errors) > 0

    def test_product_spec_versioning(self):
        from netweaver.product_spec import ProductSpec

        spec = ProductSpec("Test", "1.0.0")
        spec.set_version("2.0.0", reason="Major update")
        assert spec.version == "2.0.0"
        assert len(spec.version_log) == 1
        assert spec.version_log[0]["old_version"] == "1.0.0"
        assert spec.version_log[0]["new_version"] == "2.0.0"

    def test_product_spec_is_valid(self):
        from netweaver.product_spec import ProductSpec, SpecComponent, SpecPhase

        spec = ProductSpec("Valid Spec")
        phase = SpecPhase("P1")
        phase.add_component(SpecComponent("c1", "tested"))
        spec.add_phase(phase)
        assert spec.is_valid()

    def test_spec_overall_completion(self):
        from netweaver.product_spec import ProductSpec, SpecComponent, SpecPhase

        spec = ProductSpec("Spec")
        p1 = SpecPhase("P1")
        p1.add_component(SpecComponent("c1", "implemented"))
        p1.add_component(SpecComponent("c2", "planned"))
        spec.add_phase(p1)
        p2 = SpecPhase("P2")
        p2.add_component(SpecComponent("c3", "deployed"))
        spec.add_phase(p2)
        assert spec.overall_completion() == 0.75  # (0.5 + 1.0) / 2

    def test_spec_get_phase(self):
        from netweaver.product_spec import ProductSpec, SpecPhase

        spec = ProductSpec("Spec")
        spec.add_phase(SpecPhase("Phase A"))
        spec.add_phase(SpecPhase("Phase B"))
        assert spec.get_phase("Phase A") is not None
        assert spec.get_phase("Phase C") is None

    def test_spec_save_and_load(self):
        from netweaver.product_spec import ProductSpec, SpecComponent, SpecPhase

        spec = ProductSpec("Save Test", "1.0.0")
        phase = SpecPhase("P1", status="completed")
        phase.add_component(SpecComponent("c1", "deployed"))
        spec.add_phase(phase)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            spec.save(path)
            loaded = ProductSpec.load(path)
            assert loaded.title == "Save Test"
            assert loaded.version == "1.0.0"
            assert len(loaded.phases) == 1
        finally:
            os.unlink(path)

    def test_spec_to_dict_roundtrip(self):
        from netweaver.product_spec import ProductSpec, SpecPhase

        spec = ProductSpec("RT", "2.0.0")
        spec.add_phase(SpecPhase("P1"))
        d = spec.to_dict()
        restored = ProductSpec.from_dict(d)
        assert restored.title == "RT"
        assert restored.version == "2.0.0"

    def test_validation_error_exception(self):
        from netweaver.product_spec import ValidationError

        err = ValidationError(["error1", "error2"])
        assert len(err.errors) == 2
        assert "error1" in str(err)


# ── roadmap ───────────────────────────────────────────────────────────


class TestRoadmapModule:
    """Tests for netweaver.roadmap — phases, milestones, dependencies, stats."""

    def test_roadmap_phase_creation(self):
        from netweaver.roadmap import RoadmapPhase

        phase = RoadmapPhase("Alpha", "in_progress", "2026-01-01", "2026-06-01")
        assert phase.name == "Alpha"
        assert phase.is_active()

    def test_phase_add_remove_item(self):
        from netweaver.roadmap import RoadmapPhase

        phase = RoadmapPhase("P1")
        phase.add_item("item1")
        phase.add_item("item2")
        phase.add_item("item1")  # duplicate ignored
        assert phase.item_ids == ["item1", "item2"]
        phase.remove_item("item1")
        assert phase.item_ids == ["item2"]

    def test_dependency_creation(self):
        from netweaver.roadmap import Dependency

        dep = Dependency("src", "tgt", "blocks")
        assert dep.source_id == "src"
        assert dep.target_id == "tgt"
        assert dep.dep_type == "blocks"

    def test_dependency_to_dict_roundtrip(self):
        from netweaver.roadmap import Dependency

        dep = Dependency("a", "b", "relates_to")
        d = dep.to_dict()
        restored = Dependency.from_dict(d)
        assert restored.source_id == "a"
        assert restored.target_id == "b"
        assert restored.dep_type == "relates_to"

    def test_add_dependency(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "Task A")
        r.create_roadmap_item("2", "Task B")
        r.add_dependency("1", "2", "blocks")
        deps = r.get_dependencies("1")
        assert len(deps) == 1
        assert deps[0].target_id == "2"

    def test_remove_dependency(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "A")
        r.create_roadmap_item("2", "B")
        r.add_dependency("1", "2")
        r.remove_dependency("1", "2")
        assert len(r.get_dependencies("1")) == 0

    def test_blocked_items(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "A")
        r.create_roadmap_item("2", "B")
        r.add_dependency("1", "2", "blocks")
        blocked = r.get_blocked_items()
        assert "1" in blocked

    def test_is_item_blocked(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "A")
        r.create_roadmap_item("2", "B")
        r.add_dependency("1", "2", "blocks")
        assert r.is_item_blocked("1")
        assert not r.is_item_blocked("2")

    def test_not_blocked_when_target_done(self):
        from netweaver.roadmap import Roadmap
        from netweaver.tracker import ItemState

        r = Roadmap()
        r.create_roadmap_item("1", "A")
        r.create_roadmap_item("2", "B")
        r.move_item("2", ItemState.DONE)
        r.add_dependency("1", "2", "blocks")
        assert not r.is_item_blocked("1")

    def test_resolve_dependency_chain(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "Root")
        r.create_roadmap_item("2", "Dep1")
        r.create_roadmap_item("3", "Dep2")
        r.add_dependency("1", "2")
        r.add_dependency("2", "3")
        chain = r.resolve_dependency_chain("1")
        assert len(chain) == 2
        assert chain[0].id == "2" or chain[1].id == "2"

    def test_get_items_by_phase(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "A", phase="Alpha")
        r.create_roadmap_item("2", "B", phase="Beta")
        items = r.get_items_by_phase("Alpha")
        assert len(items) == 1
        assert items[0].id == "1"

    def test_get_phase_statistics(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "A", phase="P1", state="in_progress")
        r.create_roadmap_item("2", "B", phase="P1")
        stats = r.get_phase_statistics()
        assert "P1" in stats
        assert stats["P1"]["total_items"] == 2
        assert stats["P1"]["state_counts"]["backlog"] == 1

    def test_summary(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "A")
        r.create_roadmap_item("2", "B", milestone="v1")
        summary = r.summary()
        assert summary["total_items"] == 2
        assert summary["milestones"] == 1

    def test_roadmap_persistence(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "A", phase="P1")
        d = r.to_dict()
        assert "phases" in d
        assert "P1" in d["phases"]

    def test_get_dependents(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "A")
        r.create_roadmap_item("2", "B")
        r.add_dependency("1", "2")
        deps = r.get_dependents("2")
        assert len(deps) == 1
        assert deps[0].source_id == "1"

    def test_phase_to_dict_roundtrip(self):
        from netweaver.roadmap import RoadmapPhase

        phase = RoadmapPhase("P1", "in_progress", "2026-01-01")
        phase.add_item("i1")
        d = phase.to_dict()
        restored = RoadmapPhase.from_dict(d)
        assert restored.name == "P1"
        assert restored.item_ids == ["i1"]

    def test_milestone_items(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "A", milestone="M1")
        r.create_roadmap_item("2", "B", milestone="M1")
        r.create_roadmap_item("3", "C")
        items = r.get_items_by_milestone("M1")
        assert len(items) == 2

    def test_query_items_with_phase_filter(self):
        from netweaver.roadmap import Roadmap

        r = Roadmap()
        r.create_roadmap_item("1", "Fix login", phase="Alpha")
        r.create_roadmap_item("2", "Add tests", phase="Beta")
        results = r.query_items(query="login")
        assert len(results) == 1
        results = r.query_items(phase="Alpha")
        assert len(results) == 1


# ── skill_doc_extractor (new features) ────────────────────────────────


class TestSkillDocExtractorExpanded:
    """Tests for expanded multi-format extraction in skill_doc_extractor."""

    def test_extract_markdown_basic(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_md

        content = "# Title\n\nSome body text\n\n## Section 1\n\nSection body"
        result = extract_skill_doc_md(content)
        assert result.format == "markdown"
        assert result.title == "Title"
        assert len(result.sections) == 2  # "Title" (H1) + "Section 1" (H2)
        assert result.sections[0].heading == "Title"
        assert result.sections[1].heading == "Section 1"

    def test_extract_markdown_multiple_sections(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_md

        content = "# Doc\n\n## A\n\nBody A\n\n## B\n\nBody B"
        result = extract_skill_doc_md(content)
        assert len(result.sections) == 2  # Doc (H1, has sub "A") + B (H2, top-level)
        assert result.sections[0].heading == "Doc"
        assert len(result.sections[0].subsections) == 1
        assert result.sections[0].subsections[0].heading == "A"
        assert result.sections[1].heading == "B"

    def test_extract_markdown_subsections(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_md

        content = "# Main\n\n## Section\n\n### Sub\n\nSub body"
        result = extract_skill_doc_md(content)
        assert len(result.sections) == 1  # Main (H1)
        assert result.sections[0].heading == "Main"
        assert len(result.sections[0].subsections) == 1
        assert result.sections[0].subsections[0].heading == "Section"
        assert len(result.sections[0].subsections[0].subsections) == 1
        assert result.sections[0].subsections[0].subsections[0].heading == "Sub"

    def test_extract_markdown_with_frontmatter(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_md

        content = "---\ntitle: My Doc\nauthor: test\n---\n# Actual Title\n\nBody"
        result = extract_skill_doc_md(content)
        assert result.metadata.get("title") == "My Doc"
        assert result.metadata.get("author") == "test"
        assert result.title == "Actual Title"

    def test_extract_markdown_body_content(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_md

        content = "# Doc\n\n## Section\n\nThis is the body.\nIt has multiple lines."
        result = extract_skill_doc_md(content)
        assert result.sections[0].heading == "Doc"
        assert len(result.sections[0].subsections) == 1
        assert "body" in result.sections[0].subsections[0].body.lower()

    def test_extract_html_basic(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_html

        content = "<html><body><h1>Title</h1><p>Body</p></body></html>"
        result = extract_skill_doc_html(content)
        assert result.format == "html"
        assert result.title == "Title"

    def test_extract_html_with_sections(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_html

        content = "<h1>Doc</h1><h2>Section 1</h2><p>Content</p><h2>Section 2</h2><p>More</p>"
        result = extract_skill_doc_html(content)
        assert len(result.sections) >= 2

    def test_extract_rst_basic(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_rst

        content = "Title\n=====\n\nBody text\n\nSection\n------\n\nSection body"
        result = extract_skill_doc_rst(content)
        assert result.format == "rst"
        assert result.title == "Title"

    def test_extract_rst_overline(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_rst

        content = "=======\nTitle\n=======\n\nBody"
        result = extract_skill_doc_rst(content)
        assert result.title == "Title"

    def test_detect_format_markdown(self):
        from netweaver.skill_doc_extractor import detect_format

        assert detect_format("# Heading\n\nBody") == "markdown"

    def test_detect_format_html(self):
        from netweaver.skill_doc_extractor import detect_format

        assert detect_format("<html><body>Content</body></html>") == "html"

    def test_detect_format_html_by_tag(self):
        from netweaver.skill_doc_extractor import detect_format

        assert detect_format("<h1>Title</h1><p>Body</p>") == "html"

    def test_detect_format_rst(self):
        from netweaver.skill_doc_extractor import detect_format

        assert detect_format("Heading\n======") == "rst"

    def test_detect_format_plain(self):
        from netweaver.skill_doc_extractor import detect_format

        assert detect_format("Just some plain text\nNo special markers") == "plain"

    def test_extract_skill_content_auto_detect(self):
        from netweaver.skill_doc_extractor import extract_skill_content

        result = extract_skill_content("# Auto\n\nDetected")
        assert result.format == "markdown"

    def test_extract_skill_content_explicit(self):
        from netweaver.skill_doc_extractor import extract_skill_content

        result = extract_skill_content("<h1>Explicit</h1>", fmt="html")
        assert result.format == "html"

    def test_skill_extractor_class(self):
        from netweaver.skill_doc_extractor import SkillExtractor

        ext = SkillExtractor()
        result = ext.extract("# Test\n\nBody")
        assert result.format == "markdown"

    def test_skill_extractor_invalid_format(self):
        from netweaver.skill_doc_extractor import SkillExtractor

        with pytest.raises(ValueError):
            SkillExtractor(default_format="unknown")

    def test_skill_extractor_extract_section(self):
        from netweaver.skill_doc_extractor import SkillExtractor

        ext = SkillExtractor()
        section = ext.extract_section("# Doc\n\n## Install\n\nRun this command", "Install")
        assert section is not None
        assert section.heading == "Install"

    def test_skill_extractor_section_not_found(self):
        from netweaver.skill_doc_extractor import SkillExtractor

        ext = SkillExtractor()
        section = ext.extract_section("# Doc\n\n## A\n\nBody", "Nonexistent")
        assert section is None

    def test_skill_extractor_list_formats(self):
        from netweaver.skill_doc_extractor import SkillExtractor

        ext = SkillExtractor()
        fmts = ext.list_formats()
        assert "markdown" in fmts
        assert "html" in fmts
        assert "rst" in fmts

    def test_extract_skill_content_plain(self):
        from netweaver.skill_doc_extractor import extract_skill_content

        result = extract_skill_content("Plain text", fmt="plain")
        assert result.format == "plain"
        assert result.raw_content == "Plain text"

    def test_section_count(self):
        from netweaver.skill_doc_extractor import ExtractionResult, ExtractedSection

        result = ExtractionResult(format="test")
        result.sections.append(ExtractedSection("A", "", 1))
        result.sections[0].subsections.append(ExtractedSection("A1", "", 2))
        assert result.section_count() == 2

    def test_extraction_result_to_dict(self):
        from netweaver.skill_doc_extractor import ExtractionResult, ExtractedSection

        result = ExtractionResult(format="md", title="Test")
        result.sections.append(ExtractedSection("Sec 1", "Body text"))
        d = result.to_dict()
        assert d["format"] == "md"
        assert d["title"] == "Test"
        assert len(d["sections"]) == 1

    def test_skill_extractor_to_markdown(self):
        from netweaver.skill_doc_extractor import SkillExtractor

        ext = SkillExtractor()
        result = ext.extract("# Doc\n\n## Section\n\nBody")
        output = ext.to_markdown(result)
        assert "Doc" in output
        assert "Section" in output

    def test_empty_content(self):
        from netweaver.skill_doc_extractor import detect_format, extract_skill_content

        assert detect_format("") == "plain"
        result = extract_skill_content("")
        assert result.format == "plain"

    def test_markdown_multilevel_headings(self):
        from netweaver.skill_doc_extractor import extract_skill_doc_md

        content = "# H1\n\n## H2\n\n### H3\n\n#### H4\n\nBody"
        result = extract_skill_doc_md(content)
        assert len(result.sections) == 1  # H1
        assert result.sections[0].heading == "H1"
        assert len(result.sections[0].subsections) == 1
        assert result.sections[0].subsections[0].heading == "H2"
        assert result.sections[0].subsections[0].level == 2
        assert len(result.sections[0].subsections[0].subsections) == 1
        assert result.sections[0].subsections[0].subsections[0].heading == "H3"

    def test_detect_format_empty(self):
        from netweaver.skill_doc_extractor import detect_format

        assert detect_format("") == "plain"
        assert detect_format("   ") == "plain"

    def test_skill_extractor_extract_metadata(self):
        from netweaver.skill_doc_extractor import SkillExtractor

        content = "---\nkey1: val1\nkey2: val2\n---\n# Doc\n\nBody"
        ext = SkillExtractor()
        meta = ext.extract_metadata(content)
        assert "key1" in meta
