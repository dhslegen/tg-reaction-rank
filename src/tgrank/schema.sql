-- 版本 1。所有时间都是 UTC unix 秒。
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- chat_id 统一用 Telethon 的 marked id：超级群/频道为 -100xxxx，普通群为 -xxxx
CREATE TABLE IF NOT EXISTS chats (
  chat_id           INTEGER PRIMARY KEY,
  title             TEXT NOT NULL,
  kind              TEXT NOT NULL,
  username          TEXT,
  is_forum          INTEGER NOT NULL DEFAULT 0,
  sync_enabled      INTEGER NOT NULL DEFAULT 0,
  history_complete  INTEGER NOT NULL DEFAULT 0,
  last_sync_at      INTEGER,
  last_refresh_at   INTEGER,
  last_calibrate_at INTEGER,
  last_error        TEXT,
  created_at        INTEGER NOT NULL
);

-- 存全部消息：新消息入库时还没有反应，要靠后续刷新补上；导入时要沿回复链解析话题
CREATE TABLE IF NOT EXISTS messages (
  chat_id       INTEGER NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
  msg_id        INTEGER NOT NULL,
  date          INTEGER NOT NULL,
  sender        TEXT NOT NULL DEFAULT '',
  text          TEXT NOT NULL DEFAULT '',
  media         TEXT,
  reply_to      INTEGER,
  topic_id      INTEGER,
  api_synced_at INTEGER,          -- 非空表示来自 API 同步，导入时不得覆盖其正文与反应
  PRIMARY KEY (chat_id, msg_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS messages_by_date ON messages(chat_id, date);

-- 只含有反应的消息；kind=emoji 时 key 为去掉 U+FE0F 的表情，custom_emoji 时为 document_id
CREATE TABLE IF NOT EXISTS reactions (
  chat_id INTEGER NOT NULL,
  msg_id  INTEGER NOT NULL,
  kind    TEXT NOT NULL CHECK (kind IN ('emoji', 'custom_emoji', 'paid', 'unknown')),
  key     TEXT NOT NULL,
  count   INTEGER NOT NULL CHECK (count > 0),
  PRIMARY KEY (chat_id, msg_id, kind, key),
  FOREIGN KEY (chat_id, msg_id) REFERENCES messages(chat_id, msg_id) ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS topics (
  chat_id  INTEGER NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
  topic_id INTEGER NOT NULL,
  title    TEXT NOT NULL,
  PRIMARY KEY (chat_id, topic_id)
) WITHOUT ROWID;

-- 榜单 = 名称 + 表情权重表；未列出的普通表情用 default_weight
CREATE TABLE IF NOT EXISTS boards (
  id                  INTEGER PRIMARY KEY,
  name                TEXT NOT NULL UNIQUE,
  default_weight      REAL NOT NULL DEFAULT 1,
  custom_emoji_weight REAL NOT NULL DEFAULT 1,
  paid_weight         REAL NOT NULL DEFAULT 1,
  push_enabled        INTEGER NOT NULL DEFAULT 0,
  builtin             INTEGER NOT NULL DEFAULT 0,
  position            INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS board_weights (
  board_id INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
  emoji    TEXT NOT NULL,
  weight   REAL NOT NULL,
  PRIMARY KEY (board_id, emoji)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS admin_sessions (
  token_hash TEXT PRIMARY KEY,
  expires_at INTEGER NOT NULL
);
