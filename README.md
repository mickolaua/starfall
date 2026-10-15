**STARFALL** is the software for automatic processing of astronomical images. It was designed for 
both user submissions via web UI and software clients via REST API and consists of several services 
(see description below). 

# STARFALL services

## job-viewer

```Job-Viewer``` is a site designed to run user jobs via convenient web UI or via requests to the 
REST API. Proceed to the [job-viewer](job-viewer) page in this repository to learn more about deployment 
and running this service.

## orchestrator

```orchestrator``` is the software for running and managing processing jobs. For this role 
```prefect``` was preferred to Apache Airflow after initial stage of development. More details 
described in the [orchestrator](orchestrator) folder in this repository. 


# Versioning

per-package SemVer via Conventional Commits and Release Please.
See [docs/VERSIONING.md](docs/VERSIONING.md) for commit scopes, tags
(`{package}-vX.Y.Z`), and the release-PR workflow.