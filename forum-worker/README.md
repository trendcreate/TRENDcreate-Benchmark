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

## 法的な整理（電気通信事業法・総務省届出について）

本フォーラムは以下を満たす範囲で運用し、**総務省への届出（電気通信事業の届出）が不要な範囲**に収めます。

- **公開掲示板のみ**: すべての投稿は誰でも閲覧できる 1対不特定多数の公開投稿。特定の利用者間の通信を取り次ぐものではないため「他人の通信の媒介」に該当しない（総務省の参入マニュアル追補版の整理）
- **非営利・無料**: 収益目的の提供ではなく、事業としての電気通信役務提供に当たらない
- **投稿の管理**: 誹謗中傷・個人情報・法令違反の投稿は運営が削除する（削除依頼窓口: GitHub Issues）。IP はレート制限のため短時間のみ KV に保持し、恒久保存しない

### ⚠️ 今後の機能追加で「やってはいけない」こと

以下を追加すると「他人の通信の媒介」に該当し**届出が必要になり得る**ため、実装しないこと。

- DM・非公開メッセージ・1対1チャットなど、特定ユーザー間のクローズドなメッセージ機能
- 非公開（メンバー限定）スレッドでのメッセージ交換
- メール転送・通知代行など通信の取次ぎ

有料化・広告収益化する場合や上記機能が必要になった場合は、総務省の
「電気通信事業参入マニュアル（追補版）」を確認のうえ、必要に応じて届出を行ってください。
