import vuetify, { transformAssetUrls } from 'vite-plugin-vuetify'

export default defineNuxtConfig({
  compatibilityDate: '2026-10-01',
  // スタッフ向け業務アプリのため SPA で配信（nuxt generate で静的ファイル化可能）
  ssr: false,
  devtools: { enabled: true },
  app: {
    head: {
      htmlAttrs: { lang: 'ja' },
      title: '接骨院システム',
      meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
    },
  },
  css: ['@mdi/font/css/materialdesignicons.css'],
  build: { transpile: ['vuetify'] },
  vite: {
    plugins: [vuetify({ autoImport: true })],
    vue: { template: { transformAssetUrls } },
  },
  runtimeConfig: {
    public: {
      // NUXT_PUBLIC_API_BASE で上書き
      apiBase: 'http://localhost:8000',
    },
  },
  typescript: { strict: true },
})
