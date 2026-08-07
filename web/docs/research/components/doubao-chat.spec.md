# DoubaoChat Specification

## Overview
- Target file: `src/app/page.tsx`
- Screenshots:
  - `docs/design-references/doubao/desktop-1280.png`
  - `docs/design-references/doubao/mobile-390.png`
- Interaction model: mostly static with hover states and mobile sidebar toggle.

## DOM Structure
- Root viewport container
- Sidebar navigation
  - Brand row with avatar and `豆包`
  - Navigation items: `新对话`, `AI 创作`, `更多`
  - Footer item: `关于豆包`
- Main chat area
  - Header with sidebar icon, centered title/subtitle, download and login buttons
  - Welcome section with heading and prompt chips
  - Composer with textarea placeholder, toolbar buttons, and microphone button

## Computed Styles

### Sidebar
- width: `280px`
- height: `100dvh`
- background: `rgb(249,249,249)`
- item height: `36px`
- item radius: `10px`
- item padding: `0 8px`

### Main
- background: `rgb(252,252,252)`
- desktop width: remaining viewport after `280px` sidebar
- mobile width: `100vw`

### Header
- height: `56px`
- border bottom: `1px solid rgba(0,0,0,0.06)`
- title: `14px`, `500`
- subtitle: `11px`, muted

### Greeting
- text: `你好，我是豆包`
- desktop font size: about `30px`, weight `700`
- mobile font size: about `28px`, weight `700`

### Prompt Chips
- background: `rgba(0,0,0,0.04)`
- border radius: `12px`
- font size: `14px`
- desktop: multiple centered rows with `8px` gaps
- mobile: horizontally clipped rows, no full wrapping guarantee

### Composer
- desktop: `800px` wide, about `100px` tall, bottom `18px`
- mobile: `calc(100vw - 32px)` wide, bottom `16px`
- background: white
- radius: `28px`
- border: pale blue-gray
- shadow: soft blue glow
- textarea font: `16px`, line-height `24px`
- placeholder: muted gray

## Assets
- Avatar: `public/images/doubao/doubao-avatar.png`
- Windows download icon: `public/images/doubao/download-windows.svg`

## Responsive Behavior
- Desktop: sidebar visible, main centered content, all toolbar options visible.
- Mobile: sidebar hidden off-canvas, header buttons remain on the right, composer compresses and hides less important toolbar options.
