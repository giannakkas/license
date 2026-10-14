# OnCue licensing

Two parts that ship together:

| Folder | What it is |
| --- | --- |
| [`platform/`](platform/README.md) | The licensing platform at **https://license.oncue.cy**: softwares, customers, serial keys, activated computers, remote lock and revoke, offline licence files, and the public download links for each software's builds. Next.js 16 + Prisma 7 on PostgreSQL, deployed on Railway (project `licensing`, service `player`, root directory `/platform`); every push to `main` deploys. |
| [`monitor/`](monitor/README.md) | The **Monitoring Application** (`MonitoringApp.exe`): a Windows multiviewer with live audio meters and QC alarms, the first software licensed through the platform. Python, Qt and libmpv, built into one exe with PyInstaller (`monitor/build-wine.sh` cross-builds it on Linux). |

A new program joins the platform by registering a software there (its slug) and using the
same device API as `monitor/barpi_monitor/license.py`; see the platform README.
