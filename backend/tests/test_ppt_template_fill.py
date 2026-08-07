from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_preview_renderer(monkeypatch, tmp_path):
    import app.PPT_master.template_fill as template_fill
    def render(_source, _target, count):
        paths = []
        for index in range(count):
            path = tmp_path / f"preview-{index + 1}.png"
            path.write_bytes(b"preview")
            paths.append(path)
        return paths
    monkeypatch.setattr(template_fill, "_render_template_previews", render)


def test_template_fill_plan_rejects_apply_until_confirmed():
    from app.PPT_master.template_fill import TemplateFillPlanNotConfirmed, TemplateFillStore

    store = TemplateFillStore()
    plan = {"plan_id": "fillplan_test", "status": "draft"}
    with pytest.raises(TemplateFillPlanNotConfirmed):
        store.require_confirmed(plan)
    assert store.require_confirmed({**plan, "status": "confirmed"}) is None


def test_template_registers_only_an_owned_macro_free_pptx(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from app.database import Base
    from app.models import File, User
    from app.PPT_master.template_fill import TemplateFillStore

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    deck = tmp_path / "template.pptx"
    with ZipFile(deck, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>")
        archive.writestr("ppt/presentation.xml", "<p:presentation xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"/>")
    db.add_all([User(id=1, username="template-owner", password_hash="x"), User(id=2, username="other", password_hash="x")])
    db.add(File(id=201, user_id=1, owner_user_id=1, filename="template.pptx", filepath=str(deck), real_path=str(deck), filetype=".pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"))
    db.commit()

    created = TemplateFillStore().register_template(db, source_file_id=201, user_id=1, title="客户模板")

    assert created["owner_user_id"] == 1
    assert created["source_file_id"] == 201
    assert created["status"] == "uploaded"
    assert created["sha256"]
    assert TemplateFillStore().get_template(db, template_id=created["template_id"], user_id=2) is None


def test_template_analysis_persists_slide_library_and_candidate_slots(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from app.database import Base
    from app.models import File, User
    import app.PPT_master.template_fill as template_fill

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    deck = tmp_path / "template.pptx"
    with ZipFile(deck, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>")
        archive.writestr("ppt/presentation.xml", "<p:presentation xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"/>")
    db.add(User(id=1, username="template-owner", password_hash="x"))
    db.add(File(id=202, user_id=1, owner_user_id=1, filename="template.pptx", filepath=str(deck), real_path=str(deck), filetype=".pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"))
    db.commit()
    monkeypatch.setattr(template_fill, "_analyze_pptx", lambda _path: {"slide_count": 1, "canvas_px": {"width": 1280, "height": 720}, "slides": [{"slide_index": 1, "slots": [{"slot_id": "s01_sh1", "role": "title", "text": "原标题"}], "tables": [], "charts": []}]})

    store = template_fill.TemplateFillStore()
    template = store.register_template(db, source_file_id=202, user_id=1)
    analyzed = store.analyze_template(db, template_id=template["template_id"], user_id=1)

    assert analyzed["status"] == "analyzed"
    assert analyzed["slide_count"] == 1
    assert analyzed["analysis"]["slides"][0]["slots"][0]["confidence"] > 0


def test_template_api_registers_and_analyzes_for_enabled_owner(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import Base, get_db
    from app.deps import get_current_user
    from app.models import File, User
    from app.PPT_master.template_router import router
    import app.PPT_master.template_fill as template_fill

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    deck = tmp_path / "template.pptx"
    with ZipFile(deck, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>")
        archive.writestr("ppt/presentation.xml", "<p:presentation xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"/>")
    owner = User(id=1, username="123", password_hash="x")
    db.add_all([owner, File(id=203, user_id=1, owner_user_id=1, filename="template.pptx", filepath=str(deck), real_path=str(deck), filetype=".pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")])
    db.commit()
    monkeypatch.setattr(template_fill, "_analyze_pptx", lambda _path: {"slide_count": 1, "canvas_px": {}, "slides": [{"slide_index": 1, "slots": [], "tables": [], "charts": []}]})
    app = FastAPI(); app.include_router(router, prefix="/api/v1")
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    monkeypatch.setenv("PPT_TEMPLATE_FILL_ALLOWED_USERS", "123")
    with TestClient(app) as client:
        created = client.post("/api/v1/ppt-master/templates", json={"source_file_id": 203, "title": "模板"})
        assert created.status_code == 200
        template_id = created.json()["data"]["template_id"]
        analyzed = client.post(f"/api/v1/ppt-master/templates/{template_id}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["data"]["status"] == "analyzed"


def test_fill_plan_transitions_draft_to_confirmed_only_for_template_owner(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from app.database import Base
    from app.models import File, User
    import app.PPT_master.template_fill as template_fill

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine); db = sessionmaker(bind=engine)()
    deck = tmp_path / "template.pptx"
    with ZipFile(deck, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>")
        archive.writestr("ppt/presentation.xml", "<p:presentation xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"/>")
    db.add_all([User(id=1, username="123", password_hash="x"), User(id=2, username="other", password_hash="x")])
    db.add(File(id=204, user_id=1, owner_user_id=1, filename="template.pptx", filepath=str(deck), real_path=str(deck), filetype=".pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")); db.commit()
    monkeypatch.setattr(template_fill, "_analyze_pptx", lambda _path: {"slide_count": 1, "canvas_px": {}, "slides": [{"slide_index": 1, "slots": [{"slot_id": "s01_sh1", "role": "title", "text": "原标题"}], "tables": [], "charts": []}]})
    store = template_fill.TemplateFillStore(); template = store.register_template(db, source_file_id=204, user_id=1); store.analyze_template(db, template_id=template["template_id"], user_id=1)

    plan = store.create_fill_plan(db, template_id=template["template_id"], user_id=1, selected_slides=[1], source_file_ids=[])

    assert plan["status"] == "draft"
    assert store.confirm_fill_plan(db, plan_id=plan["plan_id"], user_id=2) is None
    confirmed = store.confirm_fill_plan(db, plan_id=plan["plan_id"], user_id=1)
    assert confirmed["status"] == "confirmed"


def test_fill_plan_update_requires_matching_revision_and_rejects_confirmed(tmp_path, monkeypatch):
    # lifecycle setup is shared with the preceding plan test; the new contract is optimistic locking.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from app.database import Base
    from app.models import File, User
    import app.PPT_master.template_fill as m
    engine=create_engine("sqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool); Base.metadata.create_all(engine); db=sessionmaker(bind=engine)()
    deck=tmp_path/"t.pptx"
    with ZipFile(deck,"w") as z: z.writestr("[Content_Types].xml","<Types/>"); z.writestr("ppt/presentation.xml","<p:presentation/>")
    db.add(User(id=1,username="123",password_hash="x")); db.add(File(id=205,user_id=1,owner_user_id=1,filename="t.pptx",filepath=str(deck),real_path=str(deck),filetype=".pptx")); db.commit()
    monkeypatch.setattr(m,"_analyze_pptx",lambda _: {"slide_count":1,"slides":[{"slide_index":1,"slots":[],"tables":[],"charts":[]}]})
    s=m.TemplateFillStore(); t=s.register_template(db,source_file_id=205,user_id=1); s.analyze_template(db,template_id=t["template_id"],user_id=1); plan=s.create_fill_plan(db,template_id=t["template_id"],user_id=1,selected_slides=[1],source_file_ids=[])
    with pytest.raises(m.TemplateFillPlanConflict): s.update_fill_plan(db,plan_id=plan["plan_id"],user_id=1,expected_revision=2,plan=plan["plan"])
    updated=s.update_fill_plan(db,plan_id=plan["plan_id"],user_id=1,expected_revision=1,plan=plan["plan"]); assert updated["revision"]==2
    s.confirm_fill_plan(db,plan_id=plan["plan_id"],user_id=1)
    with pytest.raises(m.TemplateFillPlanImmutable): s.update_fill_plan(db,plan_id=plan["plan_id"],user_id=1,expected_revision=2,plan=updated["plan"])


def test_fill_plan_uses_stable_selected_slide_and_slot_contract(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from app.database import Base
    from app.models import File, User
    import app.PPT_master.template_fill as m

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine); db = sessionmaker(bind=engine)()
    deck = tmp_path / "template.pptx"
    with ZipFile(deck, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>"); z.writestr("ppt/presentation.xml", "<p:presentation/>")
    db.add(User(id=1, username="123", password_hash="x"))
    db.add(File(id=206, user_id=1, owner_user_id=1, filename="template.pptx", filepath=str(deck), real_path=str(deck), filetype=".pptx")); db.commit()
    monkeypatch.setattr(m, "_analyze_pptx", lambda _: {"slide_count": 1, "slides": [{"slide_index": 1, "slide_id": "rId7", "slots": [{"slot_id": "slot_title", "shape_id": "42", "role": "title", "text": "原题"}], "tables": [], "charts": []}]})
    store = m.TemplateFillStore(); template = store.register_template(db, source_file_id=206, user_id=1); store.analyze_template(db, template_id=template["template_id"], user_id=1)

    result = store.create_fill_plan(db, template_id=template["template_id"], user_id=1, selected_slides=[1], source_file_ids=[])

    plan = result["plan"]
    assert plan["template_id"] == template["template_id"]
    assert plan["status"] == "draft"
    assert plan["revision"] == 1
    assert plan["selected_slides"] == [{
        "template_slide_id": "rId7", "template_slide_index": 1, "output_order": 1,
        "slot_values": [{"shape_id": "42", "slot_type": "text", "action": "keep", "value": "原题", "source_refs": []}],
    }]


def test_public_fill_plan_converts_only_explicit_replace_and_clear_values():
    from app.PPT_master.template_fill import TemplateFillStore

    plan = {
        "selected_slides": [{
            "template_slide_index": 2, "output_order": 1, "slot_values": [
                {"shape_id": "42", "slot_type": "text", "action": "replace", "value": "新标题", "source_refs": []},
                {"shape_id": "43", "slot_type": "text", "action": "clear", "value": "忽略", "source_refs": []},
                {"shape_id": "44", "slot_type": "text", "action": "keep", "value": "原文", "source_refs": []},
            ],
        }]
    }
    converted = TemplateFillStore._to_upstream_plan(plan)

    assert converted["slides"] == [{"source_slide": 2, "replacements": [
        {"shape_id": "42", "text": "新标题"}, {"shape_id": "43", "text": ""}
    ], "table_edits": [], "chart_edits": []}]



def test_public_plan_flattens_analyzer_table_rows_and_supports_controlled_clear():
    from app.PPT_master.template_fill import TemplateFillStore
    plan = {"selected_slides": [{"template_slide_index": 1, "output_order": 1, "slot_values": [
        {"shape_id": "5", "slot_type": "table", "action": "replace", "value": [[{"row": 0, "col": 0, "text": "Updated"}]], "source_refs": []},
        {"shape_id": "4", "slot_type": "chart", "action": "clear", "value": {"categories": ["Q1"], "series": [{"name": "Revenue", "values": [10]}]}, "source_refs": []},
    ]}]}
    converted = TemplateFillStore._to_upstream_plan(plan)["slides"][0]
    assert converted["table_edits"] == [{"shape_id": "5", "cells": [{"row": 0, "col": 0, "text": "Updated"}]}]
    assert converted["chart_edits"] == [{"shape_id": "4", "categories": [""], "series": [{"name": "", "values": [0]}]}]

def test_confirmed_plan_apply_creates_append_only_output_task(tmp_path, monkeypatch):
    from datetime import datetime
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from app.database import Base
    from app.models import File, User
    import app.PPT_master.template_fill as m

    engine=create_engine("sqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool); Base.metadata.create_all(engine); db=sessionmaker(bind=engine)()
    deck=tmp_path/"template.pptx"
    with ZipFile(deck,"w") as z:
        z.writestr("[Content_Types].xml","<Types/>"); z.writestr("ppt/presentation.xml","<p:presentation/>"); z.writestr("ppt/slides/slide1.xml", "<p:sld/>")
    db.add(User(id=1,username="123",password_hash="x")); db.add(File(id=207,user_id=1,owner_user_id=1,filename="template.pptx",filepath=str(deck),real_path=str(deck),filetype=".pptx")); db.commit()
    monkeypatch.setattr(m,"_analyze_pptx",lambda _: {"slide_count":1,"slides":[{"slide_index":1,"slots":[],"tables":[],"charts":[]}]})
    monkeypatch.setattr(m,"_check_plan",lambda library, plan: {"summary":{"error":0},"results":[]},raising=False)
    def fake_apply(source, plan, output, **kwargs):
        output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(deck.read_bytes() + b"\nfilled")
    monkeypatch.setattr(m,"_apply_plan",fake_apply,raising=False)
    # This lifecycle test deliberately uses a synthetic ZIP; strict OOXML
    # validation is separately covered by the real native fixture below.
    monkeypatch.setattr(m.TemplateFillStore, "_validate_output", staticmethod(lambda path, **_: {"zip_valid": True, "xml_valid": True, "source_sha256": "old", "output_sha256": "new"}))
    def fake_register(self, db, owner_user_id, project_id, task_id, real_path, **kwargs):
        row=File(user_id=owner_user_id,owner_user_id=owner_user_id,filename="filled.pptx",filepath=str(real_path),real_path=str(real_path),filetype=".pptx",project_id=project_id,task_id=task_id,sha256="new-sha")
        db.add(row); db.commit(); db.refresh(row); return row
    monkeypatch.setattr(m.ArtifactService,"register_pptx",fake_register,raising=False)
    store=m.TemplateFillStore(); template=store.register_template(db,source_file_id=207,user_id=1); store.analyze_template(db,template_id=template["template_id"],user_id=1)
    plan=store.create_fill_plan(db,template_id=template["template_id"],user_id=1,selected_slides=[1],source_file_ids=[]); store.confirm_fill_plan(db,plan_id=plan["plan_id"],user_id=1)

    task=store.apply_fill_plan(db,plan_id=plan["plan_id"],user_id=1,expected_revision=1)

    assert task["status"] == "completed", task
    assert task["source_file_id"] == 207
    assert task["output_file_id"] != 207
    assert task["artifact_manifest"]["fill_plan_revision"] == 1


def test_apply_route_rejects_unconfirmed_plan_with_explicit_status(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import Base, get_db
    from app.deps import get_current_user
    from app.models import File, User
    from app.PPT_master.template_router import router
    import app.PPT_master.template_fill as m

    engine=create_engine("sqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool); Base.metadata.create_all(engine); db=sessionmaker(bind=engine)()
    deck=tmp_path/"template.pptx"
    with ZipFile(deck,"w") as z: z.writestr("[Content_Types].xml","<Types/>"); z.writestr("ppt/presentation.xml","<p:presentation/>")
    owner=User(id=1,username="123",password_hash="x"); db.add_all([owner,File(id=208,user_id=1,owner_user_id=1,filename="template.pptx",filepath=str(deck),real_path=str(deck),filetype=".pptx")]); db.commit()
    monkeypatch.setattr(m,"_analyze_pptx",lambda _: {"slide_count":1,"slides":[{"slide_index":1,"slots":[],"tables":[],"charts":[]}]})
    store=m.TemplateFillStore(); t=store.register_template(db,source_file_id=208,user_id=1); store.analyze_template(db,template_id=t["template_id"],user_id=1); plan=store.create_fill_plan(db,template_id=t["template_id"],user_id=1,selected_slides=[1],source_file_ids=[])
    app=FastAPI();app.include_router(router,prefix="/api/v1")
    def override_db():
        yield db
    app.dependency_overrides[get_db]=override_db;app.dependency_overrides[get_current_user]=lambda: owner
    monkeypatch.setenv("PPT_TEMPLATE_FILL_ALLOWED_USERS","123")
    with TestClient(app) as client:
        response=client.post(f"/api/v1/ppt-master/fill-plans/{plan['plan_id']}/apply",json={"expected_revision":1})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "template_fill_plan_not_confirmed"


def test_template_analysis_persists_owner_scoped_preview_manifest_once(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from app.database import Base
    from app.models import File, User
    import app.PPT_master.template_fill as m

    engine=create_engine("sqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool); Base.metadata.create_all(engine); db=sessionmaker(bind=engine)()
    deck=tmp_path/"template.pptx"; image=tmp_path/"page-1.png"
    with ZipFile(deck,"w") as z: z.writestr("[Content_Types].xml","<Types/>");z.writestr("ppt/presentation.xml","<p:presentation/>")
    image.write_bytes(b"preview")
    db.add(User(id=1,username="123",password_hash="x")); db.add(File(id=209,user_id=1,owner_user_id=1,filename="template.pptx",filepath=str(deck),real_path=str(deck),filetype=".pptx")); db.commit()
    monkeypatch.setattr(m,"_analyze_pptx",lambda _: {"slide_count":1,"slides":[{"slide_index":1,"slots":[],"tables":[],"charts":[]}]})
    calls=[]
    def render(source, target, count):
        calls.append((source,target,count)); return [image]
    monkeypatch.setattr(m,"_render_template_previews",render,raising=False)
    store=m.TemplateFillStore();template=store.register_template(db,source_file_id=209,user_id=1)

    first=store.analyze_template(db,template_id=template["template_id"],user_id=1)
    second=store.analyze_template(db,template_id=template["template_id"],user_id=1)

    assert len(calls) == 1
    previews=first["preview_manifest"]["slides"]
    assert previews[0]["preview_file_id"]
    assert previews[0]["download_url"].endswith("/download")
    assert second["preview_manifest"] == first["preview_manifest"]


def test_template_slides_include_controlled_preview_reference(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from zipfile import ZipFile
    from app.database import Base
    from app.models import File, User
    import app.PPT_master.template_fill as m
    engine=create_engine("sqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool); Base.metadata.create_all(engine); db=sessionmaker(bind=engine)()
    deck=tmp_path/"template.pptx"
    with ZipFile(deck,"w") as z:z.writestr("[Content_Types].xml","<Types/>");z.writestr("ppt/presentation.xml","<p:presentation/>")
    db.add(User(id=1,username="123",password_hash="x"));db.add(File(id=210,user_id=1,owner_user_id=1,filename="template.pptx",filepath=str(deck),real_path=str(deck),filetype=".pptx"));db.commit()
    monkeypatch.setattr(m,"_analyze_pptx",lambda _: {"slide_count":1,"slides":[{"slide_index":1,"slots":[],"tables":[],"charts":[]}]})
    s=m.TemplateFillStore();t=s.register_template(db,source_file_id=210,user_id=1);s.analyze_template(db,template_id=t["template_id"],user_id=1)
    payload=s.get_template_slides(db,template_id=t["template_id"],user_id=1)
    assert payload[0]["preview_file_id"]
    assert payload[0]["download_url"].endswith("/download")


def test_slot_candidate_inference_uses_placeholder_name_geometry_font_and_page_role():
    from app.PPT_master.template_fill import _with_slot_confidence
    library = {"slides": [{"slide_index": 1, "page_type": "cover", "slots": [
        {"slot_id": "s01_sh42", "shape_id": "42", "role": "title", "shape_name": "Title 1", "placeholder": {"type": "title", "idx": 0}, "text": "季度汇报", "geometry": {"x": 30, "y": 40, "width": 900, "height": 100}, "text_metrics": {"font_size_px": 40}},
        {"slot_id": "s01_sh43", "shape_id": "43", "role": "label", "shape_name": "Legal notice", "text": "机密", "geometry": {"x": 30, "y": 680, "width": 180, "height": 20}, "text_metrics": {"font_size_px": 8}},
    ]}]}

    result = _with_slot_confidence(library)

    title, notice = result["slides"][0]["slots"]
    assert title["fillable"] is True
    assert title["confidence"] >= 0.9
    assert "placeholder:title" in title["inference_reasons"]
    assert notice["fillable"] is False
    assert "small_footer_or_legal" in notice["inference_reasons"]


def test_analysis_enrichment_records_slide_layout_and_theme_without_source_path(tmp_path):
    from zipfile import ZipFile
    from app.PPT_master.template_fill import _enrich_template_library
    deck=tmp_path/"layout.pptx"
    ns_p="http://schemas.openxmlformats.org/presentationml/2006/main"; ns_r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"; ns_rel="http://schemas.openxmlformats.org/package/2006/relationships"; ns_a="http://schemas.openxmlformats.org/drawingml/2006/main"
    with ZipFile(deck,"w") as z:
        z.writestr("ppt/presentation.xml", f'<p:presentation xmlns:p="{ns_p}" xmlns:r="{ns_r}"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>')
        z.writestr("ppt/_rels/presentation.xml.rels", f'<Relationships xmlns="{ns_rel}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>')
        z.writestr("ppt/slides/slide1.xml", f'<p:sld xmlns:p="{ns_p}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="42" name="Title 1"/><p:nvPr><p:ph type="title" idx="0"/></p:nvPr></p:nvSpPr></p:sp></p:spTree></p:cSld></p:sld>')
        z.writestr("ppt/slides/_rels/slide1.xml.rels", f'<Relationships xmlns="{ns_rel}"><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>')
        z.writestr("ppt/slideLayouts/slideLayout1.xml", f'<p:sldLayout xmlns:p="{ns_p}"/>')
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", f'<Relationships xmlns="{ns_rel}"><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>')
        z.writestr("ppt/slideMasters/slideMaster1.xml", f'<p:sldMaster xmlns:p="{ns_p}"/>')
        z.writestr("ppt/theme/theme1.xml", f'<a:theme xmlns:a="{ns_a}"><a:themeElements><a:fontScheme name="x"><a:majorFont><a:latin typeface="Aptos"/></a:majorFont></a:fontScheme><a:clrScheme name="x"><a:dk1><a:srgbClr val="000000"/></a:dk1></a:clrScheme></a:themeElements></a:theme>')
    library={"source_pptx":"hidden", "slide_count":1,"slides":[{"slide_index":1,"slots":[{"slot_id":"s01_sh42","role":"title_candidate","text":"标题","geometry":{},"text_metrics":{}}],"tables":[],"charts":[]}]}
    result=_enrich_template_library(deck,library)
    slide=result["slides"][0]
    assert "source_pptx" not in result
    assert slide["slide_id"] == "rId1"
    assert slide["layout"]["master_part"] == "ppt/slideMasters/slideMaster1.xml"
    assert slide["slots"][0]["placeholder"] == {"type":"title","idx":"0"}
    assert result["theme"]["major_font"] == "Aptos"


def test_image_replace_updates_only_selected_picture_relationship(tmp_path):
    from zipfile import ZipFile
    from app.PPT_master.template_fill import _replace_output_images
    pptx=tmp_path/"out.pptx"; image=tmp_path/"replacement.png"; image.write_bytes(b"new-image")
    p="http://schemas.openxmlformats.org/presentationml/2006/main"; a="http://schemas.openxmlformats.org/drawingml/2006/main"; r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"; rel="http://schemas.openxmlformats.org/package/2006/relationships"
    with ZipFile(pptx,"w") as z:
        z.writestr("[Content_Types].xml",f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("ppt/presentation.xml",f'<p:presentation xmlns:p="{p}"/>')
        z.writestr("ppt/slides/slide2.xml",f'<p:sld xmlns:p="{p}" xmlns:a="{a}" xmlns:r="{r}"><p:cSld><p:spTree><p:pic><p:nvPicPr><p:cNvPr id="42" name="Hero"/></p:nvPicPr><p:blipFill><a:blip r:embed="rId3"/></p:blipFill></p:pic></p:spTree></p:cSld></p:sld>')
        z.writestr("ppt/slides/_rels/slide2.xml.rels",f'<Relationships xmlns="{rel}"><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/old.png"/></Relationships>')
        z.writestr("ppt/media/old.png",b"old-image")
    _replace_output_images(pptx, [{"output_slide_position":1,"shape_id":"42","image_path":image}])
    with ZipFile(pptx) as z:
        rels=z.read("ppt/slides/_rels/slide2.xml.rels")
        assert b"old.png" not in rels
        targets=[n for n in z.namelist() if n.startswith("ppt/media/template-fill-")]
        assert len(targets)==1 and z.read(targets[0]) == b"new-image"
        assert z.read("ppt/media/old.png") == b"old-image"


def test_real_native_fixture_preserves_chart_table_media_and_master_layout(tmp_path):
    from pathlib import Path
    from zipfile import ZipFile
    from app.PPT_master.template_fill import _analyze_pptx, _enrich_template_library, _with_slot_confidence, TemplateFillStore, _apply_plan
    source = Path(__file__).parent / "fixtures" / "p2_template_fill_native.pptx"
    library = _with_slot_confidence(_enrich_template_library(source, _analyze_pptx(source)))
    slides = []
    for order, slide in enumerate(library["slides"], start=1):
        values = [{"shape_id": item["shape_id"], "slot_type": "text", "action": "replace" if item["role"].startswith("title") else "keep", "value": "P2 Filled" if item["role"].startswith("title") else item["text"], "source_refs": []} for item in slide["slots"]]
        values.extend({"shape_id": item["shape_id"], "slot_type": "table", "action": "replace", "value": [{"row": 0, "col": 0, "text": "Updated Table"}], "source_refs": []} for item in slide["tables"])
        values.extend({"shape_id": item["shape_id"], "slot_type": "chart", "action": "replace", "value": {"categories": ["A", "B", "C"], "series": [{"name": "Updated Series", "values": [2, 4, 8]}]}, "source_refs": []} for item in slide["charts"])
        slides.append({"template_slide_index": slide["slide_index"], "output_order": order, "slot_values": values})
    output = tmp_path / "filled.pptx"
    _apply_plan(source, TemplateFillStore._to_upstream_plan({"selected_slides": slides}), output, transition="keep")
    with ZipFile(source) as original, ZipFile(output) as result:
        names = result.namelist()
        assert sum(name.startswith("ppt/slides/slide") and name.endswith(".xml") for name in names) == 3
        assert any(name.startswith("ppt/charts/chart") for name in names)
        assert any(name.startswith("ppt/embeddings/") for name in names)
        assert any(name.startswith("ppt/media/") for name in names)
        assert any(name.startswith("ppt/slideMasters/") for name in names)
        assert any(b"Updated Table" in result.read(name) for name in names if name.startswith("ppt/slides/"))
        assert any(b"Updated Series" in result.read(name) for name in names if name.startswith("ppt/charts/"))
        assert original.read("ppt/slides/slide2.xml") != result.read(next(name for name in names if name.endswith("slide5.xml")))
    validation = TemplateFillStore._validate_output(output, expected_slide_count=3, source_sha256=__import__("hashlib").sha256(source.read_bytes()).hexdigest())
    assert validation["zip_valid"] and validation["xml_valid"] and validation["relationship_valid"]
    assert validation["office_render_valid"] is True
    assert validation["master_count"] >= 1 and validation["layout_count"] >= 1
    assert validation["chart_count"] >= 1 and validation["table_count"] >= 1
    assert validation["media_count"] >= 1 and validation["embedding_count"] >= 1
    assert validation["external_relationship_count"] == 0
