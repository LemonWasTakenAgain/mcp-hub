"""Test marketing tools with mocked database sessions."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_hub.models.marketing import MarketingCampaign, MarketingMetric, MarketingProject
from mcp_hub.tools.marketing_tools import (
    add_metric,
    create_campaign,
    create_project,
    dashboard,
    get_campaign,
    get_project,
    list_campaigns,
    list_projects,
    query_metrics,
    update_campaign,
    update_project,
)


def _make_project(**overrides) -> MarketingProject:
    """Create a MarketingProject instance with sensible defaults."""
    now = datetime.now(UTC)
    defaults = {
        "id": 1,
        "name": "Test App",
        "slug": "test-app",
        "description": "A test application",
        "target_audience": "Developers",
        "value_prop": "Saves time",
        "status": "idea",
        "website_url": None,
        "repo_url": None,
        "gitlab_project_id": None,
        "metadata_": None,
        "created_at": now,
        "updated_at": now,
        "campaigns": [],
    }
    defaults.update(overrides)
    p = MagicMock(spec=MarketingProject)
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


def _make_campaign(**overrides) -> MarketingCampaign:
    """Create a MarketingCampaign instance with sensible defaults."""
    now = datetime.now(UTC)
    defaults = {
        "id": 1,
        "project_id": 1,
        "name": "Launch Campaign",
        "description": None,
        "channel": "social",
        "platform": "twitter",
        "status": "planned",
        "start_date": None,
        "end_date": None,
        "budget_cents": 10000,
        "spend_cents": 0,
        "revenue_cents": 0,
        "goal": "Get 100 signups",
        "outcome": None,
        "lessons_learned": None,
        "source": None,
        "metadata_": None,
        "created_at": now,
        "updated_at": now,
        "metrics": [],
    }
    defaults.update(overrides)
    c = MagicMock(spec=MarketingCampaign)
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


def _make_metric(**overrides) -> MarketingMetric:
    """Create a MarketingMetric instance with sensible defaults."""
    now = datetime.now(UTC)
    defaults = {
        "id": 1,
        "campaign_id": 1,
        "metric_date": date.today(),
        "impressions": 1000,
        "clicks": 50,
        "conversions": 5,
        "spend_cents": 500,
        "revenue_cents": 1000,
        "source": None,
        "notes": None,
        "created_at": now,
    }
    defaults.update(overrides)
    m = MagicMock(spec=MarketingMetric)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _mock_session():
    """Create a mock async session context manager."""
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


# -- create_project tests --


@pytest.mark.asyncio
async def test_create_project_success():
    ctx, session = _mock_session()

    # Mock slug uniqueness check
    slug_check = MagicMock()
    slug_check.scalar_one_or_none.return_value = None

    async def fake_refresh(obj):
        obj.id = 10
        obj.slug = "test-app"
        obj.status = "idea"
        obj.name = "Test App"

    session.execute = AsyncMock(return_value=slug_check)
    session.refresh = fake_refresh

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await create_project("Test App", description="A test", status="idea")

    assert "Project #10 created" in result
    assert "test-app" in result
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_project_empty_name():
    result = await create_project("")
    assert "Error" in result
    assert "name" in result


@pytest.mark.asyncio
async def test_create_project_invalid_status():
    result = await create_project("Test App", status="invalid")
    assert "Error" in result
    assert "invalid status" in result


@pytest.mark.asyncio
async def test_create_project_invalid_website_url():
    result = await create_project("Test App", website_url="not-a-url")
    assert "Error" in result
    assert "website_url" in result


# -- update_project tests --


@pytest.mark.asyncio
async def test_update_project_success():
    ctx, session = _mock_session()
    project = _make_project(id=1, status="idea")
    session.get = AsyncMock(return_value=project)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await update_project(1, status="building", name="New Name")

    assert "updated" in result
    assert "status → building" in result
    assert "name" in result
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_project_not_found():
    ctx, session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await update_project(999, status="building")

    assert "not found" in result


@pytest.mark.asyncio
async def test_update_project_no_fields():
    ctx, session = _mock_session()
    project = _make_project(id=1)
    session.get = AsyncMock(return_value=project)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await update_project(1)

    assert "Error" in result
    assert "no fields" in result


# -- get_project tests --


@pytest.mark.asyncio
async def test_get_project_found():
    ctx, session = _mock_session()
    campaign = _make_campaign(id=1, name="Promo", status="active", channel="social", platform=None)
    project = _make_project(id=1, campaigns=[campaign])
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = project
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await get_project(1)

    assert "# Project #1" in result
    assert "Test App" in result
    assert "Promo" in result


@pytest.mark.asyncio
async def test_get_project_not_found():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await get_project(999)

    assert "not found" in result


# -- list_projects tests --


@pytest.mark.asyncio
async def test_list_projects_success():
    ctx, session = _mock_session()
    projects = [
        _make_project(id=1),
        _make_project(id=2, name="App Two", slug="app-two", status="building"),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = projects
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await list_projects()

    assert "#1" in result
    assert "#2" in result
    assert "2" in result


@pytest.mark.asyncio
async def test_list_projects_empty():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await list_projects(status="launched")

    assert "No projects found" in result


@pytest.mark.asyncio
async def test_list_projects_invalid_status():
    result = await list_projects(status="bogus")
    assert "Error" in result
    assert "invalid status" in result


# -- create_campaign tests --


@pytest.mark.asyncio
async def test_create_campaign_success():
    ctx, session = _mock_session()
    project = _make_project(id=1)
    session.get = AsyncMock(return_value=project)

    async def fake_refresh(obj):
        obj.id = 5
        obj.name = "Social Push"
        obj.channel = "social"
        obj.status = "planned"

    session.refresh = fake_refresh

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await create_campaign(1, "Social Push", "social", budget_cents=5000)

    assert "Campaign #5 created" in result
    assert "social" in result
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_campaign_invalid_channel():
    result = await create_campaign(1, "Test", "carrier_pigeon")
    assert "Error" in result
    assert "invalid channel" in result


@pytest.mark.asyncio
async def test_create_campaign_project_not_found():
    ctx, session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await create_campaign(999, "Test", "social")

    assert "not found" in result


@pytest.mark.asyncio
async def test_create_campaign_negative_budget():
    result = await create_campaign(1, "Test", "social", budget_cents=-100)
    assert "Error" in result
    assert "negative" in result


# -- update_campaign tests --


@pytest.mark.asyncio
async def test_update_campaign_success():
    ctx, session = _mock_session()
    campaign = _make_campaign(id=1, status="planned", budget_cents=10000, spend_cents=0)
    session.get = AsyncMock(return_value=campaign)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await update_campaign(1, status="active", spend_cents=2000)

    assert "updated" in result
    assert "status → active" in result


@pytest.mark.asyncio
async def test_update_campaign_spend_exceeds_budget_warning():
    ctx, session = _mock_session()
    campaign = _make_campaign(id=1, budget_cents=1000, spend_cents=1500)
    session.get = AsyncMock(return_value=campaign)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await update_campaign(1, spend_cents=1500)

    assert "Warning: spend exceeds budget" in result


@pytest.mark.asyncio
async def test_update_campaign_not_found():
    ctx, session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await update_campaign(999, status="active")

    assert "not found" in result


@pytest.mark.asyncio
async def test_update_campaign_negative_spend_rejected():
    result = await update_campaign(1, spend_cents=-50)
    assert "Error" in result
    assert "negative" in result


# -- get_campaign tests --


@pytest.mark.asyncio
async def test_get_campaign_found():
    ctx, session = _mock_session()
    metric = _make_metric(impressions=500, clicks=25, conversions=3)
    campaign = _make_campaign(id=2, name="Email Drip", metrics=[metric])
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = campaign
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await get_campaign(2)

    assert "# Campaign #2" in result
    assert "Email Drip" in result
    assert "500" in result  # impressions


@pytest.mark.asyncio
async def test_get_campaign_not_found():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await get_campaign(999)

    assert "not found" in result


# -- list_campaigns tests --


@pytest.mark.asyncio
async def test_list_campaigns_success():
    ctx, session = _mock_session()
    project = _make_project(id=1)
    campaigns = [_make_campaign(id=1), _make_campaign(id=2, name="Email Blast", channel="email")]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = campaigns

    # get() returns project, execute() returns campaign list
    session.get = AsyncMock(return_value=project)
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await list_campaigns(project_id=1)

    assert "#1" in result
    assert "#2" in result


@pytest.mark.asyncio
async def test_list_campaigns_project_not_found():
    ctx, session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await list_campaigns(project_id=999)

    assert "not found" in result


# -- add_metric tests --


@pytest.mark.asyncio
async def test_add_metric_success():
    ctx, session = _mock_session()
    campaign = _make_campaign(id=1)
    session.get = AsyncMock(return_value=campaign)

    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=no_existing)

    async def fake_refresh(obj):
        obj.id = 99

    session.refresh = fake_refresh

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await add_metric(1, "2026-01-15", impressions=1000, clicks=50)

    assert "added" in result
    assert "#99" in result or "2026-01-15" in result
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_add_metric_upsert():
    ctx, session = _mock_session()
    campaign = _make_campaign(id=1)
    existing_metric = _make_metric(id=5, impressions=100)
    session.get = AsyncMock(return_value=campaign)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_metric
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await add_metric(1, "2026-01-15", impressions=2000, clicks=100)

    assert "updated" in result
    assert existing_metric.impressions == 2000


@pytest.mark.asyncio
async def test_add_metric_invalid_date():
    result = await add_metric(1, "not-a-date")
    assert "Error" in result
    assert "date" in result.lower()


@pytest.mark.asyncio
async def test_add_metric_negative_spend():
    result = await add_metric(1, "2026-01-15", spend_cents=-100)
    assert "Error" in result
    assert "negative" in result


# -- query_metrics tests --


@pytest.mark.asyncio
async def test_query_metrics_success():
    ctx, session = _mock_session()
    metrics = [
        _make_metric(id=1, impressions=1000, clicks=50, conversions=5),
        _make_metric(id=2, campaign_id=2, impressions=500, clicks=20, conversions=2),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = metrics
    session.get = AsyncMock(return_value=_make_campaign(id=1))
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await query_metrics(campaign_id=1)

    assert "2 entries" in result
    assert "1,500" in result  # total impressions


@pytest.mark.asyncio
async def test_query_metrics_empty():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await query_metrics()

    assert "No metrics found" in result


# -- dashboard tests --


@pytest.mark.asyncio
async def test_dashboard_with_projects():
    ctx, session = _mock_session()
    today = date.today()
    recent_date = today - timedelta(days=10)

    metric = _make_metric(metric_date=recent_date)
    active_campaign = _make_campaign(id=1, status="active", metrics=[metric])
    green_project = _make_project(id=1, name="Green Project", campaigns=[active_campaign])

    planned_campaign = _make_campaign(id=2, status="planned", metrics=[])
    yellow_project = _make_project(
        id=2, name="Yellow Project", slug="yellow", campaigns=[planned_campaign]
    )

    red_project = _make_project(id=3, name="Red Project", slug="red", campaigns=[])

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [green_project, yellow_project, red_project]
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await dashboard()

    assert "GREEN" in result
    assert "YELLOW" in result
    assert "RED" in result
    assert "3 projects" in result


@pytest.mark.asyncio
async def test_dashboard_empty():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.marketing_tools.async_session", return_value=ctx):
        result = await dashboard()

    assert "No marketing projects" in result
