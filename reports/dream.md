# Dream replay

- source run: `dream_skills_k3`
- harness: `h0`
- winner: **test_gated**
- note: best_of_k_oracle is an upper bound, never deployed.

| policy | score | passed | calls | tokens out | value |
|---|---|---|---|---|---|
| `first` | 0.75 | 9/12 | 12 | 1484 | 0.690 |
| `longest` | 0.67 | 8/12 | 36 | 4663 | 0.487 |
| `majority` | 0.75 | 9/12 | 36 | 4663 | 0.570 |
| `test_gated` | 0.83 | 10/12 | 36 | 4663 | 0.653 |
| `best_of_k_oracle` | 0.83 | 10/12 | 36 | 4663 | 0.653 |

This is offline policy search over cached candidates. It makes no model
calls and does not claim a new prompt was evaluated. The winner is chosen
by score; tokens break ties. `value` is diagnostic. `best_of_k_oracle`
is an upper bound and is never deployed.

