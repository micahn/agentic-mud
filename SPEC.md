# Club MUD — Specification

**Status:** draft for build.
**Scope of this document:** M1 is fully specified and normative. M2–M5 define
contracts and acceptance criteria only; they are specified in detail when
reached.

**Working title:** "Club MUD" (name to be chosen by the club).

---

## 1. Summary

A text MUD run as one central server for the club. The server owns the world,
the rules, the persistence, and the protocol. Club members write **clients**:
terminal clients, browser clients, and later hardware clients. The LLM is not a
game engine and is not in M1 at all.

Decisions taken during the grilling session (rationale in §17):

| Question | Decision |
|---|---|
| Who builds what | Server: one owner. Clients: club members. |
| Server topology | One central club server; shared persistent world. |
| First working proof | Text MUD playable on its own, no hardware, no LLM. |
| Wire protocol | WebSocket + JSON. Text commands in, typed events out. |
| Server language | Python 3 + asyncio. |
| M1 content | Everything except combat: movement, objects, containers, locks, scripted NPCs, social verbs. |
| Multiplayer | Shared world with room presence, `say`, `emote`, `tell`, `who`. |
| World content | YAML files in the repo, validated, seeded into SQLite. |
| Identity | Name + password, persistent character. |
| Lifecycle | Persistent world; destructive reset via offline admin CLI. |
| M1 exit | 3+ members, their own clients, 20 minutes, no restart. |
| Network | Club-owned WireGuard tailnet. No public exposure. |
| M2 | IoT bridge. |
| M3+ | LLM narration, then procedural generation, then NPC agents. |

**Non-goals for M1:** combat, HP, death, LLM calls, MQTT, hardware, procedural
generation, web UI, public internet exposure, TLS termination, horizontal
scaling, accounts beyond name/password, in-game administration.

---

## 2. Guiding constraints

1. **The protocol is the product.** Members build against it, so it is
   versioned, documented, and covered by golden tests. Server internals may
   change freely; the wire contract may not break within v1.
2. **Hardware-agnostic.** The server has no concept of a lamp, a Pi, an ESP32,
   or a relay. It emits semantic events ("room darkened", "thunder"). M2 maps
   those to MQTT. Devices are member projects.
3. **The engine is authoritative.** Narration, when it arrives, is prose only.
   It never decides state.
4. **Deterministic core.** No wall-clock or randomness in game logic except a
   seeded RNG. The same command sequence on the same seed produces the same
   events.
5. **Degrade to static.** Any later layer (LLM, MQTT, agents) must be
   switch-off-able, and the game must remain fully playable with it off.
6. **Boring operations.** One process, one SQLite file, one config file. A club
   member should be able to run the whole thing on a laptop.

---

## 3. Architecture

```
                    club tailnet (WireGuard)
 members' clients ──────────┐
 (terminal, browser, etc.)  │  WebSocket + JSON
                            ▼
                 ┌─────────────────────────┐
                 │  mud server (asyncio)   │
                 │                         │
                 │  net/session ─ protocol │
                 │        │                │
                 │  command parser         │
                 │        │                │
                 │  engine (authoritative) │
                 │    │        │           │
                 │  SQLite    event bus    │
                 └─────────────────┬───────┘
                                   │ (M2) optional bridge
                                   ▼
                              MQTT broker
                                   │
                            members' devices
```

One asyncio process. One SQLite database in WAL mode. World state is held in
memory and written through to SQLite on every mutation. Every engine output is
an event on an internal bus; sessions subscribe and serialize to their socket.
No engine code writes to a socket directly.

**Why the bus matters now:** it is the seam every later layer hangs from. M2
subscribes and republishes to MQTT. M3 subscribes and appends narration. M5
subscribes for NPC observations. M1 must get this right even though nothing
else uses it yet.

### 3.1 Concurrency model

- Single event loop; no threads in M1.
- Each connection is one task; all mutations run on the loop, so no locks.
- A 1 Hz tick drives NPC wandering and, later, ambient events.
- Slow work (M3 LLM, M4 generation) runs in a separate task with a timeout and
  never blocks a command handler.
- SQLite writes are small and synchronous; acceptable at club scale. If a write
  fails, the command returns `error{code:"internal"}` and in-memory state is
  left unchanged (write first, then apply in memory).

### 3.2 Targets

| Metric | Target |
|---|---|
| Concurrent clients | 50 |
| Aggregate commands | 100/s |
| Command latency (no LLM) | p95 ≤ 100 ms |
| Cold start | ≤ 2 s |
| Database size | < 50 MB at M1 content scale |

---

## 4. Repository layout

```
.
├── pyproject.toml
├── README.md
├── SPEC.md                     # this document
├── docs/
│   ├── PROTOCOL.md             # normative client contract
│   ├── CONTENT.md              # world authoring guide
│   ├── CLIENTS.md              # how to write a client
│   └── OPERATIONS.md           # deploy, backup, reset, upgrade
├── src/mud/
│   ├── __main__.py             # server entry point
│   ├── config.py               # TOML + env
│   ├── bus.py                  # typed event bus
│   ├── protocol.py             # pydantic models, envelope, event types
│   ├── net.py                  # WebSocket server, sessions, rate limits
│   ├── auth.py                 # registration, login, scrypt
│   ├── engine/
│   │   ├── world.py            # state, mutations, transactions
│   │   ├── resolve.py          # target resolution
│   │   ├── commands.py         # verb handlers
│   │   ├── render.py           # text rendering per recipient
│   │   └── npc.py              # scripted dialogue, wandering
│   ├── storage/
│   │   ├── db.py               # connection, migrations
│   │   ├── schema.sql
│   │   └── repo.py             # queries
│   ├── content/
│   │   ├── models.py           # YAML schema (pydantic)
│   │   └── loader.py           # validate + seed
│   └── admin.py                # offline CLI
├── world/
│   ├── world.yaml              # name, start room, RNG seed
│   └── areas/*.yaml            # 30–40 rooms total
├── tests/
│   ├── scenarios/*.yaml        # golden transcripts
│   ├── test_protocol.py
│   ├── test_commands.py
│   ├── test_content.py
│   ├── test_auth.py
│   └── test_load.py
└── tools/
    └── refclient.py            # reference client + conformance runner
```

Dependencies: `websockets`, `pydantic` v2, `PyYAML`, `pytest`,
`pytest-asyncio`. Nothing else in M1. Python ≥ 3.11. M2 adds `aiomqtt`; M3 adds
an LLM client, both optional extras.

---

## 5. Data model (SQLite)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE world_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);  -- name, start_room, rng_seed, epoch, schema_version

CREATE TABLE players (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password      TEXT NOT NULL,          -- scrypt$n$r$p$salt$hash (base64)
  room_id       TEXT REFERENCES rooms(id),
  created_at    TEXT NOT NULL,
  last_seen     TEXT,
  is_admin      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE rooms (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  description   TEXT NOT NULL,
  area          TEXT,
  generated     INTEGER NOT NULL DEFAULT 0,  -- reserved for M4
  seed          TEXT,                        -- reserved for M4
  version       INTEGER NOT NULL DEFAULT 0   -- bumps on mutation, for narration cache
);

CREATE TABLE exits (
  room_id       TEXT NOT NULL REFERENCES rooms(id),
  direction     TEXT NOT NULL,
  target_id     TEXT NOT NULL REFERENCES rooms(id),
  locked        INTEGER NOT NULL DEFAULT 0,
  key_id        TEXT REFERENCES objects(id),
  label         TEXT,
  PRIMARY KEY (room_id, direction)
);

CREATE TABLE objects (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  description   TEXT,
  kind          TEXT NOT NULL DEFAULT 'item',  -- item | container | readable
  portable      INTEGER NOT NULL DEFAULT 1,
  readable_text TEXT,
  room_id       TEXT REFERENCES rooms(id),     -- null when carried or contained
  owner_id      INTEGER REFERENCES players(id),
  container_id  TEXT REFERENCES objects(id),
  state         TEXT NOT NULL DEFAULT '{}'     -- JSON: open, lit, ...
);

CREATE TABLE npcs (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  description   TEXT,
  room_id       TEXT REFERENCES rooms(id),
  dialogue      TEXT NOT NULL DEFAULT '{}',    -- JSON: greeting, default, topics
  wander        INTEGER NOT NULL DEFAULT 0,
  wander_every  INTEGER NOT NULL DEFAULT 15    -- seconds
);

CREATE TABLE event_log (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id  TEXT NOT NULL,
  ts        TEXT NOT NULL,
  type      TEXT NOT NULL,
  actor     TEXT,
  room_id   TEXT,
  payload   TEXT NOT NULL                      -- full envelope JSON
);

CREATE TABLE narration_cache (                -- created in M1, used in M3
  key        TEXT PRIMARY KEY,
  text       TEXT NOT NULL,
  model      TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_objects_room    ON objects(room_id);
CREATE INDEX idx_objects_owner   ON objects(owner_id);
CREATE INDEX idx_event_log_room  ON event_log(room_id, seq);
CREATE INDEX idx_players_room    ON players(room_id);
```

Rules:
- Every placed object has exactly one of `room_id`, `owner_id`, or
  `container_id`; enforced by the engine and checked in tests.
- `event_log` is append-only and trimmed to the last 10,000 rows on start.
- `world_meta.epoch` is a new UUID on every seed/reset. Clients use it to
  detect a world reset and drop cached maps.
- Schema changes only by bumping `PRAGMA user_version` with a migration step in
  `storage/db.py`. No ad-hoc `ALTER` by hand.

---

## 6. World content format

World content is versioned YAML, reviewed like code. One file per area,
30–40 rooms for M1.

```yaml
# world/areas/gatehouse.yaml
area: gatehouse
rooms:
  - id: gatehouse
    name: The Gatehouse
    description: |
      Cold air moves through the arch. A brass lantern hangs beside the door.
    exits:
      north: courtyard
      up:
        to: tower_stairs
        locked: true
        key: brass_key
        label: oak door
    objects:
      - id: brass_lantern
        name: brass lantern
        description: Tarnished, but the glass is clean.
        portable: true
      - id: oak_chest
        name: oak chest
        kind: container
        state: {open: false}
        contains: [tinderbox]
      - id: tinderbox
        name: tinderbox
        description: A dented tin box.
      - id: ledger
        name: mildewed ledger
        kind: readable
        readable_text: |
          The last entry is dated three winters ago.
    npcs:
      - id: keeper
        name: the keeper
        dialogue:
          greeting: "You are late. The gate does not wait."
          default: "The keeper watches the door."
          topics:
            key: "The brass key? Lost, like everything else."
            gate: "It opens for those who belong here."
        wander: false
    effects:                     # validated in M1, delivered in M2
      on_enter:
        - type: light.dim
          params: {color: "#3355ff", intensity: 0.3}
```

Authoring rules:
- IDs are global slugs (`[a-z0-9_]`), unique across the whole world. The
  validator rejects duplicates.
- Exits are declared once. The loader creates the reciprocal direction
  automatically (`n↔s`, `e↔w`, `u↔d`, `in↔out`) unless `one_way: true`.
  Declaring both directions by hand is an error so the two can never drift.
- Every exit target must exist. Every room must be reachable from `start_room`.
- A container may not contain itself, directly or indirectly.
- A lock's `key` must reference an existing portable object.
- `effects` are parsed and validated now, emitted to the internal bus and event
  log, and not sent to clients until M2 (`features.effects = true`).
- `python -m mud.content check world/` validates without touching the database
  and reports file, room id, and field.

`world/world.yaml`:

```yaml
name: Club MUD
start_room: gatehouse
rng_seed: 20261112          # change deliberately; it changes NPC wandering
```

---

## 7. Wire protocol v1

WebSocket, one JSON object per text frame, UTF-8, max frame 64 KiB. The
normative copy lives in `docs/PROTOCOL.md`; this section defines it.

### 7.1 Envelope

Server → client:

```json
{
  "v": 1,
  "type": "room.state",
  "event_id": "01JC8Z3K9Q7V2M4T6R8X0B1C2D",
  "seq": 42,
  "ts": "2026-11-12T18:04:11.213Z",
  "data": { "...": "...", "text": "The Gatehouse\nCold air moves..." }
}
```

Client → server:

```json
{
  "v": 1,
  "type": "input",
  "id": "c-17",
  "data": { "text": "take lamp" }
}
```

Rules:
- `v` is the protocol major version. M1 supports exactly `1`.
- `seq` is a per-connection counter starting at 1 after `hello`. It provides
  ordering for that client only. No cross-client ordering is promised.
- `event_id` is a ULID, unique per event, used later for narration correlation
  and MQTT deduplication.
- `id` is a client-chosen request id, echoed on direct replies (`error`,
  `look`, `auth.*`). Broadcast events carry no `id`.
- `data.text` is **presentation only** and may change wording at any time.
  Structured fields are the contract. A minimal client prints `data.text` and
  ignores everything else.
- Clients **must ignore unknown event types and unknown fields**. Additive
  changes are allowed within v1. Removing or renaming a field, or changing its
  meaning, requires v2.
- All arrays preserve a stable, documented order (exits by direction, objects
  by name, players by name) so clients can render without sorting rules.

### 7.2 Session lifecycle

1. Connect. Server sends `hello` immediately:

```json
{"v":1,"type":"hello","event_id":"...","seq":1,"ts":"...","data":{
  "server":"club-mud","protocol":[1],
  "world":{"name":"Club MUD","epoch":"f3c1..."},
  "auth_required":true,
  "motd":"Welcome. Type help."
}}
```

2. Client sends `auth` within 10 seconds or is closed with code `4001`:

```json
{"v":1,"type":"auth","id":"a1","data":{
  "mode":"login",              // "login" | "register"
  "name":"ada",
  "password":"correct horse battery staple"
}}
```

3. Success → `auth.ok`, then a full `room.state`:

```json
{"v":1,"type":"auth.ok","id":"a1","data":{
  "player":{"name":"ada","is_admin":false},
  "world":{"name":"Club MUD","epoch":"f3c1..."}
}}
```

4. Failure → `auth.error` with `code` in
   `bad_credentials | name_taken | unknown_player | invalid_name | weak_password`.
   Three failures close the connection (`4002`). A `register` with a taken name
   fails; a `login` with an unknown name fails. Registration and login are
   separate so a typo cannot silently create a character.

5. Play. Commands are `input` messages; the game responds with events.

6. Close. A clean client close or `quit` removes the player from the room and
   broadcasts `room.leave`. The character keeps position and inventory.
   Reconnecting resumes where they left off.

7. Server shutdown: broadcast `shutdown{reason, in_seconds}` (default 5), then
   close with `1001`. On start, send `hello` with the current epoch.

Close codes: `1000` normal, `1001` going away, `1002` protocol error,
`1008` policy violation, `4001` auth timeout, `4002` auth failures,
`4003` unsupported protocol version, `4004` idle timeout (90 s without input
and without server events), `4005` rate-limit abuse.

### 7.3 Client → server messages

| Type | Data | Notes |
|---|---|---|
| `auth` | `mode`, `name`, `password` | Only before authentication. |
| `input` | `text` | The whole command line, e.g. `"put lamp in chest"`. |
| `quit` | — | Graceful logout. |

Nothing else exists in v1. Clients do not send structured actions; parsing is
the server's job, so every client behaves identically.

### 7.4 Server → client events

Every event has `data.text` rendered for that recipient. Broadcasts render
differently per recipient ("You take the lamp." / "Ada takes the lamp."); the
structured fields are identical.

**Session**

| Type | Data |
|---|---|
| `hello` | `server`, `protocol`, `world{name,epoch}`, `auth_required`, `motd` |
| `auth.ok` | `player{name,is_admin}`, `world{name,epoch}` |
| `auth.error` | `code`, `message` |
| `error` | `code`, `message`, `command?`, `suggestions?[]` |
| `notice` | `text`, `level` (`info`\|`warning`) |
| `shutdown` | `reason`, `in_seconds` |

**Room and presence**

| Type | Data | Recipients |
|---|---|---|
| `room.state` | `room{...}`, `version` | Actor only |
| `room.enter` | `room{id,name}`, `actor{name}`, `direction?`, `reason` (`move`\|`connect`) | Others in room |
| `room.leave` | `room{id,name}`, `actor{name}`, `direction?`, `reason` (`move`\|`disconnect`) | Others in room |

`room.state.data.room`:

```json
{
  "id": "gatehouse",
  "name": "The Gatehouse",
  "description": "Cold air moves through the arch...",
  "exits": [
    {"direction":"north","to":"courtyard","locked":false},
    {"direction":"up","to":"tower_stairs","locked":true,"label":"oak door"}
  ],
  "objects": [
    {"id":"brass_lantern","name":"brass lantern","portable":true},
    {"id":"oak_chest","name":"oak chest","kind":"container","open":false}
  ],
  "npcs": [{"id":"keeper","name":"the keeper"}],
  "players": [{"name":"bob"}]
}
```

**Players and social**

| Type | Data | Recipients |
|---|---|---|
| `player.inventory` | `items[]{id,name}`, `capacity`, `used` | Actor only |
| `player.said` | `from`, `text`, `self` | Room incl. actor |
| `player.emoted` | `from`, `text`, `self` | Room incl. actor |
| `player.told` | `from`, `to`, `text`, `self` | Target and sender |
| `who.list` | `players[]{name,room_id}` | Actor only |

**Objects**

| Type | Data | Recipients |
|---|---|---|
| `object.taken` | `object{id,name}`, `by`, `self` | Room |
| `object.dropped` | `object{id,name}`, `by`, `self` | Room |
| `object.opened` | `object{id,name}`, `by`, `self` | Room |
| `object.closed` | `object{id,name}`, `by`, `self` | Room |
| `object.put` | `object{id,name}`, `container{id,name}`, `by`, `self` | Room |
| `object.got` | `object{id,name}`, `container{id,name}`, `by`, `self` | Room |
| `object.read` | `object{id,name}`, `text` | Actor only |
| `exit.locked` | `direction`, `by`, `self` | Room |
| `exit.unlocked` | `direction`, `by`, `self` | Room |

**NPCs**

| Type | Data | Recipients |
|---|---|---|
| `npc.say` | `npc{id,name}`, `text` | Room |
| `npc.enter` | `npc{id,name}`, `direction?` | Room |
| `npc.leave` | `npc{id,name}`, `direction?` | Room |

**Reserved for later milestones (never emitted in M1)**

| Type | Milestone | Purpose |
|---|---|---|
| `effect` | M2 | Semantic hardware effect; `data.effect`, `data.params`, `data.room_id` |
| `device.event` | M2 | Inbound hardware event, if enabled |
| `narration.append` | M3 | LLM prose appended to a room description |
| `room.generated` | M4 | A generated room was admitted |

### 7.5 Error codes

`unknown_command`, `bad_args`, `ambiguous_target`, `not_found`, `not_here`,
`not_portable`, `container_closed`, `no_exit`, `locked`, `already_open`,
`already_closed`, `not_authenticated`, `rate_limited`, `internal`,
plus the auth codes above. An error is non-fatal unless the code says
otherwise; clients should print `message` and continue.

### 7.6 Ordering and delivery

- Events are delivered in the order the engine produced them.
- A command that mutates produces at most one broadcast per recipient plus any
  private updates (inventory, state).
- There is no delivery guarantee across a disconnect. `room.state` on reconnect
  is the resynchronization mechanism. Clients must not build state they cannot
  rebuild from `room.state` + deltas.

### 7.7 Example session

```text
S: hello                     world=Club MUD epoch=f3c1
C: auth                      register ada
S: auth.ok                   + room.state (The Gatehouse)
C: input                     look at lantern
S: notice                    "Tarnished, but the glass is clean."       (id=c-1)
C: input                     take lantern
S: object.taken              "You take the brass lantern."             (self)
S: player.inventory          brass lantern (1/12)
   ... other player in room receives:
S: object.taken              "Ada takes the brass lantern."            (self=false)
C: input                     say hello
S: player.said               "You say: hello"
S: player.said               "Ada says: hello"   (to bob, self=false)
C: input                     unlock up
S: error                     code=locked, message="The oak door is locked."
```

---

## 8. Command set and rules

Parsing: case-insensitive verb, rest of line as arguments. Target resolution
accepts an object id, an exact name, or a unique case-insensitive prefix of a
visible name. Ambiguity returns `ambiguous_target` with candidates. `look at X`
and `examine X` are accepted; `at`/`the` are ignored as filler.

| Verb | Aliases | Rule |
|---|---|---|
| movement | `n s e w u d`, `north`… | Exit must exist and be unlocked. Moving emits `room.leave` to the old room, `room.state` to the actor, `room.enter` to the new room. |
| `go <dir>` | — | Same as movement. |
| `look [at] [target]` | `l` | No target: `room.state`. Target: private `notice` with the description. |
| `examine <target>` | `x` | Same as `look <target>`. |
| `inventory` | `i` | Private `player.inventory`. |
| `take <item>` | `get <item>` (room only) | Portable, in room, carry limit not exceeded. |
| `drop <item>` | — | Item in inventory; places it in the room. |
| `open <container>` | — | Container in room or inventory; sets `open=true`. |
| `close <container>` | — | Sets `open=false`. |
| `put <item> in <container>` | — | Item in inventory; container open; container in room or inventory. |
| `get <item> from <container>` | — | Container open and present; item inside. |
| `read <item>` | — | Readable only; private `object.read` with `readable_text`. |
| `unlock <direction>` | — | Exit locked; matching key in inventory. Consumes nothing. |
| `lock <direction>` | — | Exit unlocked; matching key in inventory. |
| `say <text>` | `"<text>` | Room broadcast. |
| `emote <text>` | `me <text>` | Room broadcast of a third-person action. |
| `tell <player> <text>` | — | Both parties get `player.told`; no room broadcast. |
| `talk <npc>` | — | NPC in room; returns `dialogue.greeting` (first time this session) then `dialogue.default`. |
| `ask <npc> about <topic>` | — | Case-insensitive substring match over `dialogue.topics`; falls back to `default`. |
| `who` | — | `who.list`. |
| `help [topic]` | `?` | Static help text from the server; topics: movement, objects, social, npcs, protocol. |
| `quit` | — | Graceful close. |

Carry limit: 12 items by default (`[game].carry_limit`).

NPC wandering: every `wander_every` seconds, a wandering NPC picks a random
open exit using the world RNG and moves, emitting `npc.leave`/`npc.enter` and
updating the DB. Non-wandering NPCs never move.

Containers: nested containment is allowed to a depth of 3 and validated
acyclic. Container contents are not listed in `room.state` unless open; a
closed container is opaque.

Locks: keys are ordinary portable objects. Unlocking is stateful (the exit stays
unlocked); re-locking requires the key in inventory. Losing the key does not
re-lock an exit.

Not in M1: combat, damage, death, XP, currency, shops, quests, respawns,
weather, time of day, player killing, item decay.

---

## 9. Persistence and lifecycle

- **Write-through.** Every mutation is a transaction that updates the relevant
  rows and appends the emitted event to `event_log`. In-memory state changes
  only after the commit succeeds.
- **Accounts survive resets.** A world reset re-seeds rooms, exits, objects, and
  NPCs; it deletes player-owned object rows, returns all players to
  `start_room`, and keeps accounts and password hashes. `--wipe-players` deletes
  accounts too. Resets are destructive and require confirmation.
- **Epoch.** Every reset writes a new `epoch`. Clients that cache maps compare
  it on `hello` and drop caches when it changes.
- **Migration.** `PRAGMA user_version` is authoritative. Startup refuses to run
  against an unknown newer schema and prints the required upgrade action.
- **Backup.** `python -m mud.admin backup` uses SQLite's online backup API and
  writes a timestamped copy. Recommended: nightly timer, keep 7.

---

## 10. Operations

### 10.1 Configuration

`mud.toml`, overridable by `MUD_*` environment variables:

```toml
[server]
bind = "127.0.0.1"        # set to the tailnet address in production
port = 8765
world_name = "Club MUD"
motd = "Welcome. Type help."

[storage]
db = "var/mud.db"

[game]
start_room = "gatehouse"
carry_limit = 12
tick_hz = 1
auth_timeout_s = 10
idle_timeout_s = 90
max_frame_bytes = 65536

[features]
effects = false           # M2
narration = false         # M3
generation = false        # M4
agents = false            # M5

[log]
level = "info"
format = "json"           # stderr; ship with journald or similar
```

### 10.2 Admin CLI (offline)

```
python -m mud.admin init-db
python -m mud.admin seed --reset [--wipe-players] [--yes]
python -m mud.admin create-player NAME [--admin]
python -m mud.admin set-password NAME
python -m mud.admin backup [--out DIR]
python -m mud.admin prune-generated        # M4
```

`seed --reset` requires the server stopped (startup acquires an exclusive lock
file; the CLI refuses if it is held). Account commands are safe to run live in
WAL mode; they are local-shell only. There is no in-band admin protocol in M1;
the admin surface stays out of the wire contract until there is a reason.

### 10.3 Network and security

- The server listens inside the club-owned WireGuard tailnet only. Bind to the
  tailnet address, or bind locally and forward from the tailnet interface. Do
  not port-forward it to the internet.
- Plain `ws://` is acceptable **because the tailnet already encrypts transport**.
  If the server is ever exposed beyond the tailnet, that decision requires TLS
  termination and a new review; it is not a config flag.
- Passwords: [REDACTED:password] (`n=2^14, r=8, p=1`, 16-byte salt, 32-byte hash), constant-
  time compare, never logged. No password is accepted under 10 characters.
- Per-connection rate limit: 10 commands/second, burst 20. Exceeding it returns
  `rate_limited`; sustained abuse closes with `4005`.
- Max frame 64 KiB; malformed JSON closes with `1002`. Unknown fields are
  ignored; unknown message types before auth close with `1002`.
- The server never trusts client-supplied ids for entities; targets are resolved
  against world state.

### 10.4 Deployment

Any always-on Linux host with Python 3.11+ and a tailnet address. Provide a
generic systemd unit in `docs/OPERATIONS.md` (`Restart=always`, `WorkingDirectory`,
`EnvironmentFile` for optional overrides), plus a plain `python -m mud` run
command for members testing locally. Process supervision beyond that is an ops
decision, not part of this spec.

---

## 11. Testing and acceptance

### 11.1 Test layers

1. **Content validation** — duplicates, dangling exits, unreachable rooms,
   cyclic containers, missing keys, bad effect shapes.
2. **Parser unit tests** — every verb, aliases, filler words, target
   resolution, ambiguity.
3. **Rules unit tests** — carry limit, locked exits, containers, permissions,
   NPC dialogue topics, wandering determinism with a fixed seed.
4. **Golden transcripts** — YAML scenarios drive the in-process server through
   the reference client and compare the event sequence (types, codes, ids;
   `text` compared loosely so wording can change):

```yaml
# tests/scenarios/take_lantern.yaml
- connect: {name: ada, mode: register}
- send: "look"
- expect: [hello, auth.ok, room.state]
- send: "take lantern"
- expect: [object.taken, player.inventory]
- send: "inventory"
- expect: [player.inventory]
```

5. **Protocol conformance** — `tools/refclient.py --script FILE` is usable by
   members against their own clients; the same script runs in CI against the
   reference client.
6. **Load smoke** — 20 in-process clients, 200 commands each, no errors,
   p95 under target.

### 11.2 M1 exit criteria

M1 is done when all of the following are true:

- 30–40 rooms, all reachable from `start_room`; at least 5 scripted NPCs; at
  least 10 interactive objects (containers, readables, keys, locked exits).
- Every verb in §8 covered by an automated test; every event type in §7.4
  emitted at least once in the golden scenarios.
- A member who has never seen the code writes a client using only
  `docs/PROTOCOL.md` + `docs/CLIENTS.md`, and it passes the smoke script.
- **Club playtest:** 3+ members connect with their own clients, play for 20
  minutes without a server restart, see each other's movement and chat, and the
  server logs no unhandled exceptions and no protocol errors. Command p95
  ≤ 100 ms.
- `seed --reset --yes` reproduces the same world from the YAML files on a clean
  database, and the epoch changes.
- Backup and restore are exercised once.

### 11.3 Milestone order (no dates)

| Step | Deliverable | Exit |
|---|---|---|
| M1.0 | Skeleton: config, DB, WS, `hello`/`auth`, `input`/`error`, refclient | two clients log in and get `help` |
| M1.1 | Movement, room state, presence, chat, `who` | two clients walk and talk |
| M1.2 | Objects, inventory, containers, locks, readables | golden scenario passes |
| M1.3 | NPCs, dialogue, wandering tick | NPC talks and moves deterministically |
| M1.4 | 30–40 room world, validator, reachability | `content check` clean |
| M1.5 | Rate limits, logging, conformance suite, load smoke, docs | §11.2 playtest |

Content authoring (M1.4) is the long pole and can start in parallel with M1.1.

---

## 12. M2 — IoT bridge

**Goal:** a physical device reacts to a game event, and optionally a button
changes the game.

Design:
- `src/mud/bridge/` is an optional in-process module subscribing to the bus.
  Enabled by `[features].effects = true` and `[bridge].mqtt_url`. The core
  server must run with the bridge absent.
- **Outbound:** every bus event is published to
  `mud/v1/<world>/room/<room_id>/event`, payload identical to the WS envelope.
  Retained `.../state` carries the latest room snapshot so a device that
  connects late is immediately correct. QoS 0.
- **Effects:** room/object/NPC content can declare `effects:` (already
  validated in M1). On trigger, the engine emits `effect` with `effect` name and
  `params`. Example vocabulary: `light.set`, `light.pulse`, `sound.play`,
  `fog.burst`, `relay.set`, `display.text`. The server never knows what a device
  is; devices map effects to hardware.
- **Inbound:** `mud/v1/<world>/in/<device_id>/event` accepts a narrow envelope
  (`device.button`, `device.presence`, `device.sensor`). The bridge validates
  the device against config, maps it to a `device.event`, and the engine applies
  content rules (`on_device`) — or ignores it in M2 if no rule exists.
- **Security:** Mosquitto (or equivalent) listens on the tailnet only. Per-
  device username/password or client certificate; ACLs allow a device to read
  only `mud/v1/<world>/room/#` and write only its own `in/<device_id>/event`.
- **Reference device:** `tools/refdevice.py` (host Python, prints effects, drives
  GPIO if configured) is mandatory and testable in CI with a fake broker. An
  ESP32 sketch is an optional example, not a dependency.
- **Acceptance:** a device on the tailnet receives a `light.set` within 1 s of a
  player entering a room with that effect; unplugging the bridge does not affect
  the game; unplugging a device does not affect the game; a button press reaches
  the engine and is logged.

## 13. M3 — LLM narration

**Goal:** richer descriptions without letting the model touch state.

- `Narrator` interface: `narrate(context) -> str | None`, with a hard timeout
  (default 2.5 s).
- Trigger: `look` and room entry. The static `room.state` is always sent
  immediately. If narration returns in time, the actor and room get
  `narration.append` with `data.text`, `model`, `latency_ms`, and a correlation
  `look_id`. Late responses are dropped.
- Prompt context is built from world state only: room name/description, visible
  objects and NPCs, exits, recent `event_log` entries for the room. Player chat
  is **not** included (prompt-injection surface).
- Output is capped (600 chars), stripped of control characters, and rendered
  plain. No Markdown.
- Cache: `narration_cache` keyed by
  `sha256(model + room_id + room.version + sorted visible names)`, TTL 10 min.
  A room's `version` increments on any mutation in it.
- Backends: `ollama` (default), `openai`, `none`. A shared interface, selected
  by config; cloud keys come from the environment, never the repo. Per-hour
  token budget and a circuit breaker (5 failures → 60 s off) are required.
- Acceptance: with the LLM off, every M1 test passes unchanged; with it on and
  a 20-minute playtest, no command is blocked by narration, the game stays
  playable when the backend is killed mid-session, and no generated text
  changes world state.

## 14. M4 — Procedural generation

**Goal:** unexplored exits produce new rooms on demand, safely.

- Content declares an exit with `generate: {theme: "dungeon"}` instead of `to:`.
- On entering a room, the engine prefetches proposals for its `generate` exits
  in the background (`[features].generation`). Moving through a prefetched exit
  is instant; a cold exit generates with a 5 s cap, then falls back to a static
  blocked passage with a return exit.
- Proposals must validate against the same content models as hand-authored
  rooms: valid IDs, a reciprocal exit to the origin, no dangling references,
  description length cap, max 6 exits, at most 2 objects. Failure → one retry →
  fallback.
- Room id is derived from the seed (`gen-<sha8>`), and the seed is stored;
  regenerating the same seed must produce the same room. Generated rooms are
  flagged `generated=1` and can be pruned; pruning never strands a player
  (move them to `start_room` first).
- Budget: default 50 generated rooms/day and a token cap; both configured.
  Theme strings come only from content authors, never from players.
- Acceptance: the validator rejects malformed proposals in tests; a 30-minute
  playtest never blocks more than 5 s on a cold exit; `prune-generated` leaves
  the graph reachable; same seed reproduces the same room.

## 15. M5 — Living NPC agents

**Goal:** NPCs that remember and pursue goals, without becoming the engine.

- `AgentPolicy` interface: given an observation (room events, nearby players,
  recent memory) and a memory store, return a list of intents: `say`, `emote`,
  `move(direction)`.
- The engine validates every intent (room adjacency, rate limit, budget) and is
  the only writer. Agents never touch SQLite.
- Memory is pluggable (`MemoryStore`); a vector store (ChromaDB or similar) is
  one implementation, not a requirement. Per-NPC token/minute budget and a
  global kill switch (`[features].agents = false`).
- Acceptance: an NPC references an event from earlier in the session; 100% of
  illegal intents are rejected in tests; disabling the feature leaves M1–M4
  tests untouched; the budget cap is enforced under load.

---

## 16. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| Club tailnet not provisioned, or no admin | Members cannot reach the server; onboarding stalls | Decide admin and DNS name before M1.1; locally hosted server until then |
| Server host ownership unclear | Uptime, backups, and resets become nobody's job | Name an owner and a backup location before the M1 playtest |
| Content authoring is the long pole | 30–40 rooms delay the playtest | Start M1.4 in parallel with M1.1; one file per area; validator in CI |
| Protocol drift | Members' clients break | Golden tests, `PROTOCOL.md` canonical, additive-only v1, changelog |
| Password/account recovery | Locked-out members | Offline `set-password`; document it in `CLIENTS.md` |
| Scope creep (combat, LLM, hardware) | M1 never lands | M1 non-goals are explicit; later layers are feature-flagged |
| Member client skill varies | Playtest has too few clients | Reference client + one evening of docs; offer a minimal browser example as a club exercise, not a deliverable |

Open questions to settle with the club (none block server work):

1. Who administers the club tailnet, and what is the server's DNS name?
2. Which machine hosts the central server, and who is responsible for uptime?
3. Where does the code live (club git host vs elsewhere), and under what license?
4. What is the world's name and theme for the 30–40 room dungeon?
5. Do members author content as well as clients? (Assumed yes; the format is
   designed for it.)
6. For M2: which MQTT broker, and what device inventory does the club have?
7. For M3: which LLM backend budget does the club approve?

---

## 17. Decision log

| # | Decision | Why |
|---|---|---|
| 1 | Server by one owner, clients by members | Makes the protocol the contract and keeps a single authority for state |
| 2 | One central server, shared world | Multiplayer presence is a defining MUD feature; shared state is the point |
| 3 | Text MUD first, no hardware/LLM | Every layer above the engine is optional; prove the core alone |
| 4 | WebSocket + JSON, text in, typed events out | Lowers client effort, keeps MUD feel, and gives hardware a structured event stream |
| 5 | Python 3 + asyncio | Club-familiar, best LLM/IoT ecosystem, adequate at club scale |
| 6 | Everything but combat | Objects and NPCs exercise state without combat tuning |
| 7 | Shared world, room presence and chat | Cheap with asyncio, and defines the event model clients need |
| 8 | YAML → SQLite seed | Non-coders can contribute; content is reviewable and reproducible |
| 9 | Name + password, persistent characters | Trust boundary is the tailnet; passwords prevent impersonation and loss of work |
| 10 | Persistent world + offline reset | Exploration should accumulate; resets stay deliberate and auditable |
| 11 | M1 exit = 3+ member clients, 20 minutes | Proves protocol, presence, stability, and onboarding at once |
| 12 | IoT bridge before LLM | The club's differentiator, and the reason the event bus exists |
| 13 | Hardware-agnostic server | Members' devices and OS choices must not constrain the spec |
| 14 | Static text always sent before narration | No command ever waits on a model; LLM failure is invisible |
| 15 | LLM/agents never write state | Keeps the engine authoritative and the game testable |

---

## 18. Immediate next steps

1. Confirm the open questions that block onboarding (tailnet, host, repo).
2. Scaffold the M1.0 skeleton: `pyproject.toml`, config, schema, WS handshake,
   `auth`, `input`, `error`, `tools/refclient.py`.
3. Write `docs/PROTOCOL.md` from §7 as the standalone member-facing contract.
4. Start the 30–40 room content in parallel; run `content check` in CI from the
   first file.
