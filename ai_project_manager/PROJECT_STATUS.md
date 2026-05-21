# Project Status

## Blue-Green Production Runtime Baseline

As of 2026-05-19, current production traffic path is:

```text
Cloudflare Tunnel -> 127.0.0.1:18000 -> bluegreen_proxy_candidate -> web_blue / web_green
```

- Rollback target remains `127.0.0.1:8000`.
- `bluegreen_proxy_candidate`, `web_blue`, and `web_green` must remain running.
- Do not stop or remove the old `8000` path yet.
- Real deploy or switch actions require the deployment lock.
- Django autoreload stabilization is documented in
  `docs/BLUE_GREEN_RUNTIME_AUTO_RELOAD_FIX_PLAN.md`; source/config now adds
  `--noreload` for `web`, `web_blue`, and `web_green`, but running containers
  have not been recreated, so runtime behavior is unchanged until a separate
  controlled apply is approved under the deployment lock.
- Future Docker/deploy tasks must read `docs/SAFE_DEPLOY.md` and `docs/BLUE_GREEN_LONG_TERM_OPERATIONS.md` before changing runtime.
