"""Safe defaults: a server started without APP_ENV is production, and production refuses unsafe settings."""

from app.config import Settings, production_problems
from app.routers import auth


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_defaults_are_production_without_demo_login():
    s = _settings()
    assert s.app_env == "production"
    assert s.auth_demo_login is False


def test_production_with_repo_defaults_lists_every_problem():
    problems = "\n".join(production_problems(_settings()))
    for name in ("POSTGRES_PASSWORD", "NEO4J_PASSWORD", "SQL_AGENT_DB_PASSWORD"):
        assert name in problems
    for name in ("AUTH_COOKIE_SECURE", "FRONTEND_ORIGIN", "OPENAI_API_KEY"):
        assert name in problems


def test_production_with_real_settings_starts():
    s = _settings(
        postgres_password="a-real-one",
        neo4j_password="another-real-one",
        sql_agent_db_password="and-a-third",
        auth_cookie_secure=True,
        frontend_origin="https://lms.example.com",
        openai_api_key="sk-live",
    )
    assert production_problems(s) == []
    assert production_problems(s.model_copy(update={"mcp_notes_dir": "/srv/notes"}))  # dev only


def test_dev_and_test_are_not_checked():
    assert production_problems(_settings(app_env="dev")) == []
    assert production_problems(_settings(app_env="test")) == []


def test_demo_login_needs_dev_and_the_flag(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(app_env="production", auth_demo_login=True))
    assert auth._demo_enabled() is False
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(app_env="dev"))
    assert auth._demo_enabled() is False
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(app_env="dev", auth_demo_login=True))
    assert auth._demo_enabled() is True
