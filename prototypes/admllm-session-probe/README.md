# admllm Session Probe

Small isolated probe for checking whether `admllm.data-light.ru` supports
Responses API session continuity and related long-running helpers.

The probe does not import the Gate Challenger application, does not read the
database, and does not use real documents. It sends only synthetic marker text.

## Checks

- `POST /v1/responses`
- `previous_response_id` follow-up behavior
- `GET /v1/responses/{response_id}`
- `GET /v1/responses/{response_id}/input_items`
- `POST /v1/responses` with `background=true`
- `GET /v1/responses/{polling_id}` polling
- `POST /v1/responses/compact`

## Run

Preferred:

```bash
export ADMLLM_API_KEY="sk-..."
python3 prototypes/admllm-session-probe/probe.py \
  --model openai/gpt-5.5 \
  --output /tmp/admllm-session-probe-result.json
```

Without exporting the key:

```bash
printf '%s\n' "$ADMLLM_API_KEY" | python3 prototypes/admllm-session-probe/probe.py \
  --api-key-stdin \
  --model openai/gpt-5.5 \
  --output /tmp/admllm-session-probe-result.json
```

If the proxy requires `x-litellm-api-key` instead of `Authorization: Bearer`,
add:

```bash
--auth-header x-litellm-api-key
```

## Interpret

The key fields are:

- `summary.previous_response_id_supported`: second request with
  `previous_response_id` returned successfully.
- `summary.followup_remembered_marker`: the model answered with the synthetic
  marker from the first response without the script resending it.
- `summary.background_supported`: `background=true` request was accepted.
- `summary.compact_supported`: `/responses/compact` was accepted.

If `previous_response_id_supported` is true but `followup_remembered_marker` is
false, the endpoint accepts the parameter but may not preserve usable context
for this model/proxy route.

The report redacts API-key-shaped strings before printing or writing JSON.
