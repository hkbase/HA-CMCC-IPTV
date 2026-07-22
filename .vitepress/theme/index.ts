import DefaultTheme from 'vitepress/theme'
import ChannelDirectory from './components/ChannelDirectory.vue'
import HomeSignalPanel from './components/HomeSignalPanel.vue'
import StatusSummary from './components/StatusSummary.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component('ChannelDirectory', ChannelDirectory)
    app.component('HomeSignalPanel', HomeSignalPanel)
    app.component('StatusSummary', StatusSummary)
  }
}
