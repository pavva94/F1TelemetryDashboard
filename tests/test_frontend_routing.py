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


def test_season_analysis_is_the_default_and_first_navigation_item() -> None:
    index = (FRONTEND / "index.html").read_text()
    routing = (FRONTEND / "routing.js").read_text()

    assert routing.index('legacyPath === "race" ? "race" : "season"') >= 0
    assert index.index('data-route="season"') < index.index('data-route="race"')
    assert '<section id="race-page" class="dashboard analysis-page" aria-live="polite" hidden>' in index
    assert '<section id="season-page" class="season-page analysis-page" aria-live="polite">' in index


def test_shared_router_loads_before_route_consumers() -> None:
    index = (FRONTEND / "index.html").read_text()

    assert index.index('src="assets/routing.js"') < index.index('src="assets/app.js"')
    assert index.index('src="assets/routing.js"') < index.index('src="assets/season.js"')
    assert index.index('src="assets/team-colors.js?v=20260727"') < index.index('src="assets/app.js"')
    assert index.index('src="assets/team-colors.js?v=20260727"') < index.index('src="assets/season.js"')


def test_official_team_palette_is_shared_by_both_analysis_pages() -> None:
    palette = (FRONTEND / "team-colors.js").read_text()
    app = (FRONTEND / "app.js").read_text()
    season = (FRONTEND / "season.js").read_text()

    for color in (
        "#DC0000", "#C0C0C0", "#15151E", "#0A1B40", "#FFD700",
        "#FF8700", "#005F41", "#005BA9", "#FF80BD", "#1868DB",
        "#9C9FA2", "#01C00E", "#C8CED4", "#F50537", "#6C98FF",
    ):
        assert color in palette
    assert "window.F1Teams" in palette
    assert "teamColor(item.team)" in app
    assert "entityColour(item.label, options.entityKey)" in season


def test_season_frontend_polls_status_without_restarting_analysis() -> None:
    season = (FRONTEND / "season.js").read_text()

    assert "/api/season/${encodeURIComponent(year)}/analysis" in season
    assert "/api/season/${encodeURIComponent(year)}/status" in season
    assert "This calculation is shared across all visitors." in season
    assert "Updated Round" in season


def test_plain_language_guidance_covers_both_analysis_pages() -> None:
    index = (FRONTEND / "index.html").read_text()
    app = (FRONTEND / "app.js").read_text()
    season = (FRONTEND / "season.js").read_text()

    assert "How to use Season Analysis" in index
    assert "How to use Race Analysis" in index
    assert "A positive delta means the compared driver took longer" in index
    assert "At 0% the entry matches the fastest reference" in index
    assert "Qualifying H2H is sessions won over comparable rounds" in index
    assert "This is an estimate, not measured tyre wear" in index
    assert index.count('class="data-explanation"') >= 25
    assert "Lane is the measured time from pit entry to pit exit" in app
    assert "overlapping ranges mean the model cannot clearly separate" in season


def test_public_brand_uses_apex_signal_and_credits_fastf1_as_data_source() -> None:
    index = (FRONTEND / "index.html").read_text()

    assert "<h1>Apex Signal</h1>" in index
    assert "<title>Apex Signal — Formula 1 Performance Intelligence</title>" in index
    assert "Powered by FastF1 data" in index
    assert "<h1>FastF1" not in index


def test_reliability_tables_have_legends_and_metric_first_ordering() -> None:
    index = (FRONTEND / "index.html").read_text()
    season = (FRONTEND / "season.js").read_text()

    assert "Default order: highest reliability" in index
    assert "Rows ordered by reliability" in index
    assert "Default order: fastest median time" in index
    for code in ("FIN", "LAP", "MEC", "INC", "RET", "DNS", "DSQ", "OTH"):
        assert f"<b>{code}</b>" in index
    assert 'if (/lapp/i.test(status)) return "LAP"' in season
    assert 'if (/retired/i.test(status)) return "RET"' in season
    assert "compareNullableDescending(a.percentage, b.percentage)" in season
    assert "compareNullable(a.medianPitLane, b.medianPitLane)" in season
    assert 'table(["Rank", "Team", "Starts"' in season
    assert 'table(["Rank", "Team", "Measured stops"' in season


def test_season_showcase_exposes_only_the_year_selector() -> None:
    index = (FRONTEND / "index.html").read_text()
    season = (FRONTEND / "season.js").read_text()

    assert '<form id="season-filters" class="season-picker">' in index
    assert "<span>Season</span>" in index
    assert "<span>Start round</span>" not in index
    assert "<span>Quick range</span>" not in index
    assert "<span>Teams</span>" not in index
    assert "Apply filters" not in index
    assert "Choose a season." in index
    assert "restoreControls" not in season
    assert "start: elements.start.value" not in season
