# sentinel (rung A) -- 2026-08-30T23:57:36-05:00 -- DARK

Serve verified: 12 rgs_reference_main + 10 ms_empty_main + 4 rgs_restirgi
+ 77 dxil HITs, 0 ser_reject, manifest echo `sentinel ... ptq_sha=55ed4e...`.
Settings pinned in UserSettings.pre.json (PT on, RR off, DLSS Balanced, 1440p).

On screen: no magenta anywhere. Frame read as gi-50 (bleed absent, as designed
-- sentinel is built on the gi-50 base, not gi-50-bleed).

Escape hatches checked and closed BEFORE calling this a result:
- The audit's "dispatched raygens" list omitted rgs_reference_main. NOT
  evidence: trace_rays is deduped per VkPipeline via a cb->pipe table capped
  at MAX_CBBIND 1024 (swap_layer.c:728); once full, new command buffers are
  never registered and their traces go unlogged. All 9 trace_rays lines this
  launch fall in one early burst (seq 4641-4662 of 7256). rgs_restirgi_* has
  never appeared in ANY launch's dispatch list, yet gi-50's restirgi splice is
  confirmed on screen (50 sec 6). The list is a sample, not a census.
- Wrong-permutation risk: the 2 unpainted pass-throughs are 40c6faab52a13874
  and ab7f1822eeb0331b (the atomic pair, 55 sec 2). All 10 PAINTED
  permutations built pipelines this launch, including d622fb9e1dcb8cd0 and
  4270b745d11a5e8a -- the two 24 sec T1.4 recorded dispatching and tracing.

Verdict per the pre-registered table (55 sec 4): A dark => launch B.
Still open: trace dead (H2) vs miss-0 mapping vs payload round-trip.
