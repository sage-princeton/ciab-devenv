# Local fixtures

Protocol fixtures and diagnostics used by the isolated Box. Fixture configuration
and limitations are in [operations.md](../operations.md#local-services-and-fixtures).

After changing a fixture, restart its named service and run:

```sh
./devctl --name review doctor
python3 -m unittest discover -s tests -p test_fixtures.py
```
