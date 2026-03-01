# Chat E2E Validation

Purpose: validate the final conversation path end-to-end against a running Didier instance.

## Scenario
- written question
- visible thinking phase (`/asr/status` reports `thinking=true` or `state=THINKING`)
- written response
- audio queued

## Command

```bash
python3 scripts/validate_chat_e2e.py \
  --ask-url http://127.0.0.1:5010/ask-and-speak \
  --status-url http://127.0.0.1:5010/asr/status \
  --out logs/chat_e2e_validation.json
```

## Success Criteria
- process exit code is `0`
- report field `ok` is `true`
- report field `thinking_seen` is `true`
- report field `audio` is `true`
- report field `response` is non-empty

## Notes
- Use `--allow-missing-audio` only when debugging an environment where audio is intentionally disabled or busy.
- Use `--allow-missing-thinking` only when debugging a very short local fast-path response that does not hit the main LLM path.
