# Cold-answer capstone test (2026-10-04)

Opus 5 answers each lab curriculum's capstone question given only the hypothesis
statement and the experiment titles: no data, no tools, no lesson cards. Model and
call settings match the lab's capstone (`lab/engine/provider.py`): `claude-opus-5`,
adaptive thinking, effort `high`, `max_tokens` 16000, no tools. Five samples per
curriculum, each scored in-process with that curriculum's own scorer and private
ground truth from `lab/` at `aa18672` (PR #37).

| File | Contents |
|---|---|
| `cold_test.py` | The script: prompt construction, the exact edits made to each capstone task (only sentences referring to lessons, the data file, or results "you established" are removed; each edit is asserted to match exactly once), and scoring |
| `prompt_glp1r.txt`, `prompt_wrn.txt` | The exact system and user prompts sent |
| `cold_results.json` | Every raw response, the parsed answer, stated confidence, score and full scorer details |
| `run.log` | Console summary of the run |

Before any API call, both scorers were checked to return 0.0 for an empty answer
and 1.0 for a gold answer.

GLP-1R sample 4 returned JSON with a trailing comma. It is counted as a parse
failure and left out of the mean. Its `repair_note` records the score with only
that comma removed (0.79), reported separately.

## Results

| | GLP-1R (exp6) | WRN (h2exp2) |
|---|---|---|
| Scores | 0.875, 1.00, 1.00, 0.917, parse failure | 0.40, 0.40, 0.40, 0.50, 0.50 |
| Mean | 0.95 (4 parsed of 5) | 0.44 (explanation half 0.88; ranking half 0.00, see the WRN scorer issue) |
| Stated confidence | 0.84, 0.82, 0.85, 0.82 (sample 4: 0.84) | 0.85, 0.86, 0.86 (two answers omitted it) |
| Lab capstone, for comparison | 1.00 with lessons (`replays/demo`, stated confidence 0.75), 0.79 without (`replays/control`, 0.68) | no committed WRN run |
