# Trigger Cases

These fixtures test whether the frontmatter description routes the skill at the right boundary.

- `trigger_cases.json`: primary regression set (Chinese and English positives, exclusions, near neighbors).
- `holdout/trigger_cases.json`: internal holdout-style regression set. It was authored during package creation and is **not** blind or independently labeled evidence.
- `semantic_config.json`: deterministic concept weights used by `trigger_eval.py`. It is a routing proxy, not a model-quality benchmark.

Run:

```bash
python3 /path/to/yao-meta-skill/scripts/trigger_eval.py \
  --description-file SKILL.md \
  --cases evals/trigger_cases.json \
  --semantic-config evals/semantic_config.json

python3 /path/to/yao-meta-skill/scripts/trigger_eval.py \
  --description-file SKILL.md \
  --cases evals/holdout/trigger_cases.json \
  --semantic-config evals/semantic_config.json
```

No provider-backed trigger evaluation has been run. Do not present these local checks as independent or blind evidence.
