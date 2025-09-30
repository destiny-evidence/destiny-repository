# TODO

- Use proper logger -[x] Fix index prefix
- Document first time setup/include in setup scripts
- Initialize indexes as part of test setup

## 3 Scenarios

- When is nothing/from scratch [Done]
- Current production (index requiring update, with no alias)

  ## Steps Required

  1. [m] Create the alias for the current index (even if it's badly named)
  2. [c] Make clients point to alias (running repo, demonstrator)
  3. [s] Make a new index with good name, proper mapping
  4. [s] Reindex data to new index
  5. [m] ?Maybe? stop writes to old index
  6. [s] Do (?filtered?) re-index to top-up
  7. [s] Change alias to point to new index
  8. [m] Restart workers

- Once we're up and running (index requiring update, with alias)
