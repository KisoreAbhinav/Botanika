# Botanika Build Prompt Entry Point

The authoritative implementation prompt is:

**[BOTANIKA_PI_APP_IMPLEMENTATION_PROMPT.md](BOTANIKA_PI_APP_IMPLEMENTATION_PROMPT.md)**

It preserves the complete Botanika product architecture and 800×480 InnoHack-
derived UI specification while enforcing this dependency order:

- Phase 0: Environment and native camera verification
- Phase 1: Raw Pi Camera feed in Botanika’s Python code
- Phase 2: Generic pretrained YOLO detection
- Phase 3: Stability, blur, lock-on, and crop-only capture
- Phase 4: Deterministic dummy classifier and complete pipeline proof
- Phase 5: Standalone 800×480 Pi UI using the dummy pipeline
- Phase 6: Real seven-or-more-species classifier, knowledge data, and library
- Phase 7: Private Pi Wi-Fi access point and FastAPI reachability
- Phase 8: Responsive paired client and SOLO/NETWORKED handoff
- Phase 9: Optional botanical voice guide, gamification, weed beta, and hardening

Each numbered build phase in the full prompt has its own work list, tests, and
“you know it worked when” gate. Implement only one phase per handoff. Do not skip
ahead, and do not begin networking before the complete real-species standalone
Pi flow passes.
