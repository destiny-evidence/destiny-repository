# Robots Guide

This document covers the robots domain internals.

## Overview

Robots are external services that process enhancement requests. They receive batches of references, perform analysis (e.g., classification, annotation), and return results.

## Robot Model

See `app/domain/robots/models/models.py`:

- **id** - UUID identifier
- **name** - Human-readable name
- **description** - What the robot does
- **owner** - Contact/owner information
- **client_secret** - Secret for request signing (SecretStr)

## Authentication

Robots authenticate using their `client_secret`. The secret is:

- Generated on robot creation (32 bytes hex)
- Can be cycled via `cycle_robot_secret()`
- Stored as `SecretStr` to prevent accidental logging

## Key Operations

See `app/domain/robots/service.py`:

- `add_robot()` - Register new robot, generates secret
- `get_robot_secret()` - Retrieve secret for signing
- `cycle_robot_secret()` - Rotate the secret
- `update_robot()` - Update robot metadata

## Enhancement Batches

Robots receive work via `RobotEnhancementBatch`:

1. System creates batch with pending enhancements
2. Robot polls for available batches
3. Robot processes references and returns results
4. System imports returned enhancements

See `app/domain/references/services/enhancement_service.py` for batch processing.

## Related Files

- **Models**: `app/domain/robots/models/models.py`, `sql.py`
- **Service**: `app/domain/robots/service.py`
- **Routes**: `app/domain/robots/routes.py`
- **SDK client**: `libs/sdk/src/destiny_sdk/robot_client.py`
- **Sphinx docs**: `docs/procedures/robot-automation.rst`, `docs/procedures/robot-registration.rst`
