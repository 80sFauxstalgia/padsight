# Engineering notes

Lessons that aren't obvious from the code. One section per topic; add to it when a fix teaches something.

## Contents
- [obs-websocket vendor requests](#obs-websocket-vendor-requests)

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
