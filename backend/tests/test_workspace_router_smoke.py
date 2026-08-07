"""Smoke test for workspace router registration."""
def test_workspace_router_imports():
    """Verify workspace_router can be imported."""
    from app.PPT_master.workspace_router import router
    assert router is not None
    assert hasattr(router, 'routes')


def test_workspace_router_registered_in_main():
    """Verify workspace routes are registered in main router."""
    from app.PPT_master.router import router as main_router
    
    # Check that workspace routes are present
    route_paths = [r.path for r in main_router.routes]
    assert any('/workspaces' in path for path in route_paths), "Workspace routes not registered"
