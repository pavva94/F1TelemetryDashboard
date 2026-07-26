from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_static_frontend_routes_stay_on_the_current_document() -> None:
    index = (FRONTEND / "index.html").read_text()
    routing = (FRONTEND / "routing.js").read_text()
    season = (FRONTEND / "season.js").read_text()

    assert 'href="?view=season"' in index
    assert 'href="?view=race"' in index
    assert "`${locationLike.pathname}?${query}`" in routing
    assert 'return `/season?' not in season
    assert 'return `/race?' not in season


def test_shared_router_loads_before_route_consumers() -> None:
    index = (FRONTEND / "index.html").read_text()

    assert index.index('src="assets/routing.js"') < index.index('src="assets/app.js"')
    assert index.index('src="assets/routing.js"') < index.index('src="assets/season.js"')
