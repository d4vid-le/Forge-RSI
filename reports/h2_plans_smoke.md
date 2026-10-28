# H2.3 composition smoke (engineering only)

This is a one-task pre-flight of the plan executor, not the H2.3 experiment. Stage 3 was not run because Stage 1 stopped.

| arm | passed | intermediate | preserved | tokens |
|---|---|---|---|---|
| single | 0/1 | 0/1 | 0/1 | 251 |
| forward | 1/1 | 1/1 | 1/1 | 692 |

`comp_01` asks for both `word_freq` and `merge_intervals`. The forward arm ran word_freq with its own adapter, verified the intermediate function, then ran merge_intervals on the preserved code. The final compound test passed. This is a mechanism signal for a separate pre-registered H2.3 run, not a composition result.
