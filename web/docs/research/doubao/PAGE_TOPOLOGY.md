# Doubao Page Topology

Target: `https://www.doubao.com/chat/`

## Viewports Captured
- Desktop: `docs/design-references/doubao/desktop-1280.png`
- Mobile: `docs/design-references/doubao/mobile-390.png`

## Sections
- Sidebar: 280px left column on desktop, off-canvas on mobile. Contains logo, primary navigation, and footer links.
- Header: 56px top bar inside the main content. Center title/subtitle, sidebar toggle on the left, download and login actions on the right.
- Welcome prompt area: centered greeting with 3 rows of suggestion chips on desktop; clipped horizontal chip area on mobile.
- Composer: fixed bottom chat input, 800px wide desktop and full-width mobile with action buttons and a round microphone button.

## Layout
- Body is a single non-scrolling viewport.
- Desktop uses `display: flex`: fixed 280px sidebar plus flexible main panel.
- Main panel background is near-white `rgb(252,252,252)`.
- Composer is anchored near the bottom and horizontally centered within main content.
- Mobile hides sidebar off-canvas and lets the main panel occupy the full width.
