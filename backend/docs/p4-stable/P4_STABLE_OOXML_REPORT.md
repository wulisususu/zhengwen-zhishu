# P4 Stable OOXML Report

P4 explicit-target detector exercised 7 configured targets across slides 1–4 and no timing on slide 5. It validates timing placement and target shape IDs.

The browser export artifact `pptedit_pptproj_32e720384418488a913f5ff25706f799_a1ee461aa7e343feab77817cc04e27fa_20260724_213434.pptx` passed ZIP inspection. Slide 1 contains one `fade` timing target (`spid=75`, `clickEffect`); slides 2–5 have no emitted timing for that focused browser export.

`fa85b313` adds a converter regression: an explicit `on-click` override survives writer read-back instead of being compared to slide default `after-previous`.
