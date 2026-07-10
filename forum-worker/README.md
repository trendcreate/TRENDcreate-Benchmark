# TC Bench Forum Worker

GitHub Discussions の代わりに、**Cloudflare Workers + KV** で動く軽量フォーラムAPIです。
共有ページ（GitHub Pages）から fetch で読み書きします。

## デプロイ手順（Cloudflareアカウントが必要）

```bash
cd forum-worker
npm install -g wrangler          # 未導入なら
wrangler login                   # ブラウザでCloudflareにログイン

# KV Namespace を作成して id を wrangler.toml に貼る
wrangler kv namespace create FORUM
#  → 出力された id を wrangler.toml の REPLACE_WITH_YOUR_KV_NAMESPACE_ID に設定

wrangler deploy
#  → https://tcbench-forum.<あなたのサブドメイン>.workers.dev が発行される
```

## API

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/threads` | スレッド一覧（件数・最終投稿時刻付き） |
| GET | `/api/posts?thread=general` | 投稿一覧（新しい順、最大300件保持） |
| POST | `/api/posts` | 投稿。body: `{"thread":"general","name":"...","text":"..."}` |

- スレッドは `general`（比較・雑談）/ `joke`（ジョークスペック）/ `support`（質問）
- レート制限: 1 IP につき約10秒に1回（KV TTLの都合で実際は60秒キー・判定は投稿時刻）
- 名前は省略時「名無しさん」、本文は最大1000文字、制御文字は除去

## 共有ページへの組み込み

デプロイで発行された Worker URL を `docs/index.html` の `FORUM_API` 定数に設定すると、
ページ内にフォーラム（スレッド切替・投稿フォーム・自動更新）が表示されます。
未設定（空文字）の間は従来どおり GitHub Discussions へのリンクを表示します。

## 注意

- CORS は `https://trendcreate.github.io` と localhost のみ許可（`worker.js` の `ALLOWED_ORIGINS`）
- 認証なしの匿名投稿です。荒らし対策が必要になったら Turnstile（Cloudflareの無料CAPTCHA）の追加を検討してください
- KV は結果整合なので、投稿直後に他ユーザーへ反映されるまで数秒かかることがあります
