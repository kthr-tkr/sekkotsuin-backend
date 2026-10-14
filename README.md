# 接骨院システム

接骨院向けの予約・患者・問診管理システムです。
旧 Django 版（`legacy/`）を、**FastAPI + Nuxt/Vuetify** で作り直しています。

| ディレクトリ | 内容 |
|---|---|
| `backend/` | FastAPI / SQLAlchemy 2.0 (async) / Alembic / PostgreSQL |
| `frontend/` | Nuxt 4 (SPA) / Vuetify 4 / FullCalendar / openapi-fetch |
| `legacy/` | 旧 Django 版（参照用。新システムへの移植が終わったら削除予定） |

## MVP の機能

- **スタッフログイン**（JWT、役割: 管理者・受付・施術者）
- **患者管理**（診察券番号の自動採番、検索、編集、予約履歴、問診履歴）
- **予約カレンダー**（週・日・月表示、ドラッグで登録・移動、担当者の重複チェック、空き枠API）
- **Web問診**（スタッフが URL を発行 → 患者がスマホで回答 → 「問診待ち」の予約を自動で「予約確定」に）
- **院の設定**（営業時間・休憩・休診曜日・予約単位、施術メニュー、スタッフ追加）※管理者のみ

すべてのデータは院（clinic）単位で分離され、他院のデータにはアクセスできません。

## ローカル開発

### 1. DB と API

```bash
docker compose up -d db          # PostgreSQL（開発用 sekkotsuin / テスト用 sekkotsuin_test）

cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run python -m app.cli seed-demo   # デモデータ（admin / password123）
uv run uvicorn app.main:app --reload
```

API ドキュメント: http://localhost:8000/docs

### 2. フロントエンド

```bash
cd frontend
pnpm install
pnpm dev
```

http://localhost:3000 を開き、`admin` / `password123` でログインします。

### API の型を更新する

backend のスキーマを変えたら、OpenAPI から TypeScript の型を作り直します。

```bash
cd frontend
pnpm gen:api    # backend から openapi.json を出力 → app/types/api.d.ts を生成
```

## テスト・チェック

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run pytest            # PostgreSQL の sekkotsuin_test を使用
uv run alembic check     # モデルとマイグレーションの差分がないか

cd ../frontend
pnpm typecheck
pnpm build
```

## 院の作成（本番）

```bash
cd backend
uv run python -m app.cli create-clinic --name "さくら接骨院" --slug sakura --admin admin --password '...'
```

本番環境では `ENVIRONMENT=production` と 32 文字以上の `SECRET_KEY` を必ず設定してください（未設定の場合は起動時にエラーになります）。

## 今後の予定（第2弾以降）

legacy にある以下の機能を順次移植します。

- カルテ（clinical_notes）・施術記録（treatment_sessions）
- 施術計画（treatment_plans）・姿勢評価（posture_assessments）
- AI 機能（問診の音声文字起こし・要約、姿勢分析）とジョブキュー
- 売上・KPI ダッシュボード、シフト・休暇管理
- 患者向けポータル（Web 予約・マイページ）
