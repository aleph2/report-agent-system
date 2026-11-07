# Fake04 evidence controls

The four synthetic PDFs describe North and South. The survey names a search area, a measured facility, borehole and pit counts, and a groundwater observation with a depth and date. Separate hazard histories give explicit counts and periods for the two sites. A design inventory, a sheet reference and a checked drawing supply different levels of information about the design.

Each entry in `attestations.json` identifies its source page, exact quote, subject and scope. The original pages are in `inputs/`. The file contains observations and source limitations. The expected acceptance or refusal of a claim is kept in `tests/test_fake04_claim_controls.py`, outside the source materials.

This fixture exercises the claim validator offline. It does not supply an approved commission plan or a complete engineering assessment.
