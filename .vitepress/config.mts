import { defineConfig } from 'vitepress'

export default defineConfig({
  title: '河南移动 IPTV',
  description: '河南移动 IPTV 直播源、频道列表与维护说明',
  base: process.env.DOCS_BASE || '/',
  cleanUrls: true,
  srcExclude: ['reports/**'],
  themeConfig: {
    nav: [
      { text: '首页', link: '/' },
      { text: '快速开始', link: '/start' },
      { text: '频道列表', link: '/channels' },
      {
        text: '使用与维护',
        items: [
          { text: '订阅地址', link: '/usage' },
          { text: '播放排查', link: '/troubleshooting' },
          { text: '源状态', link: '/status' },
          { text: '维护说明', link: '/maintain' }
        ]
      }
    ],
    sidebar: [
      {
        text: '开始',
        items: [
          { text: '首页', link: '/' },
          { text: '快速开始', link: '/start' },
          { text: '订阅地址', link: '/usage' }
        ]
      },
      {
        text: '频道',
        items: [
          { text: '频道列表', link: '/channels' },
          { text: '源状态', link: '/status' }
        ]
      },
      {
        text: '维护',
        items: [
          { text: '播放排查', link: '/troubleshooting' },
          { text: '维护说明', link: '/maintain' }
        ]
      }
    ],
    socialLinks: [
      { icon: 'github', link: 'https://github.com/Elykia093/HA-CMCC-IPTV' }
    ]
  }
})
