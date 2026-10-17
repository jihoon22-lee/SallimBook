import pytest

from sallimbook.config import Settings


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch):
    monkeypatch.delenv("SALLIMBOOK_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SALLIMBOOK_ALLOWED_ORIGINS", raising=False)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_defaults_have_no_allowed_origins(environment):
    assert Settings(environment=environment, _env_file=None).allowed_origins == []


@pytest.mark.parametrize("environment", ["development", "test"])
def test_development_defaults_keep_only_the_dedicated_local_origins(environment):
    assert Settings(environment=environment, _env_file=None).allowed_origins == [
        "http://localhost:18742", "http://127.0.0.1:18742"
    ]


def test_explicit_empty_origins_disable_development_defaults():
    settings = Settings(environment="development", allowed_origins=[], _env_file=None)
    assert settings.allowed_origins == []


def test_settings_load_only_the_working_directory_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        'SALLIMBOOK_ENVIRONMENT=staging\n'
        'SALLIMBOOK_ALLOWED_ORIGINS=["https://dotenv.invalid"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert settings.environment == "staging"
    assert settings.allowed_origins == ["https://dotenv.invalid"]

    nested = tmp_path / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert Settings().environment == "development"


def test_explicit_inputs_then_environment_take_precedence_over_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        'SALLIMBOOK_ENVIRONMENT=staging\n'
        'SALLIMBOOK_ALLOWED_ORIGINS=["https://dotenv.invalid"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SALLIMBOOK_ENVIRONMENT", "production")
    monkeypatch.setenv("SALLIMBOOK_ALLOWED_ORIGINS", '["https://environment.invalid"]')
    settings = Settings()
    assert settings.environment == "production"
    assert settings.allowed_origins == ["https://environment.invalid"]

    explicit = Settings(environment="test", allowed_origins=["https://explicit.invalid"])
    assert explicit.environment == "test"
    assert explicit.allowed_origins == ["https://explicit.invalid"]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_dotenv_deployment_mode_does_not_inherit_local_origins(tmp_path, monkeypatch, environment):
    (tmp_path / ".env").write_text(f"SALLIMBOOK_ENVIRONMENT={environment}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert Settings().allowed_origins == []


def test_dotenv_origins_are_used_only_as_explicit_configuration(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        'SALLIMBOOK_ENVIRONMENT=production\n'
        'SALLIMBOOK_ALLOWED_ORIGINS=["http://localhost:18742"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert Settings().allowed_origins == ["http://localhost:18742"]
    assert Settings(environment="production", _env_file=None).allowed_origins == []
