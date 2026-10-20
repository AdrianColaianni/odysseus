import os
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse
from sqlalchemy import DDL, event, create_engine, Column, String, Text, Boolean, DateTime, Integer, Float, ForeignKey, JSON, Index, func, inspect, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.types import TypeDecorator
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import relationship, sessionmaker, backref

from src.runtime_paths import get_app_root
from core.platform_compat import safe_chmod, IS_WINDOWS

logger = logging.getLogger(__name__)

# Create base class for declarative models
Base = declarative_base()


def utcnow_naive() -> datetime:
    """Return naive UTC for existing DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    """Mixin that adds timestamp fields to models"""
    @declared_attr
    def created_at(cls):
        return Column(DateTime, default=utcnow_naive, nullable=False)
    
    @declared_attr
    def updated_at(cls):
        return Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)

from src.constants import APP_DB, DATA_DIR, AUTH_FILE, MEMORY_FILE, USER_PREFS_FILE, SETTINGS_FILE


def _default_database_url() -> str:
    return f"sqlite:///{APP_DB}"


def _normalize_sqlite_url(url: str) -> str:
    """Resolve relative ordinary SQLite paths without rewriting URI filenames."""
    try:
        parsed = make_url(url)
    except Exception:
        return url

    if parsed.get_backend_name() != "sqlite":
        return url

    db_path = parsed.database
    if (
        not db_path
        or db_path == ":memory:"
        or str(db_path).lower().startswith("file:")
        or os.path.isabs(str(db_path))
    ):
        return url

    absolute_path = (Path(get_app_root()) / str(db_path)).resolve().as_posix()
    return parsed.set(database=absolute_path).render_as_string(
        hide_password=False
    )


# Get database URL from environment, default to SQLite in DATA_DIR
DATABASE_URL = _normalize_sqlite_url(os.getenv("DATABASE_URL", _default_database_url()))

# Create engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if "sqlite" in DATABASE_URL else {},
    # Each in-memory connection is its own empty database, so every thread must share one.
    **({"poolclass": StaticPool} if DATABASE_URL.endswith(":memory:") else {}),
)


# Sidecar files SQLite can create next to the main DB. -journal is the default
# rollback journal; -wal/-shm appear once WAL is enabled. Each can hold copies of
# secret-bearing pages, so they get the same 0o600 lockdown as the DB itself.
_SQLITE_SIDECARS = ("-journal", "-wal", "-shm")


def _sqlite_db_path(url) -> Optional[str]:
    """Return the filesystem path for a file-backed SQLite URL.

    SQLite query parameters such as ``mode=memory`` only affect filename
    semantics when SQLAlchemy enables URI handling with ``uri=true``. Ordinary
    file URLs must therefore remain file-backed even when they contain a query
    parameter named ``mode``.

    For SQLite ``file:`` URIs, an empty authority or ``localhost`` identifies a
    local path. Other authorities are retained as UNC-style paths.
    """
    if url.get_backend_name() != "sqlite":
        return None

    db_path = url.database
    if not db_path or db_path == ":memory:":
        return None

    db_path = str(db_path)
    query = {
        str(key).lower(): str(value).strip().lower()
        for key, value in dict(getattr(url, "query", {}) or {}).items()
    }
    uri_enabled = query.get("uri") in {"1", "true", "yes", "on"}
    is_file_uri = db_path.lower().startswith("file:")

    if not uri_enabled or not is_file_uri:
        return db_path

    if (
        db_path.lower().startswith("file::memory:")
        or query.get("mode") == "memory"
    ):
        return None

    parsed = urlparse(db_path)
    fs_path = parsed.path or ""
    if not fs_path or fs_path == ":memory:":
        return None

    authority = parsed.netloc
    if authority and authority.lower() != "localhost":
        fs_path = f"//{authority}{fs_path}"

    return unquote(fs_path)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Listening on the Engine class ensures this listener fires for all Engine
# instances created within the process, not just the primary application engine.
# The isinstance(sqlite3.Connection) check ensures that this PRAGMA foreign_keys=ON
# configuration remains a no-op when using non-SQLite database backends.
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


class EncryptedText(TypeDecorator):
    """Text column transparently encrypted at rest via src.secret_storage.

    Writes are Fernet-encrypted (`enc:` prefix); reads decrypt back to
    plaintext, so all consumers use the column normally. Legacy plaintext
    rows pass through unchanged until their next write (a startup migration
    encrypts them). Protects the SQLite file at rest (stolen backup / leaked
    image), not a live process that can read the key.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        from src.secret_storage import encrypt
        return encrypt(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        from src.secret_storage import decrypt
        return decrypt(value)


class Session(TimestampMixin, Base):
    """
    SQLAlchemy model for Session table.
    Represents a chat session with its configuration and metadata.
    """
    __tablename__ = "sessions"
    
    # Primary key
    id = Column(String, primary_key=True, index=True)
    
    # Session metadata
    name = Column(String, nullable=False)
    endpoint_url = Column(String, nullable=False)
    model = Column(String, nullable=False)
    owner = Column(String, nullable=True, index=True)  # username; null = legacy/shared
    
    # Configuration flags
    rag = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    memory_extraction_enabled = Column(Boolean, default=True)
    memory_injection_enabled = Column(Boolean, default=True)
    skill_injection_enabled = Column(Boolean, default=True)
    thinking_mode = Column(String, nullable=True, default="off")
    temperature_override = Column(Float, nullable=True, default=None)
    max_tokens_override = Column(Integer, nullable=True, default=None)

    # Organization
    folder = Column(String, nullable=True, default=None)
    cwd = Column(String, nullable=True, default=None)
    # Registered ModelEndpoint this session is bound to. endpoint_url alone
    # cannot distinguish two endpoints that share a provider URL but use
    # different credentials (e.g. two ChatGPT Subscription accounts), so the
    # exact endpoint id is remembered here. NULL = legacy session; the first
    # deterministic, owner-scoped resolution persists a binding.
    endpoint_id = Column(String, nullable=True, index=True)
    
    # Headers stored as JSON
    headers = Column(JSON, default=dict)
    
    # Timestamps are provided by TimestampMixin
    last_accessed = Column(DateTime, default=func.now(), onupdate=func.now())
    # Timestamp of the last actual MESSAGE in this session. Set explicitly
    # only when a message is persisted (NOT onupdate) — so it's a clean
    # "last conversation" signal, immune to renames / model swaps / merely
    # opening the chat (all of which bump updated_at and last_accessed).
    # The "Last active" sort uses this.
    last_message_at = Column(DateTime, nullable=True, default=None)
    
    
    # Indexes - optimized composites
    __table_args__ = (
        Index('ix_sessions_active', 'archived', 'last_accessed'),
        Index('ix_sessions_search', 'name', 'archived'),
    )
    
    # Properties
    is_important = Column(Boolean, default=False)
    message_count = Column(Integer, default=0)
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    mode = Column(String, nullable=True)  # 'agent', 'chat', or 'research'
    crew_member_id = Column(String, nullable=True)  # links to crew_members.id

    # Relationship to chat messages
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    
    @property
    def is_active(self):
        """Check if session is active (not archived)"""
        return not self.archived
    
    def to_dict(self):
        """Convert session to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'name': self.name,
            'model': self.model,
            'endpoint_url': self.endpoint_url,
            'rag': self.rag,
            'archived': self.archived,
            'memory_extraction_enabled': self.memory_extraction_enabled is not False,
            'memory_injection_enabled': self.memory_injection_enabled is not False,
            'skill_injection_enabled': self.skill_injection_enabled is not False,
            'thinking_mode': self.thinking_mode or '',
            'temperature_override': self.temperature_override,
            'max_tokens_override': self.max_tokens_override,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_accessed': self.last_accessed.isoformat() if self.last_accessed else None,
            'last_message_at': self.last_message_at.isoformat() if self.last_message_at else None,
            'message_count': self.message_count,
            'is_important': self.is_important,
            'folder': self.folder,
            'total_input_tokens': self.total_input_tokens or 0,
            'total_output_tokens': self.total_output_tokens or 0,
            'total_cost_usd': self.total_cost_usd or 0.0,
            'crew_member_id': self.crew_member_id,
        }

class ChatMessage(Base):
    """
    SQLAlchemy model for ChatMessage table.
    Represents individual chat messages within a session.
    """
    __tablename__ = "chat_messages"
    
    # Primary key - using String to support UUIDs
    id = Column(String, primary_key=True, index=True)
    
    # Foreign key to Session
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Message content
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    meta_data = Column("metadata", Text, nullable=True)  # JSON string for metrics etc.

    # Timestamp
    timestamp = Column(DateTime, default=utcnow_naive)
    
    # Relationship to Session
    session = relationship("Session", back_populates="messages")
    
    # Indexes - optimized composite
    __table_args__ = (
        Index('ix_messages_session_time', 'session_id', 'timestamp'),  # Composite for efficient message retrieval
    )

class BackgroundToolJob(Base):
    """Durable origin and once-only chat delivery for background tool work."""
    __tablename__ = "background_tool_jobs"
    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    owner = Column(String, nullable=False, index=True)
    tool = Column(String, nullable=False)
    query = Column(Text, nullable=False)
    rounds = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="running", index=True)
    payload = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    message_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)


class Document(TimestampMixin, Base):
    """Living document that the AI can create and edit in-place."""
    __tablename__ = "documents"

    id              = Column(String, primary_key=True, index=True)
    session_id      = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    title           = Column(String, nullable=False, default="Untitled")
    language        = Column(String, nullable=True)          # "python", "markdown", "text", etc.
    current_content = Column(Text, nullable=False, default="")
    version_count   = Column(Integer, default=1)
    is_active       = Column(Boolean, default=True)
    # Soft-archive: hidden from the Library's Documents list/search/Tidy until
    # restored. Distinct from is_active (which tracks "open in a session").
    archived        = Column(Boolean, default=False)
    # Owner of this document. Documents used to derive ownership from their
    # linked chat session, but a session can be deleted (session_id → NULL via
    # SET NULL), orphaning the doc and making it vanish from the owner's
    # Library + search. Owning the row directly is robust against that.
    owner           = Column(String, nullable=True, index=True)
    tidy_verdict    = Column(String, nullable=True)        # "keep", "junk", or None (not yet reviewed)
    # Provenance: if this document was created by opening an email attachment,
    # these point back to the source email so the "Sign and reply" flow can
    # thread a response on the original conversation.
    source_email_uid         = Column(String, nullable=True)
    source_email_folder      = Column(String, nullable=True)
    source_email_account_id  = Column(String, nullable=True)
    source_email_message_id  = Column(String, nullable=True, index=True)

    session  = relationship("Session", backref=backref("documents", cascade="save-update, merge"))
    versions = relationship("DocumentVersion", back_populates="document",
                           cascade="all, delete-orphan", order_by="DocumentVersion.version_number")


class DocumentVersion(Base):
    """Immutable snapshot of a document at a point in time."""
    __tablename__ = "document_versions"

    id             = Column(String, primary_key=True, index=True)
    document_id    = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    content        = Column(Text, nullable=False)
    summary        = Column(String, nullable=True)     # Edit description
    source         = Column(String, default="ai")      # "ai" or "user"
    created_at     = Column(DateTime, default=utcnow_naive)

    document = relationship("Document", back_populates="versions")


class GalleryAlbum(TimestampMixin, Base):
    """A photo album/folder."""
    __tablename__ = "gallery_albums"

    id          = Column(String, primary_key=True, index=True)
    name        = Column(String, nullable=False)
    description = Column(Text, default="")
    cover_id    = Column(String, nullable=True)  # GalleryImage.id for cover photo
    owner       = Column(String, nullable=True, index=True)

    images = relationship("GalleryImage", back_populates="album")


class GalleryImage(TimestampMixin, Base):
    """Stores metadata for photos and AI-generated images."""
    __tablename__ = "gallery_images"

    id         = Column(String, primary_key=True, index=True)
    filename   = Column(String, nullable=False, unique=True)
    prompt     = Column(Text, nullable=False, default="")
    caption    = Column(Text, nullable=True, default="")
    model      = Column(String, nullable=True)
    size       = Column(String, nullable=True)
    quality    = Column(String, nullable=True)
    tags       = Column(String, nullable=True, default="")
    ai_tags    = Column(Text, nullable=True, default="")       # AI-generated tags (comma-separated)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    album_id   = Column(String, ForeignKey("gallery_albums.id", ondelete="SET NULL"), nullable=True, index=True)
    owner      = Column(String, nullable=True, index=True)
    is_active  = Column(Boolean, default=True)
    favorite   = Column(Boolean, default=False)

    # File integrity
    file_hash  = Column(String(64), nullable=True, index=True)  # SHA-256

    # EXIF / photo metadata
    taken_at       = Column(DateTime, nullable=True, index=True)  # EXIF DateTimeOriginal
    camera_make    = Column(String, nullable=True)
    camera_model   = Column(String, nullable=True)
    gps_lat        = Column(String, nullable=True)  # stored as string for precision
    gps_lng        = Column(String, nullable=True)
    width          = Column(Integer, nullable=True)
    height         = Column(Integer, nullable=True)
    file_size      = Column(Integer, nullable=True)  # bytes

    session = relationship("Session", backref=backref("gallery_images"))
    album   = relationship("GalleryAlbum", back_populates="images")

    __table_args__ = (
        Index('ix_gallery_images_tags', 'tags'),
        Index('ix_gallery_images_model', 'model'),
        Index('ix_gallery_images_active', 'is_active', 'created_at'),
    )


class EmailAccount(TimestampMixin, Base):
    """A configured IMAP/SMTP account. Supports multiple accounts per user —
    exactly one row per owner has is_default=True.

    Security note: imap_password / smtp_password are stored Fernet-encrypted
    via src/secret_storage.py. The key lives at data/.app_key (mode 0o600,
    gitignored). Anyone with read access to that file can decrypt every
    row, so the threat model is "stolen SQLite backup" rather than
    "process compromise". On first start any legacy plaintext rows are
    migrated automatically (see _migrate_encrypt_email_passwords).
    """
    __tablename__ = "email_accounts"

    id             = Column(String, primary_key=True, index=True)
    owner          = Column(String, nullable=True, index=True)
    name           = Column(String, nullable=False)  # Display name: "Work", "Personal", etc.
    is_default     = Column(Boolean, default=False, nullable=False)
    enabled        = Column(Boolean, default=True, nullable=False)

    # IMAP (receiving)
    imap_host      = Column(String, default="")
    imap_port      = Column(Integer, default=993)
    imap_user      = Column(String, default="")
    imap_password  = Column(String, default="")
    imap_starttls  = Column(Boolean, default=True)

    # SMTP (sending)
    smtp_host      = Column(String, default="")
    smtp_port      = Column(Integer, default=465)
    smtp_security  = Column(String, default="ssl")  # ssl | starttls | none
    smtp_user      = Column(String, default="")
    smtp_password  = Column(String, default="")

    from_address   = Column(String, default="")
    display_name   = Column(String, nullable=True)   # "Hriday Ranka" — used in From: header

    # OAuth2 (Google / Google Workspace). Tokens stored encrypted via secret_storage.
    oauth_provider      = Column(String, nullable=True)   # "google" or None
    oauth_access_token  = Column(String, nullable=True)   # encrypted
    oauth_refresh_token = Column(String, nullable=True)   # encrypted
    oauth_token_expiry  = Column(String, nullable=True)   # unix timestamp string

    __table_args__ = (
        Index('ix_email_accounts_owner_default', 'owner', 'is_default'),
    )


class EmailAccountOwnerLock(Base):
    """Durable per-owner mutex for email-account default mutations.

    Row-locking databases serialize mutations by locking this row before they
    inspect or stage EmailAccount changes.  SQLite uses ``BEGIN IMMEDIATE``
    instead, because it ignores ``SELECT ... FOR UPDATE``; keeping the table in
    the shared metadata still makes the non-SQLite path available without a
    separate migration.  The empty key represents the normalized legacy /
    unconfigured scope shared by ``owner IS NULL`` and ``owner = ''`` rows.
    """
    __tablename__ = "email_account_owner_locks"

    owner_key = Column(String, primary_key=True)


_EMAIL_ACCOUNT_DEFAULT_INDEX = "ux_email_accounts_one_default_per_owner"
_EMAIL_ACCOUNT_DEFAULT_INDEX_DDL = {
    "sqlite": (
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_EMAIL_ACCOUNT_DEFAULT_INDEX} "
        "ON email_accounts (COALESCE(owner, '')) WHERE is_default = 1"
    ),
    "postgresql": (
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_EMAIL_ACCOUNT_DEFAULT_INDEX} "
        "ON email_accounts ((COALESCE(owner, ''))) WHERE is_default IS TRUE"
    ),
}


# SQLAlchemy cannot express one portable partial, functional index across the
# two supported database families.  Register dialect-specific DDL so fresh
# databases get the invariant as part of create_all(); the startup migration
# below installs the same index on existing databases after normalizing legacy
# duplicate rows.
for _dialect_name, _index_ddl in _EMAIL_ACCOUNT_DEFAULT_INDEX_DDL.items():
    event.listen(
        EmailAccount.__table__,
        "after_create",
        DDL(_index_ddl).execute_if(dialect=_dialect_name),
    )


def lock_email_account_owner_mutations(db, *owners: str) -> None:
    """Lock normalized email-account owner scopes in canonical order.

    ``NULL`` and the empty string are one legacy/single-user owner partition,
    matching the unique default-account index.  SQLite has only a database
    writer reservation, while row-locking databases use durable mutex rows.
    Sorting all requested owner keys keeps multi-owner operations such as user
    rename from deadlocking with another mutation that requests the same keys
    in the opposite order.
    """
    from sqlalchemy.exc import IntegrityError

    owner_keys = sorted({owner or "" for owner in owners} or {""})
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
        return

    for owner_key in owner_keys:
        lock_row = db.get(
            EmailAccountOwnerLock,
            owner_key,
            with_for_update=True,
        )
        if lock_row is not None:
            continue

        inserted = False
        try:
            with db.begin_nested():
                db.add(EmailAccountOwnerLock(owner_key=owner_key))
                db.flush()
                inserted = True
        except IntegrityError:
            # A competing transaction created the mutex row first.  Once its
            # insert commits, lock that durable row before touching accounts.
            pass

        if not inserted:
            (
                db.query(EmailAccountOwnerLock)
                .filter(EmailAccountOwnerLock.owner_key == owner_key)
                .with_for_update()
                .one()
            )


class ModelEndpoint(TimestampMixin, Base):
    """Admin-configured model endpoints. Models are auto-discovered via /v1/models."""
    __tablename__ = "model_endpoints"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)          # Display label, e.g. "Local vLLM", "OpenRouter"
    base_url = Column(String, nullable=False)      # Base URL, e.g. "http://localhost:8002/v1"
    api_key = Column(EncryptedText, nullable=True)  # Optional provider API key, encrypted at rest
    is_enabled = Column(Boolean, default=True)
    hidden_models = Column(Text, nullable=True)    # JSON list of model IDs that failed probing
    cached_models = Column(Text, nullable=True)    # JSON list of last-known model IDs (avoids probe on list)
    pinned_models = Column(Text, nullable=True)    # JSON list of admin-pinned model IDs (manual, may not appear in /v1/models)
    model_type = Column(String, nullable=True, default="llm")  # "llm" or "image"
    # auto = classify by URL; local = self-hosted server; api/proxy = external
    # OpenAI-compatible API even when reachable through a private/tailnet IP.
    endpoint_kind = Column(String, nullable=True, default="auto")
    # auto = background refresh with TTL/backoff; manual/disabled = cached-first
    # only unless an explicit endpoint probe is requested.
    model_refresh_mode = Column(String, nullable=True, default="auto")
    model_refresh_interval = Column(Integer, nullable=True, default=None)
    model_refresh_timeout = Column(Integer, nullable=True, default=None)
    # Whether models on this endpoint accept OpenAI-style function
    # schemas + emit `tool_calls`. Auto-detected at Cookbook auto-
    # register time from `--enable-auto-tool-choice` in the serve cmd;
    # can be toggled per-endpoint in the UI. NULL = unknown, falls
    # back to the model-name keyword heuristic in agent_loop.py.
    supports_tools = Column(Boolean, nullable=True, default=None)
    # JSON object: model id -> native tool schema surface preference.
    # Values: none, compact, full. Missing key = legacy automatic behavior.
    model_tool_modes = Column(Text, nullable=True)
    # Per-user ownership. NULL = legacy/shared (visible to every user) — this
    # is the historical default. When non-null, the model picker only shows
    # the endpoint to that user (admins always see everything).
    owner = Column(String, nullable=True, index=True)
    # Optional OAuth/session-backed credential row. Used by subscription-backed
    # providers that need refresh tokens instead of a static API key.
    provider_auth_id = Column(String, nullable=True, index=True)


class ProviderAuthSession(TimestampMixin, Base):
    """Encrypted OAuth/session credentials for refresh-aware model providers."""
    __tablename__ = "provider_auth_sessions"

    id = Column(String, primary_key=True, index=True)
    provider = Column(String, nullable=False, index=True)
    owner = Column(String, nullable=True, index=True)
    label = Column(String, nullable=True)
    base_url = Column(String, nullable=False)
    access_token = Column(EncryptedText, nullable=True)
    refresh_token = Column(EncryptedText, nullable=True)
    last_refresh = Column(DateTime, nullable=True)
    auth_mode = Column(String, nullable=True)

class McpServer(TimestampMixin, Base):
    """Admin-configured MCP (Model Context Protocol) tool servers."""
    __tablename__ = "mcp_servers"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    transport = Column(String, nullable=False, default="stdio")  # "stdio" or "sse"
    command = Column(String, nullable=True)      # For stdio: executable path
    args = Column(Text, nullable=True)           # JSON array of command args
    env = Column(Text, nullable=True)            # JSON object of env vars
    url = Column(String, nullable=True)          # For SSE: server URL
    is_enabled = Column(Boolean, default=True)
    oauth_config = Column(Text, nullable=True)   # JSON: provider, keys_file, token_file, scopes
    disabled_tools = Column(Text, nullable=True)  # JSON array of tool names to hide from LLM
    oauth_tokens = Column(EncryptedText, nullable=True)  # JSON {tokens, client_info} for generic MCP OAuth, encrypted at rest


class Comparison(TimestampMixin, Base):
    """Stores A/B model comparison results."""
    __tablename__ = "comparisons"

    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, nullable=True)     # Parent session context (optional)
    owner = Column(String, nullable=True, index=True)  # username
    prompt = Column(Text, nullable=False)
    model_a = Column(String, nullable=False)
    model_b = Column(String, nullable=False)
    endpoint_a = Column(String, nullable=False)
    endpoint_b = Column(String, nullable=False)
    response_a = Column(Text, nullable=True)
    response_b = Column(Text, nullable=True)
    metrics_a = Column(Text, nullable=True)         # JSON string
    metrics_b = Column(Text, nullable=True)         # JSON string
    winner = Column(String, nullable=True)           # "a", "b", "tie", or null
    is_blind = Column(Boolean, default=True)
    blind_mapping = Column(Text, nullable=True)      # JSON: {"left": "a"/"b", "right": "a"/"b"}
    voted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('ix_comparisons_voted_at', 'voted_at'),
    )


class Signature(TimestampMixin, Base):
    """User-saved visual signatures (image stamps).

    Reusable across PDF form filling, email composition, and document editing.
    `data_png` is a base64-encoded PNG (no `data:` prefix). The SVG vector
    column is reserved for future smooth vector storage. Both are stored
    Fernet-encrypted at rest (see EncryptedText / src.secret_storage); a
    handwritten signature is sensitive, so it must never sit plaintext in the
    DB file. Existing rows are migrated automatically on startup.
    """
    __tablename__ = "signatures"

    id = Column(String, primary_key=True, index=True)
    owner = Column(String, nullable=True, index=True)
    name = Column(String, nullable=False, default="Signature")
    data_png = Column(EncryptedText, nullable=False)   # base64 PNG, encrypted at rest
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    svg = Column(EncryptedText, nullable=True)         # vector signature, encrypted at rest


class ApiToken(TimestampMixin, Base):
    """API tokens for external integrations (n8n, Make, etc.)."""
    __tablename__ = "api_tokens"

    id = Column(String, primary_key=True, index=True)
    owner = Column(String, nullable=True, index=True)
    name = Column(String, nullable=False)
    token_hash = Column(String, nullable=False)
    token_prefix = Column(String, nullable=False)  # first 8 chars for display
    scopes = Column(String, nullable=False, default="chat")
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)


class Webhook(TimestampMixin, Base):
    """Outgoing webhooks fired on events."""
    __tablename__ = "webhooks"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    secret = Column(String, nullable=True)  # HMAC-SHA256 signing secret
    events = Column(String, nullable=False)  # comma-separated event types
    is_active = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime, nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_error = Column(String, nullable=True)


class UserTool(TimestampMixin, Base):
    """User-created sandboxed mini-apps/tools."""
    __tablename__ = "user_tools"

    id            = Column(String, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    description   = Column(Text, nullable=True)
    icon          = Column(String, nullable=True, default="")
    html_content  = Column(Text, nullable=False)
    scope         = Column(String, nullable=False, default="global")  # "global" or session_id
    session_id    = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    owner         = Column(String, nullable=True, index=True)      # username
    is_pinned     = Column(Boolean, default=False)
    is_active     = Column(Boolean, default=True)
    version       = Column(Integer, default=1)
    author        = Column(String, nullable=True, default="ai")

    session = relationship("Session", backref=backref("user_tools", cascade="all, delete-orphan"))

    __table_args__ = (
        Index('ix_user_tools_scope', 'scope'),
        Index('ix_user_tools_active', 'is_active'),
    )


class UserToolData(Base):
    """Key-value storage for user tool persistent data."""
    __tablename__ = "user_tool_data"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    tool_id    = Column(String, ForeignKey("user_tools.id", ondelete="CASCADE"), nullable=False)
    key        = Column(String, nullable=False)
    value      = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    tool = relationship("UserTool", backref=backref("data_entries", cascade="all, delete-orphan"))

    __table_args__ = (
        Index('ix_user_tool_data_tool_key', 'tool_id', 'key', unique=True),
    )


class CrewMember(TimestampMixin, Base):
    """A custom AI persona ('crew member') with its own personality, model, tools, and memory scope."""
    __tablename__ = "crew_members"

    id            = Column(String, primary_key=True, index=True)
    owner         = Column(String, nullable=True, index=True)
    name          = Column(String, nullable=False)
    avatar        = Column(String, nullable=True)
    user_name     = Column(String, nullable=True)          # what they call the user
    personality   = Column(Text, nullable=True)             # system prompt
    model         = Column(String, nullable=True)
    endpoint_url  = Column(String, nullable=True)
    greeting      = Column(Text, nullable=True)
    enabled_tools = Column(Text, nullable=True)             # JSON array or "all"
    session_id    = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    is_active     = Column(Boolean, default=True)
    sort_order    = Column(Integer, default=0)
    is_default_assistant = Column(Boolean, default=False)   # singleton per-owner "personal assistant"
    timezone      = Column(String, nullable=True)           # IANA tz name (e.g. "America/New_York") for scheduled check-ins

    session = relationship("Session", foreign_keys=[session_id],
                           backref=backref("crew_member", uselist=False))


class ScheduledTask(TimestampMixin, Base):
    """A recurring or one-off task — LLM-powered or direct action, time or event triggered."""
    __tablename__ = "scheduled_tasks"

    id             = Column(String, primary_key=True, index=True)
    owner          = Column(String, nullable=True, index=True)
    name           = Column(String, nullable=False, default="Untitled Task")
    prompt         = Column(Text, nullable=True)              # LLM prompt (for task_type="llm")
    request_authority_json = Column(Text, nullable=True)       # server-only admitted request snapshot
    task_type      = Column(String, default="llm")            # "llm" | "action"
    action         = Column(String, nullable=True)            # builtin action name (for task_type="action")
    schedule       = Column(String, nullable=True)            # "once", "daily", "weekly", "monthly"
    scheduled_time = Column(String, nullable=True)            # "HH:MM" (24h, stored UTC)
    scheduled_day  = Column(Integer, nullable=True)           # day-of-week 0=Mon for weekly, day-of-month for monthly
    scheduled_date = Column(DateTime, nullable=True)          # exact datetime for "once"
    trigger_type   = Column(String, default="schedule")       # "schedule" | "event"
    trigger_event  = Column(String, nullable=True)            # e.g. "session_created", "message_sent"
    trigger_count  = Column(Integer, nullable=True)           # fire every N events
    trigger_counter = Column(Integer, default=0)              # current count toward trigger_count
    next_run       = Column(DateTime, nullable=True, index=True)
    last_run       = Column(DateTime, nullable=True)
    status         = Column(String, default="active")         # "active", "paused", "completed"
    output_target  = Column(String, default="session")        # "session" (extensible later)
    session_id     = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    model          = Column(String, nullable=True)
    endpoint_url   = Column(String, nullable=True)
    run_count      = Column(Integer, default=0)

    cron_expression = Column(String, nullable=True)           # cron string e.g. "*/5 * * * *"
    then_task_id   = Column(String, ForeignKey("scheduled_tasks.id", ondelete="SET NULL"), nullable=True)
    webhook_token  = Column(String, nullable=True, unique=True)
    crew_member_id = Column(String, nullable=True)     # optional link to crew_members.id
    # character_id historically referenced an agent_characters table that was
    # never actually created. Keep the column for schema compatibility but
    # drop the ForeignKey so SQLAlchemy table sort doesn't fail on flush.
    character_id   = Column(String, nullable=True)
    max_steps      = Column(Integer, nullable=True)       # max agent loop iterations (null=unlimited)
    email_results  = Column(Boolean, default=True)        # email results to character.email_to
    notifications_enabled = Column(Boolean, default=True) # per-task on/off for completion notifications

    session = relationship("Session", backref=backref("scheduled_tasks", cascade="save-update, merge"))
    then_task = relationship("ScheduledTask", remote_side=[id], foreign_keys=[then_task_id])

    __table_args__ = (
        Index('ix_scheduled_tasks_due', 'status', 'next_run'),
        Index('ix_scheduled_tasks_event', 'trigger_type', 'trigger_event', 'status'),
    )


class EditorDraft(TimestampMixin, Base):
    """Persisted in-progress gallery-editor session — layered project state
    that the user can close and reopen later. Stores the full layer payload
    as JSON (with base64-encoded PNG dataURLs per layer) plus a small
    thumbnail for the landing-screen list.
    """
    __tablename__ = "editor_drafts"

    id              = Column(String, primary_key=True, index=True)
    owner           = Column(String, nullable=True, index=True)
    name            = Column(String, nullable=False, default="Untitled")
    # If the draft was opened FROM a gallery photo, point back at it so we
    # can show "Resuming edit of <photo>" and so reopening that photo picks
    # up the same draft rather than starting fresh.
    source_image_id = Column(String, nullable=True, index=True)
    width           = Column(Integer, nullable=True)
    height          = Column(Integer, nullable=True)
    # Full draft body — layer pixels (base64 PNG dataURLs), offsets,
    # opacities, visibility, active id, next id, etc. Kept as TEXT/JSON so
    # we don't have to re-shape the model every time the editor adds a
    # new piece of state.
    payload         = Column(Text, nullable=False, default="")
    # Tiny preview (data URL, ~128px wide) for the landing list. Stored
    # inline so the list endpoint can return everything in one shot.
    thumbnail       = Column(Text, nullable=True)
    is_active       = Column(Boolean, default=True)

    __table_args__ = (
        Index('ix_editor_drafts_owner_updated', 'owner', 'is_active', 'updated_at'),
    )


class TaskRun(Base):
    """Record of a single execution of a ScheduledTask."""
    __tablename__ = "task_runs"

    id          = Column(String, primary_key=True, index=True)
    task_id     = Column(String, ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), nullable=False)
    started_at  = Column(DateTime, nullable=False, default=utcnow_naive)
    finished_at = Column(DateTime, nullable=True)
    status      = Column(String, default="running")  # "running", "success", "error"
    result      = Column(Text, nullable=True)
    error       = Column(Text, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    steps       = Column(Text, nullable=True)             # JSON log of agent tool calls
    model       = Column(String, nullable=True)           # model that actually ran (resolved at execution)

    task = relationship("ScheduledTask", backref=backref("runs", cascade="all, delete-orphan",
                        order_by="TaskRun.started_at.desc()"))

    __table_args__ = (
        Index('ix_task_runs_task', 'task_id', 'started_at'),
    )


class NotificationLog(Base):
    """Persisted task notifications, including completion and error text."""
    __tablename__ = "notification_logs"

    id         = Column(String, primary_key=True, index=True)
    owner      = Column(String, nullable=True, index=True)
    task_name  = Column(String, nullable=False)
    task_id    = Column(String, nullable=True, index=True)
    status     = Column(String, nullable=False, default="success")
    body       = Column(Text, nullable=True)
    timestamp  = Column(DateTime, nullable=False, default=utcnow_naive, index=True)

    __table_args__ = (
        Index('ix_notification_logs_owner_time', 'owner', 'timestamp'),
    )


class Memory(Base):
    """
    SQLAlchemy model for Memory table.
    Represents persistent memory entries with metadata.
    """
    __tablename__ = "memories"
    
    # Primary key
    id = Column(String, primary_key=True, index=True)
    
    # Memory content
    text = Column(Text, nullable=False)
    
    # Categorization
    category = Column(String, default='fact')
    source = Column(String, default='user')

    # Owner (username)
    owner = Column(String, nullable=True, index=True)

    # Reference to session (nullable)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True)

    # Timestamp as Unix timestamp
    timestamp = Column(Integer, default=lambda: int(utcnow_naive().timestamp()))

    # Relationship to Session
    session = relationship("Session", backref="memories")

    # Indexes - optimized composites
    __table_args__ = (
        Index('ix_memories_lookup', 'category', 'timestamp'),  # Composite for category-based queries
        Index('ix_memories_session', 'session_id', 'timestamp'),  # Composite for session-based queries
    )

def _migrate_backfill_last_message_at():
    """Fill NULL sessions.last_message_at from the newest message, else
    last_accessed, else created_at."""
    import sqlite3
    db_path = DATABASE_URL.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        return
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            UPDATE sessions
               SET last_message_at = COALESCE(
                   (SELECT MAX(timestamp) FROM chat_messages
                     WHERE chat_messages.session_id = sessions.id),
                   last_accessed,
                   created_at
               )
             WHERE last_message_at IS NULL
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_sessions_last_message_at "
            "ON sessions(archived, last_message_at)"
        )
        conn.commit()
    except Exception as e:
        logging.getLogger(__name__).warning(f"last_message_at backfill failed: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _migrate_model_endpoints():
    """Recreate model_endpoints table if schema changed (url->base_url)."""
    import sqlite3
    db_path = DATABASE_URL.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        return
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("PRAGMA table_info(model_endpoints)")
        columns = [row[1] for row in cursor.fetchall()]
        if columns and "base_url" not in columns:
            conn.execute("DROP TABLE IF EXISTS model_endpoints")
            conn.commit()
            logging.getLogger(__name__).info("Migrated: dropped old model_endpoints table (schema change)")
    except Exception as e:
        logging.getLogger(__name__).warning(f"model_endpoints migration check failed: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _migrate_assign_legacy_owner():
    """Assign all null-owner data to the first (admin) user.

    Runs at boot AND periodically (sweep_null_owners) so that data created
    while auth is disabled / middleware is bypassed via localhost doesn't
    sit in the DB as world-visible.
    """
    import sqlite3
    import json as _json

    auth_path = os.path.join(os.path.dirname(DATABASE_URL.replace("sqlite:///", "")), "auth.json")
    if not os.path.isabs(auth_path):
        auth_path = AUTH_FILE
    admin_user = None
    try:
        with open(auth_path, "r", encoding="utf-8") as f:
            auth_data = _json.load(f)
        users = auth_data.get("users", {})
        if users:
            for uname, udata in users.items():
                if udata.get("is_admin") is True:
                    admin_user = uname
                    break
            if not admin_user:
                admin_user = next(iter(users))
    except Exception:
        pass

    if not admin_user:
        return

    db_path = DATABASE_URL.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        return

    logger = logging.getLogger(__name__)
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        tables = [
            "sessions", "memories", "gallery_images", "user_tools",
            "comparisons", "documents", "signatures", "notes",
            "calendars", "calendar_events", "integrations",
            "scheduled_tasks", "task_runs", "crew_members",
            "gallery_albums", "gallery_people", "user_tool_data",
            "api_tokens", "webhooks",
        ]
        for table in tables:
            try:
                cursor = conn.execute(f"PRAGMA table_info({table})")
                columns = [row[1] for row in cursor.fetchall()]
                if "owner" in columns:
                    res = conn.execute(f"UPDATE {table} SET owner = ? WHERE owner IS NULL", (admin_user,))
                    if res.rowcount > 0:
                        logger.info(f"Assigned {res.rowcount} legacy rows in {table} to '{admin_user}'")
            except Exception as e:
                logger.warning(f"Legacy owner assignment for {table} failed: {e}")
        conn.commit()
    except Exception as e:
        logger.warning(f"Legacy owner migration failed: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Also migrate memory.json
    mem_path = MEMORY_FILE
    try:
        if os.path.exists(mem_path):
            with open(mem_path, "r", encoding="utf-8") as f:
                memories = _json.load(f)
            changed = False
            for m in memories:
                if not m.get("owner"):
                    m["owner"] = admin_user
                    changed = True
            if changed:
                with open(mem_path, "w", encoding="utf-8") as f:
                    _json.dump(memories, f, ensure_ascii=False, indent=2)
                logger.info(f"Assigned {sum(1 for _ in memories)} legacy memories in memory.json to '{admin_user}'")
    except Exception as e:
        logger.warning(f"memory.json legacy migration failed: {e}")

    # Also migrate user_prefs.json to per-user format
    prefs_path = USER_PREFS_FILE
    try:
        if os.path.exists(prefs_path):
            with open(prefs_path, "r", encoding="utf-8") as f:
                prefs = _json.load(f)
            if "_users" not in prefs and prefs:
                # Flat format → nest ordinary preferences under the admin
                # user. Foreground fallback is an explicit per-owner opt-in,
                # so auth-disabled consent must remain inert at the flat root
                # rather than becoming consent for the first named owner.
                foreground_keys = {
                    "foreground_fallback_enabled",
                    "foreground_model_fallbacks",
                }
                named_prefs = {
                    key: value
                    for key, value in prefs.items()
                    if key not in foreground_keys
                }
                new_prefs = {
                    key: prefs[key]
                    for key in foreground_keys
                    if key in prefs
                }
                new_prefs["_users"] = {admin_user: named_prefs}
                with open(prefs_path, "w", encoding="utf-8") as f:
                    _json.dump(new_prefs, f, indent=2)
                logger.info(f"Migrated user_prefs.json to per-user format under '{admin_user}'")
    except Exception as e:
        logger.warning(f"user_prefs.json migration failed: {e}")


def _migrate_backfill_document_owner_from_session():
    """Backfill documents.owner from the owner of the linked chat session.

    Must run AFTER the owner column is added and BEFORE the blanket
    legacy-owner sweep, so session-linked docs get their *true* owner
    while only genuinely orphaned (sessionless) docs fall through to the
    admin assignment. Idempotent — only touches NULL-owner rows."""
    try:
        with engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(documents)"))]
            if "owner" not in cols:
                return
            res = conn.execute(text(
                "UPDATE documents SET owner = ("
                "  SELECT s.owner FROM sessions s WHERE s.id = documents.session_id"
                ") WHERE owner IS NULL AND session_id IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM sessions s WHERE s.id = documents.session_id "
                "            AND s.owner IS NOT NULL)"
            ))
            conn.commit()
            if res.rowcount:
                logging.getLogger(__name__).info(
                    f"Backfilled owner on {res.rowcount} session-linked documents")
    except Exception as e:
        logging.getLogger(__name__).warning(f"document owner backfill: {e}")


def _migrate_make_task_schedule_nullable():
    """Rebuild scheduled_tasks when prompt, schedule or scheduled_time is still NOT NULL."""
    try:
        with engine.connect() as conn:
            cols_info = list(conn.execute(text("PRAGMA table_info(scheduled_tasks)")))
            notnull_map = {r[1]: r[3] for r in cols_info}
            needs_rebuild = (
                notnull_map.get("prompt", 0) == 1 or
                notnull_map.get("schedule", 0) == 1 or
                notnull_map.get("scheduled_time", 0) == 1
            )
            if needs_rebuild:
                logging.getLogger(__name__).info("Rebuilding scheduled_tasks to make prompt/schedule/scheduled_time nullable")
                conn.execute(text("ALTER TABLE scheduled_tasks RENAME TO _old_scheduled_tasks"))
                conn.execute(text("""
                    CREATE TABLE scheduled_tasks (
                        id VARCHAR PRIMARY KEY,
                        owner VARCHAR,
                        name VARCHAR NOT NULL,
                        prompt TEXT,
                        schedule VARCHAR,
                        scheduled_time VARCHAR,
                        scheduled_day INTEGER,
                        scheduled_date DATETIME,
                        next_run DATETIME,
                        last_run DATETIME,
                        status VARCHAR,
                        output_target VARCHAR,
                        session_id VARCHAR,
                        model VARCHAR,
                        endpoint_url VARCHAR,
                        run_count INTEGER,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        task_type VARCHAR DEFAULT 'llm',
                        action VARCHAR,
                        trigger_type VARCHAR DEFAULT 'schedule',
                        trigger_event VARCHAR,
                        trigger_count INTEGER,
                        trigger_counter INTEGER DEFAULT 0
                    )
                """))
                conn.execute(text("""
                    INSERT INTO scheduled_tasks
                    SELECT id, owner, name, prompt, schedule, scheduled_time,
                           scheduled_day, scheduled_date, next_run, last_run,
                           status, output_target, session_id, model, endpoint_url,
                           run_count, created_at, updated_at,
                           task_type, action, trigger_type, trigger_event,
                           trigger_count, trigger_counter
                    FROM _old_scheduled_tasks
                """))
                conn.execute(text("DROP TABLE _old_scheduled_tasks"))

            conn.commit()
    except Exception as e:
        logging.getLogger(__name__).warning(f"scheduled_tasks rebuild: {e}")


def _migrate_drop_ping_notes_tasks():
    """One-time cleanup: ping_notes and ping_events used to be seeded as
    user-facing tasks. They're now pure background scanners inside the
    scheduler (no LLM, don't belong in the Tasks UI). Remove existing rows
    + their runs for both. (tidy_sessions/documents/research stay as tasks.)"""
    targets = ("ping_notes", "ping_events")
    try:
        with engine.connect() as conn:
            for action in targets:
                conn.execute(text(
                    "DELETE FROM task_runs WHERE task_id IN "
                    "(SELECT id FROM scheduled_tasks WHERE action=:a)"
                ), {"a": action})
                r = conn.execute(text("DELETE FROM scheduled_tasks WHERE action=:a"), {"a": action})
                if r.rowcount:
                    logging.getLogger(__name__).info(f"Dropped {r.rowcount} {action} task row(s)")
            conn.commit()
    except Exception as e:
        logging.getLogger(__name__).debug(f"drop_ping_notes_tasks: {e}")


class Note(TimestampMixin, Base):
    """A Google Keep-style note or checklist."""
    __tablename__ = "notes"

    id         = Column(String, primary_key=True, index=True)
    owner      = Column(String, nullable=True, index=True)
    title      = Column(String, default="")
    content    = Column(Text, nullable=True)
    items      = Column(Text, nullable=True)       # JSON string of [{text, done}]
    note_type  = Column(String, default="note")     # "note" or "checklist"
    color      = Column(String, nullable=True)
    label      = Column(String, nullable=True)
    pinned     = Column(Boolean, default=False)
    archived   = Column(Boolean, default=False)
    due_date   = Column(String, nullable=True)
    source     = Column(String, default="user")     # "user" or "agent"
    session_id = Column(String, nullable=True)
    sort_order = Column(Integer, default=0)
    image_url  = Column(String, nullable=True)      # uploaded image URL (relative path)
    gallery_id = Column(String, nullable=True, index=True)  # stable Gallery image for drawings
    repeat     = Column(String, default="none")     # none, daily, weekly, monthly, yearly
    # Auto-AI fields — populated by /api/notes/{id}/classify. The classification
    # JSON shape is { kind, solvable, confidence, task_prompt, tools, items?: [...] }.
    # Content hash gates re-classification (avoid LLM spend on every save).
    ai_classification = Column(Text, nullable=True)
    ai_content_hash   = Column(String, nullable=True)
    # Chat session spawned by the note's "Agent" button (solve-this-todo).
    # The note shows a clickable tag that opens this session for review.
    agent_session_id  = Column(String, nullable=True)


class CalendarCal(TimestampMixin, Base):
    """A calendar (e.g. 'Personal', 'TimeTree')."""
    __tablename__ = "calendars"

    id    = Column(String, primary_key=True, index=True)
    owner = Column(String, nullable=True, index=True)
    name  = Column(String, nullable=False)
    color = Column(String, default="#5b8abf")
    source = Column(String, default="local")  # "local" or "caldav"
    # UUID of the CalDAV account in user prefs that owns this calendar.
    # NULL for local calendars and for CalDAV calendars created before
    # multi-account support was added (treated as "use any configured account").
    account_id = Column(String, nullable=True, index=True)
    caldav_base_url = Column(String, nullable=True)

    events = relationship("CalendarEvent", back_populates="calendar", cascade="all, delete-orphan")


class CalendarEvent(TimestampMixin, Base):
    """A calendar event."""
    __tablename__ = "calendar_events"

    uid         = Column(String, primary_key=True, index=True)
    calendar_id = Column(String, ForeignKey("calendars.id"), nullable=False, index=True)
    summary     = Column(String, nullable=False, default="")
    description = Column(Text, default="")
    location    = Column(String, default="")
    dtstart     = Column(DateTime, nullable=False, index=True)
    dtend       = Column(DateTime, nullable=False)
    all_day     = Column(Boolean, default=False)
    # True when dtstart/dtend are stored as UTC instants (set on import paths
    # that preserve the source TZID). False = legacy naive-local. Drives the
    # `Z`-suffix on serialization so the frontend interprets correctly.
    is_utc      = Column(Boolean, default=False, nullable=False)
    rrule       = Column(String, default="")
    recurrence_exdates = Column(Text, default="")  # JSON list of skipped occurrence starts
    color       = Column(String, nullable=True)  # per-event color override
    status      = Column(String, default="confirmed")  # confirmed, cancelled
    importance  = Column(String, default="normal")    # low | normal | high | critical
    event_type  = Column(String, nullable=True)        # work | personal | health | travel | meal | social | admin | other
    last_pinged = Column(DateTime, nullable=True)      # last time the assistant pinged about this event
    # "caldav" = pulled from a CalDAV server (so the sync may prune it when it
    # vanishes upstream). NULL/local = created locally (agent, email triage, or
    # a UI event whose write-back failed) and must NOT be pruned by the sync.
    origin      = Column(String, nullable=True, index=True)
    remote_href = Column(String, nullable=True)        # CalDAV object URL for updates/deletes
    remote_etag = Column(String, nullable=True)        # Last seen CalDAV ETag, when available
    caldav_sync_pending = Column(String, nullable=True) # create | update | delete retry marker
    # Provenance for events extracted from email. UID/folder form the frontend
    # deep link: #email=<folder>:<imap uid>.
    source_email_uid = Column(String, nullable=True, index=True)
    source_email_folder = Column(String, nullable=True)
    source_email_account_id = Column(String, nullable=True, index=True)
    source_email_message_id = Column(String, nullable=True, index=True)

    calendar = relationship("CalendarCal", back_populates="events")


class EmailCalendarInvitation(TimestampMixin, Base):
    """Revision/tombstone state for one owner's email invitation source."""
    __tablename__ = "email_calendar_invitations"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, index=True)
    sender = Column(String, nullable=False)
    source_uid = Column(String, nullable=False)
    recurrence_id = Column(String, nullable=False, default="")
    event_uid = Column(String, nullable=True)
    sequence = Column(Integer, nullable=False, default=0)
    stamp = Column(String, nullable=False, default="")
    cancelled = Column(Boolean, nullable=False, default=False)


class CalendarDeletedEvent(TimestampMixin, Base):
    """Hidden CalDAV delete tombstone retained until remote delete succeeds."""
    __tablename__ = "caldav_deleted_events"

    uid = Column(String, primary_key=True, index=True)
    owner = Column(String, nullable=True, index=True)
    calendar_id = Column(String, nullable=True, index=True)
    remote_href = Column(String, nullable=True)
    remote_etag = Column(String, nullable=True)
    caldav_base_url = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)


class Integration(TimestampMixin, Base):
    """An external service connection (email, RSS, webhook, etc.)."""
    __tablename__ = "integrations"

    id     = Column(String, primary_key=True, index=True)
    owner  = Column(String, nullable=True, index=True)
    name   = Column(String, nullable=False)
    type   = Column(String, nullable=False)  # "email", "rss", "webhook"
    config = Column(JSON, nullable=True)     # type-specific config
    enabled = Column(Boolean, default=True)





def _migrate_email_account_default_invariant():
    """Normalize legacy duplicates and install durable at-most-one enforcement.

    Older databases only had a non-unique ``(owner, is_default)`` lookup index.
    Keep the oldest default deterministically in each normalized owner scope,
    then add the same partial functional unique index used for fresh schemas.
    """
    dialect_name = engine.dialect.name
    index_ddl = _EMAIL_ACCOUNT_DEFAULT_INDEX_DDL.get(dialect_name)
    if index_ddl is None:
        logger.warning(
            "Email-account default uniqueness is not available for database "
            "dialect %s; mutations remain serialized but are not protected by "
            "a database constraint",
            dialect_name,
        )
        return

    try:
        with engine.begin() as conn:
            if not inspect(conn).has_table(EmailAccount.__tablename__):
                return
            default_rows = conn.execute(text("""
                SELECT id, owner
                FROM email_accounts
                WHERE is_default IS TRUE
                ORDER BY
                    COALESCE(owner, ''),
                    CASE WHEN created_at IS NULL THEN 1 ELSE 0 END,
                    created_at,
                    id
            """)).mappings()
            seen_owner_keys = set()
            duplicate_ids = []
            for row in default_rows:
                owner_key = row["owner"] or ""
                if owner_key in seen_owner_keys:
                    duplicate_ids.append(row["id"])
                else:
                    seen_owner_keys.add(owner_key)

            for account_id in duplicate_ids:
                conn.execute(
                    text("UPDATE email_accounts SET is_default = :value WHERE id = :id"),
                    {"value": False, "id": account_id},
                )
            conn.execute(text(index_ddl))

        if duplicate_ids:
            logger.warning(
                "Normalized %d duplicate default email account(s) before "
                "installing %s",
                len(duplicate_ids),
                _EMAIL_ACCOUNT_DEFAULT_INDEX,
            )
    except Exception:
        # Starting without the constraint would silently retain the race this
        # migration is intended to close.  Fail startup so an operator sees and
        # can repair an incompatible schema instead of accepting unsafe writes.
        logger.exception("Failed to enforce the email-account default invariant")
        raise


def _migrate_seed_email_account():
    """Atomically seed one legacy default account when no account exists.

    Reading settings is intentionally done before taking the owner mutex.  The
    decisive emptiness check and insert share one locked transaction, so two
    application workers starting together cannot both seed a default row.
    """
    import json as _json
    import uuid as _uuid

    settings_file = Path(SETTINGS_FILE)
    if not settings_file.exists():
        return
    try:
        s = _json.loads(settings_file.read_text(encoding="utf-8"))
    except Exception:
        return

    imap_host = (s.get("imap_host") or "").strip()
    smtp_host = (s.get("smtp_host") or "").strip()
    if not imap_host and not smtp_host:
        return

    db = None
    try:
        if not inspect(engine).has_table(EmailAccount.__tablename__):
            return
        db = SessionLocal()
        lock_email_account_owner_mutations(db, "")
        existing = db.execute(text("SELECT COUNT(*) FROM email_accounts")).scalar() or 0
        if existing > 0:
            return

        now = utcnow_naive()
        db.execute(text("""
            INSERT INTO email_accounts
              (id, owner, name, is_default, enabled,
               imap_host, imap_port, imap_user, imap_password, imap_starttls,
               smtp_host, smtp_port, smtp_user, smtp_password,
               from_address, created_at, updated_at)
            VALUES
              (:id, :owner, :name, :is_default, :enabled,
               :imap_host, :imap_port, :imap_user, :imap_password, :imap_starttls,
               :smtp_host, :smtp_port, :smtp_user, :smtp_password,
               :from_address, :created_at, :updated_at)
        """), {
            "id": _uuid.uuid4().hex,
            "owner": None,
            "name": "Default",
            "is_default": True,
            "enabled": True,
            "imap_host": imap_host,
            "imap_port": int(s.get("imap_port") or 993),
            "imap_user": s.get("imap_user") or "",
            "imap_password": s.get("imap_password") or "",
            "imap_starttls": bool(s.get("imap_starttls", True)),
            "smtp_host": smtp_host,
            "smtp_port": int(s.get("smtp_port") or 465),
            "smtp_user": s.get("smtp_user") or "",
            "smtp_password": s.get("smtp_password") or "",
            "from_address": s.get("email_from") or "",
            "created_at": now,
            "updated_at": now,
        })
        db.commit()
        logger.info("Seeded email_accounts 'Default' from settings.json")
    except Exception as e:
        if db is not None:
            db.rollback()
        logger.warning("seed email account migration: %s", e)
    finally:
        if db is not None:
            db.close()


def _migrate_backfill_task_folders():
    """Backfill folder='Tasks' on pre-existing task/research sessions.

    Sessions created by the task scheduler (LLM tasks, action tasks, research
    runs) now set folder='Tasks' at creation time.  This migration tags any
    older sessions that predate that assignment.  Idempotent — only touches
    rows where folder is NULL or empty and the title matches known prefixes.
    """
    try:
        with engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(sessions)"))]
            if "folder" not in cols:
                return
            res = conn.execute(text(
                "UPDATE sessions SET folder = 'Tasks' "
                "WHERE (folder IS NULL OR folder = '') "
                "AND (name LIKE '[Task] %' OR name LIKE '[Research] %')"
            ))
            conn.commit()
            if res.rowcount:
                logging.getLogger(__name__).info(
                    f"Backfilled folder='Tasks' on {res.rowcount} task/research sessions")
    except Exception as e:
        logging.getLogger(__name__).warning(f"task folder backfill: {e}")


def _fts_content_expr(alias):
    return (
        f"CASE WHEN instr(COALESCE({alias}.content, ''), ';base64,') > 0 "
        f"OR instr(COALESCE({alias}.content, ''), 'data:image/') > 0 "
        f"OR instr(COALESCE({alias}.content, ''), 'data:audio/') > 0 "
        "THEN '[inline media omitted from search index]' "
        f"ELSE COALESCE({alias}.content, '') END"
    )


def _migrate_chat_messages_fts():
    """Create and backfill the session transcript FTS index for SQLite."""
    if not DATABASE_URL.startswith("sqlite"):
        return

    db_path = DATABASE_URL.replace("sqlite:///", "")
    if db_path == ":memory:":
        return
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        fts_content_expr_new = _fts_content_expr("new")
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp._odysseus_fts5_probe USING fts5(content)")
            conn.execute("DROP TABLE IF EXISTS temp._odysseus_fts5_probe")
        except Exception as e:
            logging.getLogger(__name__).warning(f"chat_messages FTS migration skipped; FTS5 unavailable: {e}")
            return

        conn.executescript(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS chat_messages_fts USING fts5(
                content,
                message_id UNINDEXED,
                session_id UNINDEXED,
                role UNINDEXED
            );

            DROP TRIGGER IF EXISTS chat_messages_fts_ai;
            DROP TRIGGER IF EXISTS chat_messages_fts_ad;
            DROP TRIGGER IF EXISTS chat_messages_fts_au;

            CREATE TRIGGER IF NOT EXISTS chat_messages_fts_ai
            AFTER INSERT ON chat_messages BEGIN
                INSERT INTO chat_messages_fts(content, message_id, session_id, role)
                VALUES ({fts_content_expr_new}, new.id, new.session_id, new.role);
            END;

            CREATE TRIGGER IF NOT EXISTS chat_messages_fts_ad
            AFTER DELETE ON chat_messages BEGIN
                DELETE FROM chat_messages_fts WHERE message_id = old.id;
            END;

            CREATE TRIGGER IF NOT EXISTS chat_messages_fts_au
            AFTER UPDATE ON chat_messages BEGIN
                DELETE FROM chat_messages_fts WHERE message_id = old.id;
                INSERT INTO chat_messages_fts(content, message_id, session_id, role)
                VALUES ({fts_content_expr_new}, new.id, new.session_id, new.role);
            END;
            """
        )
        # message_id is deliberately UNINDEXED in the FTS table.  A correlated
        # NOT EXISTS against it therefore becomes quadratic once the transcript
        # grows large, even when there is nothing left to backfill.  Build a
        # temporary indexed set only when the row counts show that reconciliation
        # is needed.  Normal inserts/updates/deletes stay synchronized by the
        # triggers above.
        chat_count = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM chat_messages_fts").fetchone()[0]
        if chat_count != fts_count:
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS _odysseus_fts_message_ids "
                "(message_id TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            conn.execute("DELETE FROM temp._odysseus_fts_message_ids")
            conn.execute(
                "INSERT OR IGNORE INTO temp._odysseus_fts_message_ids(message_id) "
                "SELECT message_id FROM chat_messages_fts"
            )
            conn.execute(
                f"""
                INSERT INTO chat_messages_fts(content, message_id, session_id, role)
                SELECT {_fts_content_expr("cm")}, cm.id, cm.session_id, cm.role
                FROM chat_messages cm
                LEFT JOIN temp._odysseus_fts_message_ids known ON known.message_id = cm.id
                WHERE known.message_id IS NULL
                """
            )
        _scrub_legacy_chat_message_fts_media(conn)
        conn.commit()
    except Exception as e:
        logging.getLogger(__name__).warning(f"chat_messages FTS migration failed: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _scrub_legacy_chat_message_fts_media(conn) -> None:
    """Replace already-indexed inline media rows with searchable text only."""
    try:
        from src.attachment_refs import search_index_text
    except Exception as e:
        logging.getLogger(__name__).warning(f"chat_messages FTS media scrub skipped: {e}")
        return

    try:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content
            FROM chat_messages
            WHERE instr(COALESCE(content, ''), ';base64,') > 0
               OR instr(COALESCE(content, ''), 'data:image/') > 0
               OR instr(COALESCE(content, ''), 'data:audio/') > 0
            """
        ).fetchall()
        for message_id, session_id, role, content in rows:
            conn.execute("DELETE FROM chat_messages_fts WHERE message_id = ?", (message_id,))
            conn.execute(
                """
                INSERT INTO chat_messages_fts(content, message_id, session_id, role)
                VALUES (?, ?, ?, ?)
                """,
                (search_index_text(content), message_id, session_id, role),
            )
    except Exception as e:
        logging.getLogger(__name__).warning(f"chat_messages FTS media scrub failed: {e}")


def _migrate_encrypt_endpoint_keys():
    """Encrypt any plaintext provider API keys in model_endpoints. Idempotent;
    raw SQL so the EncryptedText decorator isn't applied twice."""
    try:
        from src.secret_storage import encrypt, is_encrypted
    except Exception as e:
        logger.warning(f"secret_storage import failed; skipping endpoint-key migration: {e}")
        return
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, api_key FROM model_endpoints")).fetchall()
            migrated = 0
            for rid, key in rows:
                if key and not is_encrypted(key):
                    conn.execute(text("UPDATE model_endpoints SET api_key = :k WHERE id = :id"),
                                 {"k": encrypt(key), "id": rid})
                    migrated += 1
            if migrated:
                conn.commit()
                logger.info(f"Encrypted plaintext API key on {migrated} endpoint row(s)")
    except Exception as e:
        logger.warning(f"Endpoint-key encryption migration skipped: {e}")


def _migrate_encrypt_signatures():
    """Encrypt any plaintext signature images still in the signatures table.
    Idempotent — rows already prefixed with `enc:` are skipped. Uses raw SQL
    so the EncryptedText type decorator isn't applied twice."""
    try:
        from src.secret_storage import encrypt, is_encrypted
    except Exception as e:
        logger.warning(f"secret_storage import failed; skipping signature migration: {e}")
        return
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, data_png, svg FROM signatures"
            )).fetchall()
            migrated = 0
            for rid, data_png, svg in rows:
                updates = {}
                if data_png and not is_encrypted(data_png):
                    updates["data_png"] = encrypt(data_png)
                if svg and not is_encrypted(svg):
                    updates["svg"] = encrypt(svg)
                if updates:
                    sets = ", ".join(f"{k} = :{k}" for k in updates)
                    conn.execute(text(f"UPDATE signatures SET {sets} WHERE id = :id"), {**updates, "id": rid})
                    migrated += 1
            if migrated:
                conn.commit()
                logger.info(f"Encrypted plaintext signature(s) on {migrated} row(s)")
    except Exception as e:
        logger.warning(f"Signature encryption migration skipped: {e}")


def _migrate_encrypt_email_passwords():
    """Encrypt any plaintext IMAP/SMTP passwords still in the email_accounts
    table. Idempotent — rows already prefixed with `enc:` are skipped.
    Safe to run on every startup."""
    try:
        from src.secret_storage import encrypt, is_encrypted
    except Exception as e:
        logger.warning(f"secret_storage import failed; skipping password migration: {e}")
        return
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, imap_password, smtp_password FROM email_accounts"
            )).fetchall()
            migrated = 0
            for row in rows:
                rid, imap_pw, smtp_pw = row
                updates = {}
                if imap_pw and not is_encrypted(imap_pw):
                    updates["imap_password"] = encrypt(imap_pw)
                if smtp_pw and not is_encrypted(smtp_pw):
                    updates["smtp_password"] = encrypt(smtp_pw)
                if updates:
                    sets = ", ".join(f"{k} = :{k}" for k in updates)
                    params = {**updates, "id": rid}
                    conn.execute(text(f"UPDATE email_accounts SET {sets} WHERE id = :id"), params)
                    migrated += 1
            if migrated:
                conn.commit()
                logger.info(f"Encrypted plaintext passwords on {migrated} email account row(s)")
    except Exception as e:
        logger.warning(f"Password migration failed (will retry next start): {e}")


def _add_column(table, column, ddl, index=None, unique=False):
    """Add a column the model gained after its table shipped. Idempotent."""
    try:
        with engine.begin() as conn:
            schema = inspect(conn)
            if not schema.has_table(table):
                return
            if column not in {c["name"] for c in schema.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                logger.info("Migrated: added %s.%s", table, column)
            if index:
                conn.execute(text(
                    f"CREATE {'UNIQUE ' if unique else ''}INDEX IF NOT EXISTS {index} ON {table} ({column})"
                ))
    except Exception as e:
        if (table, column) in _REQUIRED_COLUMNS:
            raise
        logger.warning("Adding column %s.%s failed: %s", table, column, e)


# Session endpoint binding and the task authority snapshot gate access, so
# startup stops rather than run without them.
_REQUIRED_COLUMNS = {("sessions", "endpoint_id"), ("scheduled_tasks", "request_authority_json")}

# Runs in order after create_all. A tuple is (table, column, DDL[, index[, unique]])
# for _add_column; a callable is a data migration that depends on the columns above it.
_MIGRATIONS = (
    ("model_endpoints", "hidden_models", "TEXT"),
    ("model_endpoints", "cached_models", "TEXT"),
    ("model_endpoints", "pinned_models", "TEXT"),
    ("notes", "sort_order", "INTEGER DEFAULT 0"),
    ("notes", "image_url", "TEXT"),
    ("notes", "repeat", "TEXT DEFAULT 'none'"),
    ("notes", "ai_classification", "TEXT"),
    ("notes", "ai_content_hash", "TEXT"),
    ("notes", "agent_session_id", "TEXT"),
    ("model_endpoints", "model_type", "TEXT DEFAULT 'llm'"),
    ("model_endpoints", "endpoint_kind", "TEXT DEFAULT 'auto'"),
    ("model_endpoints", "model_refresh_mode", "TEXT DEFAULT 'auto'"),
    ("model_endpoints", "model_refresh_interval", "INTEGER"),
    ("model_endpoints", "model_refresh_timeout", "INTEGER"),
    ("model_endpoints", "owner", "VARCHAR", "ix_model_endpoints_owner"),
    ("model_endpoints", "provider_auth_id", "VARCHAR", "ix_model_endpoints_provider_auth_id"),
    ("model_endpoints", "supports_tools", "BOOLEAN"),
    ("model_endpoints", "model_tool_modes", "TEXT"),
    ("task_runs", "model", "TEXT"),
    ("sessions", "owner", "TEXT", "ix_sessions_owner"),
    ("documents", "archived", "BOOLEAN DEFAULT FALSE"),
    ("sessions", "last_message_at", "TIMESTAMP"),
    _migrate_backfill_last_message_at,
    ("sessions", "memory_extraction_enabled", "BOOLEAN DEFAULT TRUE"),
    ("sessions", "memory_injection_enabled", "BOOLEAN DEFAULT TRUE"),
    ("sessions", "skill_injection_enabled", "BOOLEAN DEFAULT TRUE"),
    ("sessions", "thinking_mode", "VARCHAR DEFAULT 'off'"),
    ("sessions", "temperature_override", "FLOAT"),
    ("sessions", "max_tokens_override", "INTEGER"),
    ("sessions", "folder", "TEXT"),
    ("sessions", "cwd", "TEXT"),
    ("sessions", "endpoint_id", "VARCHAR", "ix_sessions_endpoint_id"),
    ("sessions", "total_input_tokens", "INTEGER DEFAULT 0"),
    ("sessions", "total_output_tokens", "INTEGER DEFAULT 0"),
    ("sessions", "total_cost_usd", "REAL DEFAULT 0.0"),
    ("sessions", "mode", "TEXT"),
    ("memories", "owner", "TEXT", "ix_memories_owner"),
    ("gallery_images", "owner", "TEXT", "ix_gallery_images_owner"),
    ("user_tools", "owner", "TEXT", "ix_user_tools_owner"),
    ("comparisons", "owner", "TEXT", "ix_comparisons_owner"),
    ("api_tokens", "owner", "TEXT", "ix_api_tokens_owner"),
    ("documents", "owner", "TEXT", "ix_documents_owner"),
    ("gallery_images", "caption", "TEXT DEFAULT ''"),
    # Existing tokens get `chat`, the one scope they could already use.
    ("api_tokens", "scopes", "TEXT NOT NULL DEFAULT 'chat'"),
    # Session-linked documents take their session's owner before the admin sweep.
    _migrate_backfill_document_owner_from_session,
    _migrate_assign_legacy_owner,
    ("documents", "tidy_verdict", "VARCHAR"),
    ("documents", "source_email_uid", "VARCHAR"),
    ("documents", "source_email_folder", "VARCHAR"),
    ("documents", "source_email_account_id", "VARCHAR"),
    ("documents", "source_email_message_id", "VARCHAR", "ix_documents_source_email_message_id"),
    ("calendar_events", "source_email_uid", "VARCHAR"),
    ("calendar_events", "source_email_folder", "VARCHAR"),
    ("calendar_events", "source_email_account_id", "VARCHAR"),
    ("calendar_events", "source_email_message_id", "VARCHAR", "ix_calendar_events_source_email_message_id"),
    ("mcp_servers", "oauth_config", "TEXT"),
    ("email_accounts", "oauth_provider", "TEXT"),
    ("email_accounts", "oauth_access_token", "TEXT"),
    ("email_accounts", "oauth_refresh_token", "TEXT"),
    ("email_accounts", "oauth_token_expiry", "TEXT"),
    ("email_accounts", "display_name", "TEXT"),
    ("scheduled_tasks", "task_type", "VARCHAR DEFAULT 'llm'"),
    ("scheduled_tasks", "action", "VARCHAR"),
    ("scheduled_tasks", "trigger_type", "VARCHAR DEFAULT 'schedule'"),
    ("scheduled_tasks", "trigger_event", "VARCHAR"),
    ("scheduled_tasks", "trigger_count", "INTEGER"),
    ("scheduled_tasks", "trigger_counter", "INTEGER DEFAULT 0"),
    # The rebuild copies only the columns above, so later scheduled_tasks columns come after it.
    _migrate_make_task_schedule_nullable,
    ("scheduled_tasks", "request_authority_json", "TEXT"),
    ("mcp_servers", "disabled_tools", "TEXT"),
    # EncryptedText stores its ciphertext as TEXT.
    ("mcp_servers", "oauth_tokens", "TEXT"),
    ("scheduled_tasks", "cron_expression", "VARCHAR"),
    ("scheduled_tasks", "then_task_id", "VARCHAR"),
    ("scheduled_tasks", "webhook_token", "VARCHAR", "ix_scheduled_tasks_webhook", True),
    ("scheduled_tasks", "notifications_enabled", "BOOLEAN DEFAULT TRUE"),
    _migrate_drop_ping_notes_tasks,
    ("sessions", "crew_member_id", "TEXT"),
    ("scheduled_tasks", "crew_member_id", "TEXT"),
    ("crew_members", "is_default_assistant", "BOOLEAN DEFAULT FALSE"),
    ("crew_members", "timezone", "TEXT"),
    ("email_accounts", "smtp_security", "TEXT DEFAULT 'ssl'"),
    _migrate_email_account_default_invariant,
    _migrate_seed_email_account,
    ("calendar_events", "importance", "TEXT DEFAULT 'normal'"),
    ("calendar_events", "event_type", "TEXT"),
    ("calendar_events", "last_pinged", "TIMESTAMP"),
    ("calendar_events", "is_utc", "BOOLEAN DEFAULT FALSE NOT NULL"),
    ("calendar_events", "origin", "TEXT", "ix_calendar_events_origin"),
    ("calendars", "account_id", "TEXT", "ix_calendars_account_id"),
    ("calendar_events", "remote_href", "TEXT"),
    ("calendar_events", "remote_etag", "TEXT"),
    ("calendar_events", "caldav_sync_pending", "TEXT"),
    ("calendars", "caldav_base_url", "TEXT"),
    ("calendar_events", "recurrence_exdates", "TEXT DEFAULT ''"),
    ("notes", "gallery_id", "VARCHAR", "ix_notes_gallery_id"),
    _migrate_chat_messages_fts,
    _migrate_encrypt_email_passwords,
    _migrate_encrypt_signatures,
    _migrate_encrypt_endpoint_keys,
    _migrate_backfill_task_folders,
)


def init_db():
    """Create the tables and bring an existing database up to the current schema."""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    _migrate_model_endpoints()
    Base.metadata.create_all(bind=engine)
    # The file holds token hashes and encrypted keys; create_all makes it at the umask default.
    db_path = _sqlite_db_path(engine.url)
    if db_path is not None:
        # safe_chmod returns False as a Windows no-op, which is not a failure.
        if not safe_chmod(db_path, 0o600) and not IS_WINDOWS:
            logger.warning(
                "Could not restrict %s to 0o600; it holds secrets and may be "
                "world-readable. Check filesystem permissions and ownership.",
                db_path,
            )
        # A stale sidecar from an older 0o644 install can still hold secret pages.
        for suffix in _SQLITE_SIDECARS:
            sidecar = db_path + suffix
            if (
                os.path.exists(sidecar)
                and not safe_chmod(sidecar, 0o600)
                and not IS_WINDOWS
            ):
                logger.warning(
                    "Could not restrict %s to 0o600; it may expose DB pages.",
                    sidecar,
                )
    for step in _MIGRATIONS:
        if callable(step):
            step()
        else:
            _add_column(*step)


def get_db():
    """
    Dependency to get a database session.
    Used in FastAPI routes to inject database sessions.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from contextlib import contextmanager
from typing import Generator

@contextmanager
def get_db_session() -> Generator:
    """Context manager for database sessions"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_stats():
    """Get database statistics"""
    with get_db_session() as db:
        stats = {
            'total_sessions': db.query(Session).count(),
            'active_sessions': db.query(Session).filter(Session.archived == False).count(),
            'archived_sessions': db.query(Session).filter(Session.archived == True).count(),
            'total_messages': db.query(ChatMessage).count(),
            'total_memories': db.query(Memory).count()
        }
        return stats

def get_detailed_stats():
    """Session counts plus the SQLite file size in MB."""
    stats = get_session_stats()
    db_path = _sqlite_db_path(engine.url)
    stats['database_size_mb'] = (
        round(os.path.getsize(db_path) / (1024 * 1024), 2)
        if db_path and os.path.exists(db_path) else 0.0
    )
    return stats

def update_session_last_accessed(session_id: str):
    """Update the last_accessed timestamp for a session"""
    with get_db_session() as db:
        db_session = db.query(Session).filter(Session.id == session_id).first()
        if db_session:
            db_session.last_accessed = utcnow_naive()
            db.commit()
            return True
    return False

def get_session_mode(session_id: str):
    """Return a session's persisted `mode`, or None if unset/unknown.

    Best-effort: never raises (returns None on any DB error) so callers on hot
    request paths needn't guard it. Routed through get_db_session() so the
    connection is always returned to the pool."""
    try:
        with get_db_session() as db:
            return db.query(Session.mode).filter(Session.id == session_id).scalar()
    except Exception:
        logger.warning("Failed to read mode for session %s", session_id)
        return None

def set_session_mode(session_id: str, mode: str) -> bool:
    """Persist a session's `mode`. Best-effort: never raises, returns success.

    Routed through get_db_session() so a failure mid-write (e.g. a SQLite
    'database is locked' under concurrent streams) still returns the connection
    to the pool instead of leaking it — repeated leaks would exhaust it."""
    try:
        with get_db_session() as db:
            db.query(Session).filter(Session.id == session_id).update({"mode": mode})
        return True
    except Exception:
        logger.warning("Failed to persist mode %r for session %s", mode, session_id)
        return False


def get_upcoming_events(owner, horizon_days: int = 60, limit: int = 40):
    """Upcoming, non-cancelled events as {uid, title, start} dicts, soonest first.

    owner=None means NO owner scoping (single-user / legacy). Multi-user callers
    MUST pass the owning username — otherwise they read every tenant's events.
    The autonomous email->calendar pass relies on this to avoid disclosing (and
    acting on) other users' calendars."""
    from datetime import timedelta
    now = utcnow_naive()
    with get_db_session() as db:
        q = db.query(CalendarEvent).join(CalendarCal).filter(
            CalendarEvent.dtstart >= now,
            CalendarEvent.dtstart <= now + timedelta(days=horizon_days),
            CalendarEvent.status != "cancelled",
        )
        if owner is not None:
            q = q.filter(CalendarCal.owner == owner)
        return [
            {
                "uid": e.uid,
                "title": e.summary or "",
                "start": e.dtstart.isoformat() if e.dtstart else "",
            }
            for e in q.order_by(CalendarEvent.dtstart).limit(limit).all()
        ]

