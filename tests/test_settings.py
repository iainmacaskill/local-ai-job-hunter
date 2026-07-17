"""Cover the .env loader (Phase C)."""

import settings


def test_load_env_sets_values_handles_comments_and_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        'REED_API_KEY="abc123"\n'
        "ADZUNA_APP_ID = my-id \n"
        "ADZUNA_APP_KEY='k-e-y'\n"
        "MALFORMED_LINE\n",
        encoding="utf-8",
    )
    for k in ("REED_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.delenv(k, raising=False)

    settings.load_env(env)
    assert settings.os.environ["REED_API_KEY"] == "abc123"      # quotes stripped
    assert settings.os.environ["ADZUNA_APP_ID"] == "my-id"      # whitespace trimmed
    assert settings.os.environ["ADZUNA_APP_KEY"] == "k-e-y"


def test_load_env_does_not_override_a_real_env_var(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("REED_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("REED_API_KEY", "from-shell")
    settings.load_env(env)
    assert settings.os.environ["REED_API_KEY"] == "from-shell"  # shell wins


def test_load_env_missing_file_is_a_noop(tmp_path):
    settings.load_env(tmp_path / "does-not-exist.env")          # should not raise
