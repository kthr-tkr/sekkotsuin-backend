# frontend

Nuxt 4 (SPA) + Vuetify 4。セットアップはリポジトリ直下の README を参照してください。

- `app/types/api.d.ts` は自動生成ファイルです（`pnpm gen:api`）。手で編集しないでください。
- API の呼び出しは `useApi()`（openapi-fetch）を使うと、パス・パラメータ・レスポンスに型が付きます。
- ログイン不要のページは `definePageMeta({ public: true })` を指定します（例: `pages/q/[token].vue`）。
