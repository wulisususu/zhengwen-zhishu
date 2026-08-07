from scripts.incremental_ppt_smoke import _inspect_svg


def test_svg_namespace_is_not_mistaken_for_external_resource():
    content = (
        b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1280 720'>"
        b"<text x='20' y='40'>Safe</text></svg>"
    )

    assert _inspect_svg(content)["forbidden_resource_absent"] is True


def test_external_svg_resource_is_still_detected():
    content = (
        b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1280 720'>"
        b"<image href='https://example.invalid/a.png'/></svg>"
    )

    assert _inspect_svg(content)["forbidden_resource_absent"] is False
