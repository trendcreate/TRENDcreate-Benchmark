/**
 * TC Bench Forum Worker (Cloudflare Workers + KV)
 *
 * GitHub Discussions に代わる軽量な動的フォーラムAPI。
 * 共有ページ(GitHub Pages)からfetchで読み書きします。
 *
 * エンドポイント:
 *   GET  /api/threads                     スレッド一覧
 *   GET  /api/posts?thread=<id>           スレッドの投稿一覧(新しい順)
 *   POST /api/posts  {thread, name, text} 投稿 (10秒に1回/IP のレート制限)
 *
 * 必要なバインディング:
 *   KV Namespace: FORUM  (wrangler.toml 参照)
 */

const THREADS = {
  general:  { id: "general",  title: "📊 スペック比較・雑談" },
  joke:     { id: "joke",     title: "🃏 ジョークスペック申請所" },
  support:  { id: "support",  title: "🛠 質問・トラブル" },
};

const MAX_POSTS_PER_THREAD = 300;   // これを超えたら古い投稿から削除
const MAX_NAME = 30;
const MAX_TEXT = 1000;
const RATE_LIMIT_SECONDS = 10;

// 共有ページのオリジンのみ許可 (開発用に localhost も)
const ALLOWED_ORIGINS = [
  "https://trendcreate.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
];

function corsHeaders(origin) {
  const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json; charset=utf-8",
  };
}

function json(data, status, origin) {
  return new Response(JSON.stringify(data), { status, headers: corsHeaders(origin) });
}

function sanitize(value, max) {
  // 制御文字(改行タブ以外)を除去して長さ制限
  return String(value || "")
    .replace(/[\u0000-\u0008\u000B-\u001F\u007F]/g, "")
    .trim()
    .slice(0, max);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    // ---- ベンチ広場 (WebSocket / Durable Object) -----------------------------
    if (url.pathname === "/api/plaza/ws") {
      const id = env.PLAZA.idFromName("main");
      return env.PLAZA.get(id).fetch(request);
    }

    // ---- GET /api/threads --------------------------------------------------
    if (request.method === "GET" && url.pathname === "/api/threads") {
      const list = await Promise.all(
        Object.values(THREADS).map(async (t) => {
          const raw = await env.FORUM.get("posts:" + t.id);
          const posts = raw ? JSON.parse(raw) : [];
          return { ...t, count: posts.length, last: posts.length ? posts[0].ts : null };
        })
      );
      return json({ threads: list }, 200, origin);
    }

    // ---- GET /api/posts?thread=x -------------------------------------------
    if (request.method === "GET" && url.pathname === "/api/posts") {
      const thread = url.searchParams.get("thread") || "general";
      if (!THREADS[thread]) return json({ error: "unknown thread" }, 400, origin);
      const raw = await env.FORUM.get("posts:" + thread);
      return json({ thread, posts: raw ? JSON.parse(raw) : [] }, 200, origin);
    }

    // ---- POST /api/posts ----------------------------------------------------
    if (request.method === "POST" && url.pathname === "/api/posts") {
      // レート制限 (IPごとに10秒)
      const ip = request.headers.get("CF-Connecting-IP") || "unknown";
      const rlKey = "rl:" + ip;
      if (await env.FORUM.get(rlKey)) {
        return json({ error: "rate_limited", retry_after: RATE_LIMIT_SECONDS }, 429, origin);
      }

      let body;
      try {
        body = await request.json();
      } catch (e) {
        return json({ error: "invalid json" }, 400, origin);
      }

      const thread = sanitize(body.thread, 20) || "general";
      if (!THREADS[thread]) return json({ error: "unknown thread" }, 400, origin);
      const name = sanitize(body.name, MAX_NAME) || "名無しさん";
      const text = sanitize(body.text, MAX_TEXT);
      if (!text) return json({ error: "empty text" }, 400, origin);

      const key = "posts:" + thread;
      const raw = await env.FORUM.get(key);
      const posts = raw ? JSON.parse(raw) : [];
      const post = {
        id: crypto.randomUUID(),
        name: name,
        text: text,
        ts: new Date().toISOString(),
      };
      posts.unshift(post);                       // 新しい順
      if (posts.length > MAX_POSTS_PER_THREAD) posts.length = MAX_POSTS_PER_THREAD;

      await env.FORUM.put(key, JSON.stringify(posts));
      await env.FORUM.put(rlKey, "1", { expirationTtl: 60 }); // KVのTTL下限は60秒

      return json({ ok: true, post: post }, 201, origin);
    }

    return json({ error: "not found" }, 404, origin);
  },
};

/**
 * ベンチ広場: 2D空間の位置・チャット・共有動画をWebSocketで同期する部屋。
 * 公開の1部屋のみ (DM・非公開ルームは作らないこと → forum-worker/README.md 参照)
 */
const PLAZA_MAX_SESSIONS = 40;
const PLAZA_WORLD = { w: 960, h: 540 };
const PLAZA_HEARTBEAT_MS = 15000;   // クライアントが ping を送る間隔の目安
const PLAZA_STALE_MS = 40000;       // これより ping が来なければ切断とみなす
const PLAZA_SWEEP_MS = 15000;       // 掃除アラームの間隔

export class PlazaRoom {
  constructor(state, env) {
    this.state = state;
    this.sessions = new Map();   // id -> {ws, name, color, x, y, lastSeen}
    this.video = null;           // {vid, by, ts}
    this.playback = null;        // {state: "playing"|"paused", pos: 秒, wallTs: ms}
  }

  broadcast(obj, exceptId) {
    const msg = JSON.stringify(obj);
    for (const [id, s] of this.sessions) {
      if (id === exceptId) continue;
      try { s.ws.send(msg); } catch (e) { /* closed */ }
    }
  }

  playerList() {
    const out = [];
    for (const [id, s] of this.sessions) {
      out.push({ id: id, name: s.name, color: s.color, x: s.x, y: s.y });
    }
    return out;
  }

  async fetch(request) {
    if (request.headers.get("Upgrade") !== "websocket") {
      return new Response("expected websocket", { status: 426 });
    }
    if (this.sessions.size >= PLAZA_MAX_SESSIONS) {
      return new Response("room full", { status: 503 });
    }
    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    this.handleSession(server);
    return new Response(null, { status: 101, webSocket: client });
  }

  handleSession(ws) {
    ws.accept();
    const id = crypto.randomUUID().slice(0, 8);
    const sess = {
      ws: ws,
      name: "名無しさん",
      color: "#32b478",
      x: 100 + Math.random() * (PLAZA_WORLD.w - 200),
      y: 310 + Math.random() * (PLAZA_WORLD.h - 360),   // ステージ(上部)の下側にスポーン
      lastChat: 0,
      lastSeen: Date.now(),
    };
    this.sessions.set(id, sess);
    this.ensureSweepAlarm();

    ws.send(JSON.stringify({
      t: "init", id: id, players: this.playerList(),
      video: this.video, playback: this.playback, world: PLAZA_WORLD,
    }));

    ws.addEventListener("message", (e) => {
      sess.lastSeen = Date.now();
      let m;
      try { m = JSON.parse(e.data); } catch (err) { return; }
      if (m.t === "join") {
        sess.name = sanitize(m.name, 20) || "名無しさん";
        sess.color = /^#[0-9a-fA-F]{6}$/.test(m.color || "") ? m.color : "#32b478";
        this.broadcast({ t: "join", p: { id: id, name: sess.name, color: sess.color, x: sess.x, y: sess.y } }, id);
      } else if (m.t === "move") {
        const x = Number(m.x), y = Number(m.y);
        if (!isFinite(x) || !isFinite(y)) return;
        sess.x = Math.max(0, Math.min(PLAZA_WORLD.w, x));
        sess.y = Math.max(0, Math.min(PLAZA_WORLD.h, y));
        this.broadcast({ t: "move", id: id, x: sess.x, y: sess.y }, id);
      } else if (m.t === "chat") {
        const now = Date.now();
        if (now - sess.lastChat < 1000) return;          // 1秒に1回まで
        sess.lastChat = now;
        const text = sanitize(m.text, 200);
        if (!text) return;
        this.broadcast({ t: "chat", id: id, name: sess.name, text: text }, id);   // 送信者本人には返さない(二重表示防止)
      } else if (m.t === "ping") {
        // ハートビート。lastSeen 更新のみで応答不要。
      } else if (m.t === "video") {
        const vid = String(m.vid || "").trim();
        if (vid === "") {                                   // 空文字で消灯
          this.video = null;
          this.playback = null;
          this.broadcast({ t: "video", vid: null, by: sess.name });
          return;
        }
        if (!/^[A-Za-z0-9_-]{6,15}$/.test(vid)) return;
        this.video = { vid: vid, by: sess.name, ts: Date.now() };
        // 新しい動画は自動再生・先頭から。以後クライアントの実再生状態で上書きされる。
        this.playback = { state: "playing", pos: 0, wallTs: Date.now() };
        this.broadcast({ t: "video", vid: vid, by: sess.name });
      } else if (m.t === "vstate") {
        // 再生/一時停止/シークの同期。pos=動画内の秒数、state="playing"|"paused"
        if (!this.video) return;
        const state = m.state === "paused" ? "paused" : "playing";
        const pos = Number(m.pos);
        if (!isFinite(pos) || pos < 0) return;
        this.playback = { state: state, pos: pos, wallTs: Date.now() };
        this.broadcast({ t: "vstate", state: state, pos: pos, by: sess.name }, id);
      }
    });

    const close = () => {
      if (!this.sessions.has(id)) return;   // 既に掃除済みなら二重leaveを防ぐ
      this.sessions.delete(id);
      this.broadcast({ t: "leave", id: id });
    };
    ws.addEventListener("close", close);
    ws.addEventListener("error", close);
  }

  // 定期的に生存確認(ping)が途絶えたセッションを掃除する。
  // WebSocketの close/error イベントは、ブラウザバック・通信断・端末スリープ・
  // 強制終了などで発火しないことがあるため、その保険として動かす。
  ensureSweepAlarm() {
    if (this._sweepScheduled) return;
    this._sweepScheduled = true;
    this.state.storage.setAlarm(Date.now() + PLAZA_SWEEP_MS).catch(() => {});
  }

  async alarm() {
    this._sweepScheduled = false;
    const now = Date.now();
    for (const [id, sess] of this.sessions) {
      if (now - sess.lastSeen > PLAZA_STALE_MS) {
        this.sessions.delete(id);
        try { sess.ws.close(1001, "stale"); } catch (e) { /* already closed */ }
        this.broadcast({ t: "leave", id: id });
      }
    }
    if (this.sessions.size > 0) this.ensureSweepAlarm();
  }
}
