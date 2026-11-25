# Survey document template

Save as `docs/development/<topic>-survey.md`. Keep facts and judgement
visibly separate.

```markdown
# <Topic>: survey and recommendation

Stage 1. No implementation. Measured on <machine, OS build, Python version>,
<date>, at commit <sha>. Anything that is a judgement is labelled as one.

## 1. Question and the decision it feeds
<one paragraph>

## 2. Constraints
<the rows from the skill's constraint table that matter here>

## 3. What the repo already has
<paths, extras, earlier surveys; why it is or is not enough>

## 4. Options
| Option | Licence | Offline | Windows wheel | Install size | Notes |
|---|---|---|---|---|---|
| A | | | | | |
| B | | | | | |
| Extend existing | | | | | |
| Do nothing | | | | | |

Sources (read on <date>):
- <URL> — <what it established>

## 5. Measurements
| Option | Metric | Runs | Median | Range |
|---|---|---|---|---|

Not measured, and why: <...>

## 6. Recommendation
<option and the one-sentence reason> (judgement)

## 7. Smallest useful version
<the first PR-sized slice, with its acceptance check>

## 8. What I would not build
<scope deliberately left out>

## 9. Open questions for Captain
<only those that change the decision>
```
