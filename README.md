# 接骨院システム

接骨院向けの予約・患者・問診管理システムです。
旧 Django 版（`legacy/`）を、**FastAPI + Nuxt/Vuetify** で作り直しています。

| ディレクトリ | 内容 |
|---|---|
| `backend/` | FastAPI / SQLAlchemy 2.0 (async) / Alembic / PostgreSQL |
| `frontend/` | Nuxt 4 (SPA) / Vuetify 4 / FullCalendar / openapi-fetch |
| `legacy/` | 旧 Django 版（参照用。新システムへの移植が終わったら削除予定） |

## 機能

- **スタッフログイン**（JWT、役割: 管理者・受付・施術者）
- **患者管理**（診察券番号の自動採番、検索、編集、予約履歴、問診履歴）
- **予約カレンダー**（週・日・月表示、ドラッグで登録・移動、担当者の重複チェック、空き枠API）
- **Web問診**（スタッフが URL を発行 → 患者がスマホで回答 → 「問診待ち」の予約を自動で「予約確定」に）
- **院の設定**（営業時間・休憩・休診曜日・予約単位、施術メニュー、スタッフ追加、AI の ON/OFF と月の上限）※管理者のみ
- **カルテ**（SOAP・施術内容・施術前後の PS。予約から作ると問診を引き継ぐ。確定で予約を完了に。修正履歴を保存）
- **施術計画**（通院の目安・生活指導・改善の目安。経過は計画期間中のカルテから PS の推移グラフで表示。患者さんのサインによる同意を、署名時の計画内容と一緒に保存）
- **姿勢評価**（正面・側面・背面の写真、グリッド線、部位別の所見、Before/After 比較。写真は EXIF を除去して保存）
- **AI**（録音 → 文字起こし → SOAP 下書き → 確認してカルテに反映、姿勢写真の AI 分析、利用量とコストの記録）
- **売上**（カルテから会計を登録。メニュー料金を初期値に。未会計・支払い済み・取消）
- **シフト・休暇**（月間のシフト表、休暇の申請と承認。予約の空き枠に反映）
- **KPI**（売上・来院数・客単価・新規患者・キャンセル率・日別売上・予約経路・担当者別）※管理者のみ

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

### 2. AI ワーカー（録音の文字起こし・要約、姿勢分析）

```bash
cd backend
uv run python -m app.worker
```

`AI_PROVIDER=fake`（既定）では固定の結果を返すので、API キーなしで流れを確認できます。
実際に使う場合は `AI_PROVIDER=openai` と `OPENAI_API_KEY` を設定してください。
AI 機能は録音した音声と姿勢の写真を外部サービス（OpenAI）に送信します。患者さんへの説明と同意のうえで利用してください。

### 3. フロントエンド

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

## アップロードファイル

署名画像・姿勢写真・録音は `MEDIA_DIR`（既定 `backend/media/`）に保存し、有効期限付きの署名付き URL で配信します。
本番で S3 などに置く場合は `app/services/storage.py` の実装を差し替えてください。

## 今後の予定

- 患者向けポータル（Web 予約・マイページ）
- legacy/ の削除（移植の確認が終わったら）
