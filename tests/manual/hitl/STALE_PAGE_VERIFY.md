# Manual verification for VIOL-0099 (HITL stale-page UX)

The full failure mode is a real browser hitting a dead TCP port. pytest
cannot exercise that directly; the unit tests in
`tests/unit/test_hitl_stale_page.py` pin the markup and helper functions,
and this checklist covers the live flow.

## Pre-conditions

- A HITL-enabled workflow fixture (any of `examples/`).
- `hitl.timeout` set to ~15 seconds so the test runs in under a minute.
  Either edit the example workflow inline or use
  `defaults.hitl_timeout: 15`.

## Steps

1. Run the workflow:

   ```bash
   agac run -w <some_hitl_workflow> --resume
   ```

2. Open the printed URL in a browser.

3. Confirm the page shows a `Session expires in 00:15` banner immediately
   below the address bar. The MM:SS span ticks down once per second.

4. As the banner reaches roughly 00:05 (under `max(30, timeout/3)`),
   confirm the banner background turns red (CSS class `warning`).

5. Wait for the server to log idle-shutdown (banner reaches `00:00 expired`).

6. Click any record's "Approve" button.

7. **Confirm the page shows the fixed top-of-page red banner with the
   message:**

   > The HITL session has expired or the server is unreachable.
   > Re-launch with `agac run --resume` to continue.

   The literal substring `agac run --resume` must be visible. The
   browser MUST NOT show a bare `Failed to fetch` alert.

8. (Optional) Click "Submit". Confirm the same banner re-renders (the
   helper is idempotent — duplicate banners are suppressed).

If any step fails the VIOL is not closed. Capture browser console output
(F12 → Console) and attach to the PR.
