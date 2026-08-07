# P3-A Structured Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable structured Master/Layout/Placeholder PowerPoint generation with true OOXML inheritance

**Architecture:** Database model + API + spec_lock extension + SVG metadata + converter integration + editor + frontend + tests

**Tech Stack:** Python 3.11, SQLAlchemy, FastAPI, pytest, Vue 3, TypeScript, Vitest

---

## Execution Status

- [x] Task 1: Database model (PPTStructuredWorkspace added to models.py)
- [ ] Task 2: Alembic migration
- [ ] Task 3: Workspace service
- [ ] Task 4: Workspace API
- [ ] Task 5: Extend incremental request
- [ ] Task 6: spec_lock structured section
- [ ] Task 7: Layout assignment in planning
- [ ] Task 8: SVG metadata generation
- [ ] Task 9: Converter structured integration
- [ ] Task 10: Editor structured handling
- [ ] Task 11: Frontend toggle
- [ ] Task 12: Backend tests
- [ ] Task 13: OOXML validation
- [ ] Task 14: Production deployment
- [ ] Task 15: Browser acceptance

---

## Task 2: Alembic Migration

**Files:**
- Create: `alembic/versions/20260723_ppt_structured_workspace.py`
- Test: Migration applies and reverts cleanly

**Steps:**

1. Find current alembic head
2. Create migration file
3. Test upgrade
4. Test downgrade
5. Commit

---

## Task 3: Workspace Service

**Files:**
- Create: `app/PPT_master/workspace_service.py`
- Create: `app/PPT_master/workspace_fixtures.py`
- Test: `tests/test_workspace_service.py`

**Core methods:**
- `get_workspace(db, workspace_id) -> dict | None`
- `list_user_workspaces(db, user_id) -> list[dict]`
- `create_builtin_workspace(db, user_id, canvas) -> str`

**Builtin fixture must include:**
- 1 master: master_default
- 5 layouts: title, title_content, section, two_column, blank
- Placeholders for each layout

---

## Task 4: Workspace API Routes

**Files:**
- Create: `app/PPT_master/workspace_router.py`
- Modify: `app/main.py`
- Test: `tests/test_workspace_api.py`

**Routes:**
- GET /api/v1/ppt-master/workspaces
- GET /api/v1/ppt-master/workspaces/{id}

**Auth:** Require login, allow builtin or owned workspaces only

---

## Task 5: Extend Incremental Request

**Files:**
- Modify: `app/PPT_master/incremental_router.py`
- Test: `tests/test_incremental_structured.py`

**Add fields:**
- `pptx_structure_mode: Literal["flat", "structured"] = "flat"`
- `workspace_id: str | None = None`

**Validation:** If structured, workspace_id required

---

## Task 6: spec_lock Structured Section

**Files:**
- Modify: `app/PPT_master/nodes.py` (spec_node)
- Test: `tests/test_spec_lock_structured.py`

**When mode=structured, add to spec_lock.md:**

```
pptx_structure:
  mode: structured
  workspace_id: {workspace_id}
  workspace_revision: 1
  master_map: [{master_id, name}, ...]
  layout_map: [{layout_id, kind, master_id}, ...]
  slide_layout_assignments: [{slide_index, layout_id}, ...]
  placeholder_assignments: [{slide_index, placeholder_bindings}, ...]
```

---

## Task 7: Layout Assignment in Planning

**Files:**
- Modify: `app/PPT_master/nodes.py` (planning logic)
- Test: `tests/test_layout_assignment.py`

**Logic:**
- Slide 0 (cover) -> layout_title
- Section slides -> layout_section
- Content slides -> layout_title_content or layout_two_column
- Record assignments in slide_layout_assignments

---

## Task 8: SVG Metadata Generation

**Files:**
- Modify: `app/PPT_master/incremental_slides.py`
- Test: `tests/test_svg_structured_metadata.py`

**Add to SVG root when structured:**
```xml
<svg data-pptx-mode="structured"
     data-pptx-master="master_default"
     data-pptx-layout="layout_title_content"
     data-pptx-workspace="{workspace_id}">
```

**Add to placeholder elements:**
```xml
<g data-pptx-placeholder="title" data-pptx-idx="0" data-pptx-editable="true">
```

---

## Task 9: Converter Structured Integration

**Files:**
- Verify: `app/PPT_master/skill/ppt-master/scripts/svg_to_pptx/` reads spec_lock
- Test: `tests/test_converter_structured.py`

**Must generate:**
- Real p:sldMaster elements
- Real p:sldLayout elements
- Slide -> layout relationships
- Layout -> master relationships
- Placeholder with correct type/idx

**Must NOT:**
- Duplicate master fixed elements on each slide
- Duplicate layout fixed elements on each slide
- Generate flat structure when mode=structured

---

## Task 10: Editor Structured Handling

**Files:**
- Modify: `app/PPT_master/editor/document.py` (if exists)
- Test: `tests/test_editor_structured.py`

**Requirements:**
- Distinguish master/layout/slide layers
- Mark inherited elements as read-only
- Allow editing slide-local and placeholder content
- On export, preserve structured mode

---

## Task 11: Frontend Toggle

**Files:**
- Modify: `src/views/PptPage.vue` or settings component
- Add: Workspace selector dropdown
- Test: Frontend unit tests + E2E

**UI:**
- Advanced settings: "Presentation Structure"
- Radio: "Fast (Flat)" | "Structured"
- When Structured selected, show workspace dropdown
- Default: Flat

---

## Task 12: Backend Tests

**Coverage:**
- Workspace CRUD
- User isolation
- Structured request validation
- spec_lock generation
- Layout assignment
- SVG metadata
- Flat mode unchanged

---

## Task 13: OOXML Validation

**Files:**
- Create: `tests/fixtures/structured_pptx_validation.py`
- Test: Real PPTX structure

**Must verify:**
- Master count > 0
- Layout count > 1
- Slide->layout rels exist
- Layout->master rels exist
- Placeholder type/idx correct
- Fixed elements not duplicated per slide
- PowerPoint can open file

---

## Task 14: Production Deployment

**Steps:**
1. Merge to feature branch
2. Run all tests (backend + frontend)
3. Database migration on staging
4. Restart services
5. Manual smoke test
6. Merge to main
7. Production migration
8. Restart production services
9. Create tags

**Tags:**
- production-ppt-p3-structured-generation-20260723
- rollback-ppt-p3-structured-generation-20260723

---

## Task 15: Browser Acceptance

**Test with account 123/123:**

1. Open http://192.168.0.11:3000/ppt
2. Enable Structured mode in advanced settings
3. Select builtin workspace
4. Generate 6-page presentation
5. Verify:
   - spec_lock contains pptx_structure
   - Download PPTX
   - Inspect OOXML: masters, layouts, rels
   - Open in PowerPoint
   - Switch layout works
   - Edit placeholder content
   - Re-export preserves structure
6. Console: 0 errors
7. Failed requests: 0
8. Verify flat mode still works (default)

---

## Regression Requirements

After P3-A complete, verify:
- Flat mode (default) unchanged
- P2-A template fill works
- P2-B native enhance works
- Editor opens old projects
- History listing works
