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
