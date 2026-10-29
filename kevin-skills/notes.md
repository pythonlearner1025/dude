# Coach notes

- 2026-10-29: m8py no longer sends tickets; you now watch observation packets. The actor's
  `nofit` answer is gone (it answers a skill or `keep`), but `actor/prompt.md` still mentions
  nofit in a few places (and `tests/test_review_1154.py` checks one of them): clean these up
  when you next touch the prompt.
- Speech recognition mishears short orders ("peek out" came through as "speak out", "keep
  doubt", "seek out"). Worth examples in the prompt if you see it again.
- Check next: does `lead` (f669f6e) now keep going ahead of the player and out of their line of
  fire? It was written after the player had stopped playing; no packet has shown it live yet.
