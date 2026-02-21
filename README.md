# 渋谷ストリーム密室事件（AI GM 即興推理ゲーム）

要件定義書に基づくMVP実装です。`backend`(FastAPI) と `frontend`(Vite + React) で構成されています。

## Docker Compose（推奨）
コード変更が即時反映される開発モードです（フロント/バックともホットリロード有効）。

```bash
docker compose up --build
```

- フロントエンド: `http://localhost:5173`
- バックエンド: `http://localhost:8000`
- 停止: `Ctrl + C`
- バックグラウンド起動: `docker compose up --build -d`
- 完全停止: `docker compose down`

## 実装済み機能
- 事件生成（構造化JSON + Pydantic検証、失敗時1回リトライ）
- 質問応答（事件整合ベース、矛盾チェック付き）
- 質問回数制限（デフォルト12）
- 推理提出と採点（100点満点、S/A/B/C）
- 嘘つきNPCを含む事件生成
- 推理の弱点トップ3
- 言語モード切替（`ja` / `en`）
- 共通エラー契約（`error_code`, `message`, `retryable`, `detail`）

## ディレクトリ
- `backend/app`: API本体
- `backend/tests`: APIテスト
- `frontend/src`: UI実装

## バックエンド起動
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## フロントエンド起動
```bash
cd frontend
npm install
npm run dev
```

`VITE_API_BASE_URL` を設定しない場合、`http://localhost:8000` を参照します。

## 環境変数
- `LLM_PROVIDER`: `fake` or `gemini`（デフォルト: `fake`）
- `GEMINI_API_KEY`: Gemini利用時に必須
- `GEMINI_MODEL`: デフォルト `gemini-3-flash-preview`
- `GEMINI_API_VERSION`: デフォルト `v1beta`
- `GEMINI_THINKING_LEVEL`: `minimal|low|medium|high`（デフォルト `minimal`）
- `GEMINI_RETRY_DELAY_SEC`: リトライ初期待機秒（デフォルト `0.8`）
- `GEMINI_RETRY_MAX_DELAY_SEC`: リトライ最大待機秒（デフォルト `20`）
- `GEMINI_MAX_ATTEMPTS`: 1リクエストあたりの最大試行回数（デフォルト `5`）
- `GEMINI_FALLBACK_TO_FAKE`: デフォルト `false`（`true`のときのみGemini障害時に`fake`へフォールバック）
- `DATABASE_URL`: デフォルト `sqlite:///./mystery_game.db`
- `MAX_QUESTIONS`: デフォルト `12`
- `VITE_API_BASE_URL`: デフォルト `http://localhost:8000`

## Gemini利用
`LLM_PROVIDER=gemini` を指定すると、事件生成・応答・矛盾チェック・採点でGemini APIを使用します。
バックエンドは公式 `google-genai` SDK で Gemini API を呼び出し、`429/5xx` 系エラー時は指数バックオフで再試行します。
低遅延で返す場合は `GEMINI_THINKING_LEVEL=minimal` を使用します（Gemini 3 の推奨設定）。
`GEMINI_FALLBACK_TO_FAKE=false`（デフォルト）ではGeminiが最終的に失敗した場合 `502 GEMINI_UNAVAILABLE` を返します。

## APIテスト
```bash
cd backend
pytest -q
```

## 補足
- 要件上のPostgreSQLにも対応できるよう、`DATABASE_URL`差し替えで動作します。
- デモ運用安定性のため、オフラインでも動く`fake`プロバイダを同梱しています。
