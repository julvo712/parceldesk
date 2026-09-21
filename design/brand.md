# ParcelDesk visual system

ParcelDesk is a fictional independent retailer's aftercare desk. The experience takes its cues from thoughtful packaging: a folded parcel mark, generous paper-like whitespace, restrained product photography and clear handoff receipts. A broad photographic landing page transitions into a practical order workspace. Customer language describes outcomes, never SDKs, scenarios or telemetry.

## Tokens
- Pine `#183f3d`: primary actions, brand and deep text; white text.
- Ink `#253a38`: text.
- Mist `#f3f7f5`: workspace background.
- White `#ffffff`: conversation, receipt and navigation.
- Sage `#e7f0eb`: secondary surface, success support.
- Amber `#9c5908`: attention text on `#fff3df`; never sole state indicator.
- Error `#a32d35`: error text on `#fff0f0`.

Typography uses system Avenir Next (Mac), Avenir and Segoe UI fallbacks, with a consistent geometric humanist voice. Display uses 56–76px, tight spacing, medium weight; page titles 32–40px; body 16px/1.6, metadata 13px. No remote fonts. Spacing grid: 4, 8, 12, 16, 24, 32, 48, 64px. Images own reserved aspect ratios. Corners reflect hierarchy: 24px hero, 18px major panels, 10px controls, fully rounded status pills.

## Layout
Desktop landing: quiet brand/navigation above a split editorial hero, help story on the left and generated domestic product photography on the right. Order screen: page introduction, horizontal cards, then a two-column conversation and order receipt. The mobile layout follows reading order with full-width actions and no hidden critical controls. The presenter console is a separate route/origin, with explicit operational language and evidence links.

## Interaction and accessibility
Visible 3px focus rings; native labelled buttons/inputs; skip link; live status region; errors include recovery actions. Keep the focused composer mounted while streaming. Bound retained message rendering to 100; refresh restores durable server state. Abort interrupts only browser streaming and recovery rereads server state; it never claims server cancellation. Confirmation keys persist per proposal and duplicate clicks are synchronously locked. Reduced motion disables decorative transitions; image dimensions prevent layout shifts. Never fake successful replacement, connectivity or telemetry.

## Imagery
Local generated hero, coordinated headphone/speaker/earbud product portraits, clean packaging and damaged-package detail. Imagery serves product identity and support context. Sources and optimization provenance live with root-managed assets. No stock hotlinks, remote image generation or simulated Grafana screenshots.
