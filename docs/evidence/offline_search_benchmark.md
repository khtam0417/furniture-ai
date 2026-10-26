# Offline search benchmark (SIMULATED / MOCKED timing)

Generated 2026-10-26 19:21 UTC by `.scratch/bench.py` with the test suite's fake network:
the same mocked web-search result (6 approved listing URLs on Chairish, AptDeco and Craigslist, one returning
HTTP 403) and an EQUAL simulated delay of 80 ms per page. No real network and no real AI calls (the search endpoint is mocked), so no real costs. These timings say
nothing about live speed; real pages vary.

| Page-check slots | Median time (s) | Runs (s) | Page requests | Peak pages in flight | Decision sets identical across runs |
|---|---|---|---|---|---|
| 1 | 0.594 | 0.732, 0.594, 0.583 | 6 | 1 | yes |
| 2 | 0.372 | 0.37, 0.372, 0.401 | 6 | 2 | yes |

- Same page requests serial vs parallel: **yes** (6 each); checked 6 pages with reasons {'verified': 5, 'access_blocked': 1} in both modes.
- Concurrency never exceeded 2 (peak observed: 2).
- Duplicate-search protection: two concurrent identical searches plus one repeat inside the cache window made **1** mocked AI search request(s).
- Costs stay estimates from returned usage (see usage.py); nothing here is an invoice.
