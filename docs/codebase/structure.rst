Structure
=========

Simplified diagram of inheritance, object visibility and data flow for a domain router:

.. mermaid::

    flowchart TD
        subgraph Legend
            direction LR
            L[Business Logic] -->|call| A[ ]
            BC{{Base Class}} -.->|inheritance| B[ ]
            M[[Model]] --o|object visibility| C[ ]
            CM(Context Manager) ---|wraps| D[ ]
            style A height:0px;
            style B height:0px;
            style C height:0px;
            style D height:0px;
        end

        USER((User))

        P_REPO{{Persistence Repository}}
        SQL_REPO{{SQL Repository}}

        P_MODELS{{Persistence Interface}}
        SQL_MODELS{{SQL Interface}}

        P_UOW{{Persistence UOW}}
        SQL_UOW(SQL UOW)

        SDK_MODELS[[SDK Models]]

        D_REPO[Domain Repository]
        D_MODELS[[Domain Models]]
        D_SQL[[Domain SQL Interface]]
        D_SERVICE[Domain Service]
        D_ROUTES[Domain Routes]

        DB[(SQL DB)]

        USER--oSDK_MODELS
        USER-->D_ROUTES
        SQL_REPO-.->D_REPO
        SQL_UOW---D_SERVICE
        D_ROUTES-->D_SERVICE
        D_SERVICE-->D_REPO
        SDK_MODELS--oD_MODELS
        D_MODELS--oD_SERVICE
        D_MODELS--oD_ROUTES
        P_UOW-.->SQL_UOW
        P_REPO-.->SQL_REPO
        P_MODELS-.->SQL_MODELS
        SQL_MODELS-.->D_SQL
        D_SQL-->D_REPO
        D_SQL-->DB

Below is an overview of the project structure.

Core
----

- **Operational Classes:** Used for aspects like authentication, configuration, and logging.

Domain
------

Contains a directory for each set of related structures. Each directory includes:

- **Models**

  - **Models:** Domain models used throughout the domain.
    - **SDK Models:** Models provided by the SDK that are used for interfacing with the API.
  - **Persistence (e.g. SQL):** Models used for persisting to data stores, including translation methods to/from domain models.

- **Repository**

  - Contains interfaces between the domain and persistence implementations. It only accepts domain models as input and output, using the DTO for any persistence changes.

- **Routes**

  - Provides the FastAPI router for external interfacing and generates Units of Work (UOWs) for the service.

- **Service**

  - Performs business processing and logic.
  - Note that some functions are decorated with UoWs, and others aren't. Careful decision needs to be made to where the UoW boundary is drawn. Don't worry, if you try to call a decorated function from within a decorated function the app will tell you!

Persistence
-----------

- **Base Classes:** For each persistence implementation to inherit.
  - **Persistence implementation (SQL):** Base classes designed for each domain module to inherit, and the interface to the data store itself (e.g., a SQL session generator).
