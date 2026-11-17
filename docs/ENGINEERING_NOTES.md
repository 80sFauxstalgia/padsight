# Engineering notes

Lessons that aren't obvious from the code. One section per topic; add to it when a fix teaches something.

## Contents
- [obs-websocket vendor requests](#obs-websocket-vendor-requests)
- [Panel CSS and text in older docks](#panel-css-and-text-in-older-docks)

## obs-websocket vendor requests
- **A vendor request succeeds whenever the vendor answered.** `CallVendorRequest` returns request status `result: true`
  as soon as the plugin's callback ran. The plugin's own refusal is inside `responseData`, for example
  `{"success": false, "error": "..."}`. Read it there, or a refused stop shows as "Stopping".
  See `StreamTargets.VendorRefusal`.
- **Without a success flag, only `error` means a refusal.** A field such as `message` may just describe a success
  ("Started").
- **Treat the vendor's text as untrusted.** Reasons and OBS error comments go through `StreamTargets.SafeText` before
  they are shown: text with control or bidi characters is replaced, and long text is capped.
- **Not yet confirmed against a real OBS:** the exact shape and wording of Aitum Multistream's refusal for `stop_output`
  on an output that isn't running. The test mock uses `{"success": false, "error": "output is not running"}`.

## Panel CSS and text in older docks
- **`color-mix()` with `var()` needs `@supports`.** A declaration containing `var()` counts as valid at parse time, so a
  plain `rgba()` fallback written earlier in the same rule is replaced. In older Chromium (e.g. the OBS 29 dock), the
  `color-mix()` then fails at computed time and the property drops to its initial value. Keep the `rgba()` in the base
  rule and set `color-mix()` only inside `@supports (background: color-mix(in srgb, red 50%, transparent))`.
- **Strip bidi controls before an FSI/PDI isolate.** A PDI inside a name closes our isolate, and an unmatched opener
  swallows our PDI, so the text after the name gets reordered. `Isolate()` (C#) and `iso()` / `stripBidi()` (panel.js)
  remove every bidi control from the display text first. Values and data attributes keep the raw name.
