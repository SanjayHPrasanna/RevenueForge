"""Runtime configuration, read from environment variables (or a .env file next to the backend)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("RF_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
LOCAL_ENV_FILE = BASE_DIR / ".env.local"


# Settings the whole team shares through git. Only these non-secret keys are read from team.env, so an
# API key pasted there by mistake is ignored instead of being used (and the file is reviewed in every PR).
TEAM_KEYS = {"GOOGLE_CLIENT_ID", "GOOGLE_ALLOWED_DOMAINS"}


def _load_env_file(path: Path, allowed: set[str] | None = None, override: bool = False) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if allowed is not None and k not in allowed:
            continue
        if v or (allowed is None and k not in TEAM_KEYS):  # an empty shared setting means "use the team's value"
            if override or k not in os.environ:
                os.environ[k] = v


# Order matters: real environment variables win, then your own backend/.env, then the UI override file,
# then the shared backend/team.env. The UI override file is created automatically from the admin settings screen.
_load_env_file(BASE_DIR / ".env")
_load_env_file(LOCAL_ENV_FILE, override=True)
_load_env_file(BASE_DIR / "team.env", TEAM_KEYS)


class Settings:
    app_name = "RevenueForge"
    database_url = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'revenueforge.db').as_posix()}")
    jwt_secret = os.getenv("JWT_SECRET", "")
    jwt_hours = int(os.getenv("JWT_HOURS", "12"))
    # "Sign in with Google": the OAuth client ID from Google Cloud Console. Empty = the Google button is hidden.
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    # Optional: only these email domains may sign in with Google, e.g. "isteer.com,example.com". Empty = any verified Google account.
    google_allowed_domains = [d.strip().lower().lstrip("@") for d in os.getenv("GOOGLE_ALLOWED_DOMAINS", "").split(",") if d.strip()]
    cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

    # LLM: gemini | anthropic | openai | azure | none
    llm_provider = os.getenv("LLM_PROVIDER", "none").lower()
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    # Optional second free Gemini key used only to write proposal-video narration, so it doesn't eat the main key's quota.
    gemini_video_api_key = os.getenv("GEMINI_VIDEO_API_KEY", "").strip()
    # Optional: name of the computer voice for proposal videos (Windows: e.g. "Microsoft Zira Desktop"). Empty = system default.
    video_voice = os.getenv("VIDEO_VOICE", "").strip()
    gemini_model = os.getenv("GEMINI_MODEL", "")  # empty = pick the newest stable Flash model automatically
    gemini_embed_model = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
    gemini_base_url = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    # Requests per minute the app allows itself. Free Gemini keys are limited (about 10/min for Flash).
    llm_rpm = int(os.getenv("LLM_RPM", "8"))
    # Set to true once the key belongs to a billed Google Cloud project (paid tier: no training on your data).
    llm_paid = os.getenv("LLM_PAID", "false").lower() in ("1", "true", "yes")
    # Banner shown to every user (sign-in page and app). Empty = automatic: a "sample data only" warning while the AI
    # runs on a free key. Set to "off" to hide it, or to your own text.
    public_notice = os.getenv("PUBLIC_NOTICE", "").strip()
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")

    max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "40"))


settings = Settings()

for d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

if not settings.jwt_secret:
    # Persist a generated secret so tokens survive restarts in local/demo mode.
    secret_file = DATA_DIR / ".jwt_secret"
    if secret_file.exists():
        settings.jwt_secret = secret_file.read_text().strip()
    else:
        settings.jwt_secret = secrets.token_urlsafe(48)
        secret_file.write_text(settings.jwt_secret)


def apply_ai_settings(payload: dict) -> dict:
    """Persist selected AI config to .env.local and update the live config object."""
    provider = str(payload.get("provider", settings.llm_provider or "none")).lower()
    provider = provider if provider in {"gemini", "anthropic", "openai", "azure", "none"} else "none"
    api_key = str(payload.get("api_key", "") or "").strip()
    model = str(payload.get("model", "") or "").strip()
    embed_model = str(payload.get("embed_model", settings.gemini_embed_model or "gemini-embedding-001")).strip()
    rpm = int(payload.get("rpm", settings.llm_rpm or 8) or 8)
    paid = bool(payload.get("paid", settings.llm_paid))

    values = {
        "LLM_PROVIDER": provider,
        "LLM_RPM": str(max(1, rpm)),
        "LLM_PAID": "true" if paid else "false",
        "GEMINI_MODEL": "",
        "ANTHROPIC_MODEL": settings.anthropic_model,
        "OPENAI_MODEL": settings.openai_model,
        "AZURE_OPENAI_DEPLOYMENT": settings.azure_deployment,
        "GEMINI_EMBED_MODEL": embed_model,
    }
    if provider == "gemini":
        values["GEMINI_API_KEY"] = api_key
        values["GEMINI_MODEL"] = model or settings.gemini_model
    elif provider == "anthropic":
        values["ANTHROPIC_API_KEY"] = api_key
        values["ANTHROPIC_MODEL"] = model or settings.anthropic_model
    elif provider == "openai":
        values["OPENAI_API_KEY"] = api_key
        values["OPENAI_MODEL"] = model or settings.openai_model
    elif provider == "azure":
        values["AZURE_OPENAI_API_KEY"] = api_key
        values["AZURE_OPENAI_DEPLOYMENT"] = model or settings.azure_deployment
    else:
        values["GEMINI_API_KEY"] = ""
        values["ANTHROPIC_API_KEY"] = ""
        values["OPENAI_API_KEY"] = ""
        values["AZURE_OPENAI_API_KEY"] = ""

    # Always keep the selected provider's secret current; clear others to avoid stale keys.
    for key, value in values.items():
        os.environ[key] = str(value)
    with LOCAL_ENV_FILE.open("w", encoding="utf-8") as f:
        for key in [
            "LLM_PROVIDER",
            "GEMINI_API_KEY",
            "GEMINI_MODEL",
            "GEMINI_EMBED_MODEL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_MODEL",
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_DEPLOYMENT",
            "LLM_RPM",
            "LLM_PAID",
        ]:
            if key in os.environ:
                f.write(f"{key}={os.environ[key]}\n")

    settings.llm_provider = provider
    settings.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
    settings.gemini_model = os.environ.get("GEMINI_MODEL", "")
    settings.gemini_embed_model = os.environ.get("GEMINI_EMBED_MODEL", settings.gemini_embed_model)
    settings.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    settings.anthropic_model = os.environ.get("ANTHROPIC_MODEL", settings.anthropic_model)
    settings.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    settings.openai_model = os.environ.get("OPENAI_MODEL", settings.openai_model)
    settings.azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    settings.azure_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", settings.azure_deployment)
    settings.llm_rpm = int(os.environ.get("LLM_RPM", str(settings.llm_rpm)))
    settings.llm_paid = os.environ.get("LLM_PAID", "false").lower() in ("1", "true", "yes")
    return {"provider": provider, "model": model or values.get(f"{provider.upper()}_MODEL", ""), "rpm": settings.llm_rpm, "paid": settings.llm_paid}
