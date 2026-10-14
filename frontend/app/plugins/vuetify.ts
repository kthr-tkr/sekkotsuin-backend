import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import { ja } from 'vuetify/locale'

export default defineNuxtPlugin((nuxtApp) => {
  const vuetify = createVuetify({
    locale: { locale: 'ja', messages: { ja } },
    theme: {
      defaultTheme: 'clinic',
      themes: {
        clinic: {
          dark: false,
          colors: {
            primary: '#1D4ED8',
            secondary: '#0F172A',
            accent: '#16A34A',
            background: '#F5F7FB',
          },
        },
      },
    },
    defaults: {
      VTextField: { variant: 'outlined', density: 'comfortable' },
      VSelect: { variant: 'outlined', density: 'comfortable' },
      VAutocomplete: { variant: 'outlined', density: 'comfortable' },
      VTextarea: { variant: 'outlined', density: 'comfortable' },
      VCard: { rounded: 'lg' },
    },
  })
  nuxtApp.vueApp.use(vuetify)
})
