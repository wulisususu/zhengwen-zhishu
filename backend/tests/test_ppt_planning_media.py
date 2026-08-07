from app.PPT_master.planning_media import build_image_slots

def test_image_slots_assign_authorized_assets_without_network_urls():
    slots = build_image_slots([{"asset_id":"pptimg_a","file_id":9,"width":1600,"height":900,"resource":"pptimg_a.png"}], page_count=3)
    assert slots == [{"slide_index":1,"asset_id":"pptimg_a","file_id":9,"resource":"pptimg_a.png","purpose":"来源图片","preferred_source":"provided","aspect_ratio":"16:9","position":"right"}]


def test_inject_slot_image_adds_safe_svg_image(tmp_path):
    from app.PPT_master.planning_media import inject_slot_image
    page = tmp_path / "page.svg"
    page.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><text x="10" y="10">x</text></svg>', encoding="utf-8")
    assert inject_slot_image(page, {"resource":"pptimg_a.png", "position":"right"}) is True
    output = page.read_text(encoding="utf-8")
    assert 'href="images/pptimg_a.png"' in output
    assert '<image' in output


def test_authorized_project_image_resource_passes_svg_security_gate(tmp_path):
    from app.PPT_master.security import validate_svg_text

    image = tmp_path / "images" / "pptimg_a.png"
    image.parent.mkdir()
    image.write_bytes(b"png")
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><image href="images/pptimg_a.png"/></svg>'

    assert validate_svg_text(svg, project_root=tmp_path, registered_resources={image}) == []
    assert validate_svg_text(svg, project_root=tmp_path) == ["svg_unregistered_resource_forbidden"]
