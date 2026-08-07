# Doubao Behaviors

## Interaction Model
- Sidebar: static on desktop; off-canvas on mobile. The original starts hidden at `390px` width with `transform: translateX(-280px)`.
- Header actions: hoverable buttons. Login/download do not need backend behavior for this static clone.
- Suggestion chips: hoverable prompt shortcuts. Visible text changes between sessions on the live site; clone uses captured examples from the desktop session.
- Composer: textarea placeholder is visible. Toolbar buttons are hoverable. Microphone button is a circular action at the right.

## Responsive Notes
- Desktop `1280px`: sidebar width `280px`; main width `1000px`; composer width `800px`, height about `100px`.
- Mobile `390px`: sidebar remains present but translated off-screen; main width `390px`; composer width about `358px` with `16px` side margins.
- Mobile suggestion chips are horizontally clipped/scrollable rather than reflowing to a fully visible stack.

## Extracted Design Tokens
- Page background: `rgb(252,252,252)`
- Sidebar background: `rgb(249,249,249)`
- Primary text: `rgb(0,0,0)` and `rgba(0,0,0,0.85)`
- Muted text: `rgba(0,0,0,0.35)` to `rgba(0,0,0,0.5)`
- Chip fill: `rgba(0,0,0,0.04)`
- Header/button border: `rgba(0,0,0,0.08)`
- Login button: `rgb(35,38,41)`
- Accent glow: blue/cyan shadow around composer
- Font stack: system UI with Chinese-capable fallbacks
