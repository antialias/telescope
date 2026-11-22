# Test fixtures

`starsense_frame.hex`: one StarSense star list as it travelled on the AUX
bus, written as hex text. It is copied unchanged from the celestron-aux
toolkit (github.com/platini2/celestron-aux, `tests/fixtures/starsense_frame.hex`,
release 1.2.2, commit ad19991), which is GPL-3.0, Copyright 2021-2026 Patricio
Latini. The toolkit does not say whose camera recorded it, or where or when.
It is not from our camera.

It holds 99 stars, brightest first. `test_solver.py` plate solves it.
