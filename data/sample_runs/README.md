# Sample runs

Five vendors carried end to end, with the decision a judge sees and the full
event trace behind it. Together they cover all three outcomes.

| input | case | decision |
|---|---|---|
| `V0001` | Exact alias of a listed entity; the name gives nothing away | **BLOCK** |
| `V0003` | Fuzzy overlap with the same anchor, different jurisdiction | **CLEAR** |
| `V0004` | Clean on its own name; the control chain reaches a listed entity | **BLOCK** |
| `V0005` | Name too generic to resolve against a watchlist | **ESCALATE** |
| `V0009` | Real company, real GLEIF chain to a real OFAC-designated parent | **BLOCK** |

`<vendor>.out.txt` is the decision, evidence, caveats and the question put back
to the reviewer. `<vendor>.trace.jsonl` is one JSON event per line: every agent
turn, tool call, branch taken and critic verdict, in order.

Reproduce any of them:

```bash
python -m clearline.run --vendor V0001 --fake
```

Generated in fixture mode against an empty memory, which is what a fresh clone
has, so these files are what the command prints on a clean checkout. The traces
here are copies; live runs write to `logs/`, which is not tracked.
