# Execution and evidence

Run bounded commands and collect sanitized reports from the isolated Box. Requires
a provisioned environment from the [parent runbook](../README.md).

```sh
./devctl --name review report
./devctl --name review report REPORT_ID --output /private/evidence
```

## Development

Run the [environment checks](../tests/README.md#development), then inspect a fresh
Run report for correct source identity, bounded execution and sanitized output.
