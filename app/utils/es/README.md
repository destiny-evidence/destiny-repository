# Automated ES Migrations

The es_migrator script in this directory is used for performing automated elasticsearch index migrations to update document mappings etc.

Logs from all processes are viewable in Honeycomb.

## Running on Azure

Migrations are run via a `es-index-migrator-[ENV]` container app job which can be triggered manually with a command override.

- Note that you need to both save _AND THEN_ apply the command changes when inputting them into the UI.
- Note that command needs to be separated by commas at every space like `python, -m, app.utils.es.es_migration, --migrate, --alias, reference`

## Migrate an index

To migrate an index to a new index with updated mappings based on document class use the following

```zsh
python -m app.utils.es.es_migration --migrate --alias reference
```

If you want to change the number of shards, specify with the `-n` or `--number-of-shards` argument. If not specified, it will assume the shard count on the index the alias currently points to.

```zsh
python -m app.utils.es.es_migration --migrate --alias reference --number-of-shards 50
```

## Rollback an index

If a migration is incompatible with the application, you can roll back to the previous index using

```zsh
python -m app.utils.es.es_migration --rollback --alias reference
```

OR

```zsh
python -m app.utils.es.es_migration --rollback --alias reference --target-index an_old_reference_index
```

Which will switch the alias back to the old index

## Delete an index

For cleaning up once a migration has been verified to be successful

```zsh
python -m app.utils.es.es_migration --delete --target-index reference_v1
```
