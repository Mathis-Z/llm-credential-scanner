# Testing Setup

(Work in progress)

Running the tests will prune all containers and networks!

Use `python3 -m scanner.tests.tests --keep` to run the default test-network set and keep the DB files produced. Each app gets its own DB in `/tmp`.

Use `python3 -m scanner.tests.tests -e --keep` (or `--evaluation`) to run the evaluation-network set instead.

You can combine either mode with app selection:

- `python3 -m scanner.tests.tests -s BookStack,4gaBoards`
- `python3 -m scanner.tests.tests -e -s ActiveMQ,Casdoor`
